from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..database import Database
from ..models import (
    PhraseCategory,
    PhraseLibraryMutationRequest,
    PhraseLibraryState,
    PhraseSnippet,
    utcnow,
)
from ..phrase_library_schemas import (
    PhraseActivationInput,
    PhraseCategoryCreateInput,
    PhraseCategoryView,
    PhraseCreateInput,
    PhraseLibraryView,
    PhraseReorderInput,
    PhraseSnippetView,
    PhraseUpdateInput,
)


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class PhraseLibraryError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        status_code: int = 400,
        *,
        revision: int | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code
        self.revision = revision


class PhraseLibraryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _state(session: Session) -> PhraseLibraryState:
        state = session.get(PhraseLibraryState, "global")
        if state is None:
            raise PhraseLibraryError(
                "schema_incomplete",
                "话术库结构不完整，请检查本地数据库迁移",
                500,
            )
        return state

    @staticmethod
    def _request(
        session: Session,
        request_id: str,
        operation: str,
        payload: dict[str, Any],
    ) -> PhraseLibraryView | None:
        row = session.get(PhraseLibraryMutationRequest, request_id)
        if row is None:
            return None
        if row.operation != operation or row.payload_hash != _payload_hash(payload):
            raise PhraseLibraryError(
                "request_id_reused",
                "该请求编号已用于不同的话术操作，请刷新后重试",
                409,
            )
        stored = PhraseLibraryView.model_validate(json.loads(row.result_json or "{}"))
        return stored.model_copy(update={"idempotent": True})

    @staticmethod
    def _record_request(
        session: Session,
        request_id: str,
        operation: str,
        payload: dict[str, Any],
        result: PhraseLibraryView,
    ) -> None:
        session.add(
            PhraseLibraryMutationRequest(
                request_id=request_id,
                operation=operation,
                payload_hash=_payload_hash(payload),
                result_json=_canonical(result.model_dump(mode="json")),
            )
        )

    @staticmethod
    def _require_revision(
        session: Session,
        expected_revision: int,
    ) -> PhraseLibraryState:
        state = PhraseLibraryService._state(session)
        if state.revision != expected_revision:
            raise PhraseLibraryError(
                "revision_conflict",
                "话术库已在其他页面更新，请刷新后重试",
                409,
                revision=state.revision,
            )
        return state

    @staticmethod
    def _bump_revision(
        session: Session,
        state: PhraseLibraryState,
        expected_revision: int,
    ) -> int:
        next_revision = expected_revision + 1
        result = session.execute(
            update(PhraseLibraryState)
            .where(
                PhraseLibraryState.id == "global",
                PhraseLibraryState.revision == expected_revision,
            )
            .values(revision=next_revision, updated_at=utcnow())
        )
        if result.rowcount != 1:
            session.expire(state)
            current = PhraseLibraryService._state(session).revision
            raise PhraseLibraryError(
                "revision_conflict",
                "话术库已在其他页面更新，请刷新后重试",
                409,
                revision=current,
            )
        state.revision = next_revision
        return next_revision

    @staticmethod
    def _snapshot(session: Session, *, idempotent: bool = False) -> PhraseLibraryView:
        state = PhraseLibraryService._state(session)
        categories = list(
            session.scalars(
                select(PhraseCategory)
                .where(PhraseCategory.active.is_(True))
                .order_by(PhraseCategory.position, PhraseCategory.created_at, PhraseCategory.id)
            )
        )
        category_ids = [row.id for row in categories]
        phrases = (
            list(
                session.scalars(
                    select(PhraseSnippet)
                    .where(PhraseSnippet.category_id.in_(category_ids))
                    .order_by(
                        PhraseSnippet.category_id,
                        PhraseSnippet.active.desc(),
                        PhraseSnippet.position,
                        PhraseSnippet.created_at,
                        PhraseSnippet.id,
                    )
                )
            )
            if category_ids
            else []
        )
        grouped: dict[str, list[PhraseSnippetView]] = {row.id: [] for row in categories}
        for row in phrases:
            grouped[row.category_id].append(
                PhraseSnippetView(
                    id=row.id,
                    category_id=row.category_id,
                    content=row.content,
                    position=row.position,
                    active=row.active,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return PhraseLibraryView(
            revision=state.revision,
            categories=[
                PhraseCategoryView(
                    id=row.id,
                    category_key=row.category_key,
                    name=row.name,
                    source=row.source,
                    position=row.position,
                    active=row.active,
                    phrases=grouped[row.id],
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in categories
            ],
            idempotent=idempotent,
        )

    def view(self) -> PhraseLibraryView:
        with self.database.session() as session:
            return self._snapshot(session)

    def create_category(self, input: PhraseCategoryCreateInput) -> PhraseLibraryView:
        name = input.name.strip()
        if not name:
            raise PhraseLibraryError("category_name_empty", "分类名称不能为空")
        payload = {"expected_revision": input.expected_revision, "name": name}
        with self.database.session() as session:
            replay = self._request(session, input.request_id, "create_category", payload)
            if replay is not None:
                return replay
            state = self._require_revision(session, input.expected_revision)
            max_position = session.scalar(select(func.max(PhraseCategory.position)))
            category_id = f"phrase-category-{uuid4()}"
            session.add(
                PhraseCategory(
                    id=category_id,
                    category_key=f"custom:{uuid4()}",
                    name=name,
                    source="custom",
                    position=int(max_position if max_position is not None else -1) + 1,
                    active=True,
                )
            )
            session.flush()
            self._bump_revision(session, state, input.expected_revision)
            result = self._snapshot(session)
            self._record_request(
                session, input.request_id, "create_category", payload, result
            )
            session.commit()
            return result

    def create_phrase(self, input: PhraseCreateInput) -> PhraseLibraryView:
        if not input.content.strip():
            raise PhraseLibraryError("phrase_empty", "话术内容不能为空")
        payload = {
            "expected_revision": input.expected_revision,
            "category_id": input.category_id,
            "content": input.content,
        }
        with self.database.session() as session:
            replay = self._request(session, input.request_id, "create_phrase", payload)
            if replay is not None:
                return replay
            state = self._require_revision(session, input.expected_revision)
            category = session.get(PhraseCategory, input.category_id)
            if category is None or not category.active:
                raise PhraseLibraryError("category_missing", "所选话术分类不存在", 404)
            max_position = session.scalar(
                select(func.max(PhraseSnippet.position)).where(
                    PhraseSnippet.category_id == category.id,
                    PhraseSnippet.active.is_(True),
                )
            )
            session.add(
                PhraseSnippet(
                    id=f"phrase-{uuid4()}",
                    category_id=category.id,
                    content=input.content,
                    position=int(max_position if max_position is not None else -1) + 1,
                    active=True,
                )
            )
            session.flush()
            self._bump_revision(session, state, input.expected_revision)
            result = self._snapshot(session)
            self._record_request(session, input.request_id, "create_phrase", payload, result)
            session.commit()
            return result

    def update_phrase(
        self, phrase_id: str, input: PhraseUpdateInput
    ) -> PhraseLibraryView:
        if not input.content.strip():
            raise PhraseLibraryError("phrase_empty", "话术内容不能为空")
        payload = {
            "phrase_id": phrase_id,
            "expected_revision": input.expected_revision,
            "category_id": input.category_id,
            "content": input.content,
        }
        with self.database.session() as session:
            replay = self._request(session, input.request_id, "update_phrase", payload)
            if replay is not None:
                return replay
            state = self._require_revision(session, input.expected_revision)
            phrase = session.get(PhraseSnippet, phrase_id)
            if phrase is None:
                raise PhraseLibraryError("phrase_missing", "所选话术不存在", 404)
            category = session.get(PhraseCategory, input.category_id)
            if category is None or not category.active:
                raise PhraseLibraryError("category_missing", "所选话术分类不存在", 404)
            if phrase.category_id != category.id:
                max_position = session.scalar(
                    select(func.max(PhraseSnippet.position)).where(
                        PhraseSnippet.category_id == category.id,
                        PhraseSnippet.active.is_(True),
                    )
                )
                phrase.category_id = category.id
                phrase.position = int(max_position if max_position is not None else -1) + 1
            phrase.content = input.content
            phrase.updated_at = utcnow()
            session.flush()
            self._bump_revision(session, state, input.expected_revision)
            result = self._snapshot(session)
            self._record_request(session, input.request_id, "update_phrase", payload, result)
            session.commit()
            return result

    def reorder(self, input: PhraseReorderInput) -> PhraseLibraryView:
        if len(input.phrase_ids) != len(set(input.phrase_ids)):
            raise PhraseLibraryError("reorder_duplicate", "排序列表包含重复话术")
        payload = input.model_dump(exclude={"request_id"})
        with self.database.session() as session:
            replay = self._request(session, input.request_id, "reorder_phrases", payload)
            if replay is not None:
                return replay
            state = self._require_revision(session, input.expected_revision)
            category = session.get(PhraseCategory, input.category_id)
            if category is None or not category.active:
                raise PhraseLibraryError("category_missing", "所选话术分类不存在", 404)
            rows = list(
                session.scalars(
                    select(PhraseSnippet).where(
                        PhraseSnippet.category_id == category.id,
                        PhraseSnippet.active.is_(True),
                    )
                )
            )
            by_id = {row.id: row for row in rows}
            if set(input.phrase_ids) != set(by_id):
                raise PhraseLibraryError(
                    "reorder_stale",
                    "话术列表已变化，请刷新后重新排序",
                    409,
                    revision=state.revision,
                )
            for position, phrase_id in enumerate(input.phrase_ids):
                by_id[phrase_id].position = position
                by_id[phrase_id].updated_at = utcnow()
            session.flush()
            self._bump_revision(session, state, input.expected_revision)
            result = self._snapshot(session)
            self._record_request(
                session, input.request_id, "reorder_phrases", payload, result
            )
            session.commit()
            return result

    def set_activation(
        self, phrase_id: str, input: PhraseActivationInput
    ) -> PhraseLibraryView:
        payload = {
            "phrase_id": phrase_id,
            "expected_revision": input.expected_revision,
            "active": input.active,
        }
        with self.database.session() as session:
            replay = self._request(session, input.request_id, "activate_phrase", payload)
            if replay is not None:
                return replay
            state = self._require_revision(session, input.expected_revision)
            phrase = session.get(PhraseSnippet, phrase_id)
            if phrase is None:
                raise PhraseLibraryError("phrase_missing", "所选话术不存在", 404)
            phrase.active = input.active
            phrase.updated_at = utcnow()
            session.flush()
            self._bump_revision(session, state, input.expected_revision)
            result = self._snapshot(session)
            self._record_request(
                session, input.request_id, "activate_phrase", payload, result
            )
            session.commit()
            return result
