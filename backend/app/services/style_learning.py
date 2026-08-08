from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..ai import SellerStyleContext
from ..config import Settings
from ..database import Database
from ..models import (
    Message,
    OperationLog,
    SellerReplySample,
    SellerStylePreference,
    utcnow,
)


_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_CONTACT_RE = re.compile(
    r"(?:(?:微信|vx|v信|电话|手机|qq)\s*[:：]?\s*)?[A-Za-z0-9_-]{6,}",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_MONEY_RE = re.compile(r"(?:[¥￥]\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*元)")
_DATE_RE = re.compile(
    r"(?:\d{1,2}[月/-]\d{1,2}(?:日)?|\d{1,2}[:：]\d{2}|"
    r"(?:今天|明天|后天|本周|下周|周[一二三四五六日天])(?:上午|下午|晚上)?)"
)


@dataclass(frozen=True, slots=True)
class StyleProfileSnapshot:
    enabled: bool
    sample_count: int
    summary: str
    traits: tuple[str, ...]
    updated_at: datetime | None

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "sample_count": self.sample_count,
            "summary": self.summary,
            "traits": list(self.traits),
            "updated_at": self.updated_at,
        }


class StyleLearningService:
    """Builds a local writing-style profile from replies the seller actually sent.

    The service never treats generated drafts as examples. It stores only local
    outbound messages, masks volatile facts before adding examples to an AI
    request, and keeps the input bounded so the style context cannot grow forever.
    """

    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def bootstrap(self) -> StyleProfileSnapshot:
        with self.database.session() as session:
            self._preference(session)
            session.commit()
        self.capture_synced_outbound()
        return self.snapshot()

    def _preference(self, session: Session) -> SellerStylePreference:
        preference = session.get(SellerStylePreference, 1)
        if preference is None:
            preference = SellerStylePreference(
                id=1,
                enabled=self.settings.style_learning_enabled,
            )
            session.add(preference)
            session.flush()
        return preference

    @staticmethod
    def _is_eligible(message: Message) -> bool:
        content = message.content.strip()
        return (
            message.direction == "outbound"
            and message.message_type == "text"
            and 2 <= len(content) <= 1000
            and not (content.startswith("[") and content.endswith("]"))
        )

    def record_message(
        self,
        session: Session,
        message: Message,
        *,
        source: str,
        included: bool | None = None,
    ) -> SellerReplySample | None:
        if not self._is_eligible(message):
            return None
        preference = self._preference(session)
        include_sample = source != "automatic" if included is None else included
        if include_sample and not preference.enabled:
            return None
        existing = session.scalar(
            select(SellerReplySample).where(
                SellerReplySample.message_id == message.id
            )
        )
        if existing:
            return existing
        sample = SellerReplySample(
            message_id=message.id,
            conversation_id=message.conversation_id,
            content=message.content.strip(),
            source=source[:32],
            included=include_sample,
            created_at=message.received_at or utcnow(),
        )
        session.add(sample)
        session.flush()
        self._trim(session)
        return sample

    def capture_synced_outbound(self) -> int:
        """Capture new outbound history synced from Xianyu.

        Locally created messages are recorded at send time. A synced copy that
        matches any recently recorded reply remains excluded, preventing both
        automatic replies and Xianyu echoes from inflating the profile.
        """

        captured = 0
        with self.database.session() as session:
            preference = self._preference(session)
            if not preference.enabled:
                session.commit()
                return 0
            statement = (
                select(Message)
                    .outerjoin(
                        SellerReplySample,
                        SellerReplySample.message_id == Message.id,
                    )
                    .where(
                        Message.direction == "outbound",
                        Message.message_type == "text",
                        SellerReplySample.id.is_(None),
                    )
                    .order_by(Message.received_at.asc(), Message.id.asc())
            )
            if preference.collect_after:
                statement = statement.where(
                    Message.received_at >= preference.collect_after
                )
            rows = list(session.scalars(statement))
            for message in rows:
                if not self._is_eligible(message):
                    continue
                if message.external_id.startswith("local-"):
                    # New local sends are recorded synchronously by HumanActions.
                    # Old rows are recovered only when their originating action
                    # can prove they were human-confirmed.
                    origin = session.scalar(
                        select(Message).where(
                            Message.client_send_uuid
                            == message.external_id.removeprefix("local-")
                        )
                    )
                    if not origin:
                        continue
                    was_human = session.scalar(
                        select(OperationLog.id).where(
                            OperationLog.message_id == origin.id,
                            OperationLog.action == "message_sent",
                        )
                    )
                    if not was_human:
                        continue
                    source = "human_confirmed"
                    included = True
                else:
                    source = "synced_outbound"
                    included = not self._matches_recent_recorded(session, message)
                if self.record_message(
                    session,
                    message,
                    source=source,
                    included=included,
                ):
                    captured += 1
            session.commit()
        return captured

    @staticmethod
    def _matches_recent_recorded(session: Session, message: Message) -> bool:
        start = (message.received_at or utcnow()) - timedelta(minutes=10)
        end = (message.received_at or utcnow()) + timedelta(minutes=10)
        return bool(
            session.scalar(
                select(SellerReplySample.id).where(
                    SellerReplySample.conversation_id == message.conversation_id,
                    SellerReplySample.content == message.content.strip(),
                    SellerReplySample.created_at >= start,
                    SellerReplySample.created_at <= end,
                )
            )
        )

    def _trim(self, session: Session) -> None:
        stale = list(
            session.scalars(
                select(SellerReplySample)
                .where(SellerReplySample.included.is_(True))
                .order_by(SellerReplySample.created_at.desc(), SellerReplySample.id.desc())
                .offset(self.settings.style_learning_max_samples)
            )
        )
        for sample in stale:
            sample.included = False
            sample.source = "retired"

    def set_enabled(self, enabled: bool) -> StyleProfileSnapshot:
        with self.database.session() as session:
            preference = self._preference(session)
            if enabled and not preference.enabled:
                paused_at = preference.updated_at
                paused_rows = list(
                    session.scalars(
                        select(Message)
                        .outerjoin(
                            SellerReplySample,
                            SellerReplySample.message_id == Message.id,
                        )
                        .where(
                            Message.direction == "outbound",
                            Message.message_type == "text",
                            Message.received_at >= paused_at,
                            SellerReplySample.id.is_(None),
                        )
                    )
                )
                for message in paused_rows:
                    self.record_message(
                        session,
                        message,
                        source="learning_paused",
                        included=False,
                    )
            preference.enabled = enabled
            preference.updated_at = utcnow()
            session.add(
                OperationLog(
                    action="style_learning_enabled" if enabled else "style_learning_paused",
                    detail=(
                        "用户开启本地回复风格学习"
                        if enabled
                        else "用户暂停本地回复风格学习"
                    ),
                )
            )
            session.commit()
        if enabled:
            self.capture_synced_outbound()
        return self.snapshot()

    def reset(self) -> StyleProfileSnapshot:
        with self.database.session() as session:
            session.execute(delete(SellerReplySample))
            preference = self._preference(session)
            preference.collect_after = utcnow()
            preference.updated_at = utcnow()
            session.add(
                OperationLog(
                    action="style_learning_reset",
                    detail="用户清空本地回复风格样本",
                )
            )
            session.commit()
        return self.snapshot()

    def snapshot(self) -> StyleProfileSnapshot:
        with self.database.session() as session:
            preference = self._preference(session)
            rows = list(
                session.scalars(
                    select(SellerReplySample)
                    .where(SellerReplySample.included.is_(True))
                    .order_by(
                        SellerReplySample.created_at.desc(),
                        SellerReplySample.id.desc(),
                    )
                    .limit(100)
                )
            )
            count = session.scalar(
                select(func.count())
                .select_from(SellerReplySample)
                .where(SellerReplySample.included.is_(True))
            ) or 0
            latest = rows[0].created_at if rows else preference.updated_at
            enabled = preference.enabled
            session.commit()
        traits = self._traits([row.content for row in rows]) if enabled else ()
        return StyleProfileSnapshot(
            enabled=enabled,
            sample_count=count,
            summary=self._summary(traits, count, enabled),
            traits=traits,
            updated_at=latest,
        )

    def build_context(self, conversation_id: int) -> SellerStyleContext:
        self.capture_synced_outbound()
        snapshot = self.snapshot()
        if not snapshot.enabled or snapshot.sample_count == 0:
            return SellerStyleContext(
                enabled=snapshot.enabled,
                sample_count=snapshot.sample_count,
                summary=snapshot.summary,
                traits=list(snapshot.traits),
                examples=[],
            )
        with self.database.session() as session:
            same_conversation = list(
                session.scalars(
                    select(SellerReplySample)
                    .where(
                        SellerReplySample.included.is_(True),
                        SellerReplySample.conversation_id == conversation_id,
                    )
                    .order_by(
                        SellerReplySample.created_at.desc(),
                        SellerReplySample.id.desc(),
                    )
                    .limit(self.settings.style_context_examples)
                )
            )
            other_conversations = list(
                session.scalars(
                    select(SellerReplySample)
                    .where(
                        SellerReplySample.included.is_(True),
                        SellerReplySample.conversation_id != conversation_id,
                    )
                    .order_by(
                        SellerReplySample.created_at.desc(),
                        SellerReplySample.id.desc(),
                    )
                    .limit(self.settings.style_context_examples * 3)
                )
            )
        examples: list[str] = []
        seen: set[str] = set()
        remaining = self.settings.style_context_max_chars
        for sample in [*same_conversation, *other_conversations]:
            masked = self._mask_facts(sample.content)
            normalized = " ".join(masked.split())
            if not normalized or normalized in seen:
                continue
            clipped = normalized[: min(180, remaining)]
            if not clipped:
                break
            examples.append(clipped)
            seen.add(normalized)
            remaining -= len(clipped)
            if (
                len(examples) >= self.settings.style_context_examples
                or remaining <= 0
            ):
                break
        return SellerStyleContext(
            enabled=True,
            sample_count=snapshot.sample_count,
            summary=snapshot.summary,
            traits=list(snapshot.traits),
            examples=examples,
        )

    @staticmethod
    def _mask_facts(content: str) -> str:
        text = _URL_RE.sub("<链接>", content)
        text = _PHONE_RE.sub("<联系方式>", text)
        text = _MONEY_RE.sub("<金额>", text)
        text = _DATE_RE.sub("<时间>", text)
        # Contact-like identifiers are masked last so ordinary short Chinese
        # phrases and punctuation remain available as style signals.
        text = _CONTACT_RE.sub(
            lambda match: "<联系方式>"
            if any(char.isdigit() for char in match.group(0))
            else match.group(0),
            text,
        )
        return text.strip()

    @staticmethod
    def _traits(contents: list[str]) -> tuple[str, ...]:
        if not contents:
            return ()
        count = len(contents)
        average_length = sum(len(content.strip()) for content in contents) / count
        traits: list[str] = []
        if average_length <= 35:
            traits.append("简短")
        elif average_length <= 70:
            traits.append("简洁自然")
        else:
            traits.append("信息完整")

        warm = sum(
            any(token in content for token in ("呀", "呢", "哦", "哈", "～", "~"))
            for content in contents
        )
        polite = sum(
            any(token in content for token in ("您好", "你好", "请", "麻烦", "谢谢"))
            for content in contents
        )
        cautious = sum(
            any(token in content for token in ("确认", "看看", "看完", "根据", "再给", "先发"))
            for content in contents
        )
        questions = sum("？" in content or "?" in content for content in contents)
        if warm / count >= 0.18:
            traits.append("语气自然")
        elif polite / count >= 0.25:
            traits.append("礼貌")
        else:
            traits.append("少寒暄")
        if cautious / count >= 0.18:
            traits.append("少承诺")
        elif questions / count >= 0.25:
            traits.append("主动追问")
        else:
            traits.append("直接回应")
        return tuple(traits[:3])

    @staticmethod
    def _summary(traits: tuple[str, ...], count: int, enabled: bool) -> str:
        if not enabled:
            return "本地回复风格学习已暂停。"
        if count == 0:
            return "尚无已发送回复样本，将继续使用基础客服规则。"
        return f"已从 {count} 条实际发送回复中提炼风格：{'、'.join(traits)}。"
