from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import Database
from ..ledger import LedgerService, RevisionConflict, canonical_json
from ..models import (
    BusinessProject,
    Item,
    LedgerMutationRequest,
    ProductMonitor,
)


class ProjectProductAttributionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProjectProductAttributionService:
    """Revision-safe project to owned-listing attribution.

    The canonical ledger snapshot and normalized project row move together in
    one transaction. Preview tokens bind the confirmation to the exact project
    financial facts so a stale profit move cannot be applied silently.
    """

    OPERATION = "project_product_attribution"

    def __init__(self, database: Database, ledger: LedgerService) -> None:
        self.database = database
        self.ledger = ledger

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _project(snapshot: dict[str, Any], project_id: str) -> dict[str, Any] | None:
        return next(
            (row for row in snapshot["projects"] if str(row.get("id") or "") == project_id),
            None,
        )

    @staticmethod
    def _item(session: Session, external_id: str | None) -> Item | None:
        if not external_id:
            return None
        return session.scalar(
            select(Item)
            .join(ProductMonitor, ProductMonitor.item_id == Item.id)
            .where(
                Item.external_id == external_id,
                ProductMonitor.ownership_status == "owned",
            )
            .limit(1)
        )

    @staticmethod
    def _project_financials(snapshot: dict[str, Any], project_id: str) -> dict[str, float]:
        payments = [row for row in snapshot["payments"] if row.get("projectId") == project_id]
        gross = round(
            sum(
                float(row.get("amount") or 0)
                for row in payments
                if row.get("status") in {"confirmed", "refunded"}
            ),
            2,
        )
        legacy_refunds = round(
            sum(
                float(row.get("amount") or 0)
                for row in payments
                if row.get("status") == "refunded"
            ),
            2,
        )
        issue_refunds = round(
            sum(
                float(row.get("refundAmount") or 0)
                for row in snapshot["settlementIssues"]
                if row.get("projectId") == project_id
            ),
            2,
        )
        refunds = round(legacy_refunds + issue_refunds, 2)
        net = round(gross - refunds, 2)
        expenses = round(
            sum(
                float(row.get("amount") or 0)
                for row in snapshot["expenses"]
                if row.get("projectId") == project_id
            ),
            2,
        )
        return {
            "net": net,
            "expenses": expenses,
            "refunds": refunds,
            "profit": round(net - expenses, 2),
        }

    def _product_totals(
        self,
        snapshot: dict[str, Any],
        external_id: str | None,
    ) -> tuple[int, float]:
        if not external_id:
            return 0, 0.0
        projects = [
            row
            for row in snapshot["projects"]
            if str(row.get("itemExternalId") or "") == external_id
        ]
        return (
            len(projects),
            round(
                sum(
                    self._project_financials(snapshot, str(row.get("id") or ""))["profit"]
                    for row in projects
                ),
                2,
            ),
        )

    def _build_preview(
        self,
        session: Session,
        snapshot: dict[str, Any],
        *,
        revision: int,
        project_id: str,
        target_item_external_id: str | None,
    ) -> dict[str, Any]:
        project = self._project(snapshot, project_id)
        normalized_project = session.get(BusinessProject, project_id)
        if project is None or normalized_project is None:
            raise ProjectProductAttributionError("project_not_found", "项目不存在或已被删除")
        if project.get("projectKind") == "personal":
            raise ProjectProductAttributionError(
                "client_project_required",
                "只有接单项目可以关联来源商品",
            )

        current_external_id = str(project.get("itemExternalId") or "").strip() or None
        target_external_id = str(target_item_external_id or "").strip() or None
        if current_external_id == target_external_id:
            raise ProjectProductAttributionError(
                "product_unchanged",
                "目标商品与当前来源商品相同，无需修改",
            )
        current_item = self._item(session, current_external_id)
        target_item = self._item(session, target_external_id)
        if target_external_id and target_item is None:
            raise ProjectProductAttributionError(
                "owned_product_required",
                "只能关联当前账号已确认的本人商品",
            )

        financials = self._project_financials(snapshot, project_id)
        current_count, current_profit = self._product_totals(snapshot, current_external_id)
        target_count, target_profit = self._product_totals(snapshot, target_external_id)
        action = "unbind" if target_external_id is None else "rebind" if current_external_id else "bind"
        impact = {
            "project_net_confirmed": financials["net"],
            "project_expenses": financials["expenses"],
            "project_refunds": financials["refunds"],
            "project_profit": financials["profit"],
            "current_product_project_count": current_count,
            "current_product_profit_before": current_profit,
            "current_product_profit_after": round(
                current_profit - financials["profit"] if current_external_id else current_profit,
                2,
            ),
            "target_product_project_count": target_count,
            "target_product_profit_before": target_profit,
            "target_product_profit_after": round(
                target_profit + financials["profit"] if target_external_id else target_profit,
                2,
            ),
        }
        fingerprint = {
            "revision": revision,
            "project_id": project_id,
            "project_kind": project.get("projectKind"),
            "current_item_external_id": current_external_id,
            "target_item_external_id": target_external_id,
            "financials": financials,
        }
        preview_token = hashlib.sha256(
            canonical_json(fingerprint).encode("utf-8")
        ).hexdigest()
        warnings = []
        if financials["profit"] < 0:
            warnings.append("该项目当前为负利润，关联后会降低目标商品的实际利润")
        if current_external_id:
            warnings.append("改绑只移动利润归属，不会修改项目或商品的历史快照")
        return {
            "preview_token": preview_token,
            "revision": revision,
            "project_id": project_id,
            "project_name": str(project.get("name") or "未命名项目"),
            "current_item_external_id": current_external_id,
            "current_item_title": current_item.title if current_item else None,
            "target_item_external_id": target_external_id,
            "target_item_title": target_item.title if target_item else None,
            "action": action,
            "impact": impact,
            "preserves": ["合同金额", "到账与待收状态", "项目交付状态", "历史商品快照"],
            "warnings": warnings,
        }

    def preview(
        self,
        *,
        expected_revision: int,
        project_id: str,
        target_item_external_id: str | None,
    ) -> dict[str, Any]:
        with self.database.session() as session:
            revision, snapshot = self.ledger.get_in_session(session)
            if revision != expected_revision:
                raise RevisionConflict(revision)
            return self._build_preview(
                session,
                snapshot,
                revision=revision,
                project_id=project_id,
                target_item_external_id=target_item_external_id,
            )

    def commit(
        self,
        *,
        request_id: str,
        expected_revision: int,
        preview_token: str,
        project_id: str,
        target_item_external_id: str | None,
    ) -> dict[str, Any]:
        target_external_id = str(target_item_external_id or "").strip() or None
        request_payload = {
            "project_id": project_id,
            "target_item_external_id": target_external_id,
        }
        payload_hash = self._payload_hash(request_payload)
        with self.database.session() as session:
            previous = session.get(LedgerMutationRequest, request_id)
            if previous is not None:
                if previous.operation != self.OPERATION or previous.payload_hash != payload_hash:
                    raise ProjectProductAttributionError(
                        "request_id_reused",
                        "该请求编号已用于不同操作，请刷新后重新提交",
                    )
                try:
                    stored = json.loads(previous.result_json)
                except json.JSONDecodeError:
                    raise ProjectProductAttributionError(
                        "request_record_invalid",
                        "历史请求记录无法校验，请刷新后重试",
                    ) from None
                revision, snapshot = self.ledger.get_in_session(session)
                return {**stored, "revision": revision, "snapshot": snapshot, "idempotent": True}

            revision, snapshot = self.ledger.get_in_session(session)
            if revision != expected_revision:
                raise RevisionConflict(revision)
            preview = self._build_preview(
                session,
                snapshot,
                revision=revision,
                project_id=project_id,
                target_item_external_id=target_external_id,
            )
            if preview["preview_token"] != preview_token:
                raise ProjectProductAttributionError(
                    "preview_expired",
                    "利润归属预览已经失效，请刷新后重新预览",
                )

            project = self._project(snapshot, project_id)
            assert project is not None
            current_external_id = str(project.get("itemExternalId") or "").strip() or None
            project["itemExternalId"] = target_external_id
            new_revision, normalized = self.ledger.save_in_session(
                session,
                snapshot,
                expected_revision,
            )
            stored = {
                "project_id": project_id,
                "current_item_external_id": current_external_id,
                "target_item_external_id": target_external_id,
                "impact": preview["impact"],
            }
            session.add(
                LedgerMutationRequest(
                    request_id=request_id,
                    operation=self.OPERATION,
                    payload_hash=payload_hash,
                    result_json=canonical_json(stored),
                )
            )
            session.commit()
            return {
                **stored,
                "revision": new_revision,
                "snapshot": normalized,
                "idempotent": False,
            }
