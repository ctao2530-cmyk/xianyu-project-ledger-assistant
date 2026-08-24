from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from ..customer_relationship_schemas import CustomerRelationImpact
from ..database import Database
from ..ledger import LedgerService, RevisionConflict, canonical_json
from ..models import BusinessCustomer, LedgerMutationRequest


class CustomerRelationshipError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CustomerRelationshipService:
    """Fail-closed customer edits and project ownership corrections.

    The canonical snapshot and normalized tables are changed in the same SQLite
    transaction. Relationship previews are tied to the exact ledger revision
    and relationship fingerprint so a stale confirmation cannot be applied.
    """

    CUSTOMER_UPDATE = "customer_update"
    PROJECT_REBIND = "customer_project_rebind"

    def __init__(self, database: Database, ledger: LedgerService) -> None:
        self.database = database
        self.ledger = ledger

    @staticmethod
    def _payload_hash(operation: str, payload: dict[str, Any]) -> str:
        value = {"operation": operation, "payload": payload}
        return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _request_result(
        session: Session,
        *,
        request_id: str,
        operation: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        row = session.get(LedgerMutationRequest, request_id)
        if row is None:
            return None
        if row.operation != operation or row.payload_hash != payload_hash:
            raise CustomerRelationshipError(
                "request_id_reused",
                "该请求编号已用于不同操作，请刷新后重新提交",
            )
        try:
            result = json.loads(row.result_json)
        except json.JSONDecodeError:
            raise CustomerRelationshipError(
                "request_record_invalid",
                "历史请求记录无法校验，请刷新后重试",
            ) from None
        if not isinstance(result, dict):
            raise CustomerRelationshipError(
                "request_record_invalid",
                "历史请求记录无法校验，请刷新后重试",
            )
        return result

    @staticmethod
    def _save_request(
        session: Session,
        *,
        request_id: str,
        operation: str,
        payload_hash: str,
        result: dict[str, Any],
    ) -> None:
        session.add(
            LedgerMutationRequest(
                request_id=request_id,
                operation=operation,
                payload_hash=payload_hash,
                result_json=canonical_json(result),
            )
        )

    @staticmethod
    def _customer(snapshot: dict[str, Any], customer_id: str) -> dict[str, Any] | None:
        return next(
            (row for row in snapshot["customers"] if str(row.get("id") or "") == customer_id),
            None,
        )

    def update_customer(
        self,
        customer_id: str,
        *,
        request_id: str,
        expected_revision: int,
        name: str,
        source: str,
        phone: str,
        follow_up_status: str,
        last_contact_at: str,
        level: str,
        tags: list[str],
        current_need: str | None = None,
        price_type: str | None = None,
        price_amount: float | None = None,
        next_action: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        values = {
            "customer_id": customer_id,
            "name": name.strip(),
            "source": source,
            "phone": phone.strip(),
            "follow_up_status": follow_up_status,
            "last_contact_at": last_contact_at.strip(),
            "level": level,
            "tags": tags,
            "current_need": current_need.strip() if current_need is not None else None,
            "price_type": price_type,
            "price_amount": price_amount,
            "next_action": next_action.strip() if next_action is not None else None,
            "notes": notes.strip() if notes is not None else None,
        }
        payload_hash = self._payload_hash(self.CUSTOMER_UPDATE, values)
        with self.database.session() as session:
            repeated = self._request_result(
                session,
                request_id=request_id,
                operation=self.CUSTOMER_UPDATE,
                payload_hash=payload_hash,
            )
            if repeated is not None:
                revision, snapshot = self.ledger.get_in_session(session)
                if self._customer(snapshot, customer_id) is None:
                    raise CustomerRelationshipError("customer_not_found", "客户记录不存在")
                return {
                    "revision": revision,
                    "snapshot": snapshot,
                    "customer_id": customer_id,
                    "idempotent": True,
                }

            revision, snapshot = self.ledger.get_in_session(session)
            if revision != expected_revision:
                raise RevisionConflict(revision)
            customer = self._customer(snapshot, customer_id)
            normalized_customer = session.get(BusinessCustomer, customer_id)
            if customer is None or normalized_customer is None:
                raise CustomerRelationshipError("customer_not_found", "客户记录不存在")

            customer.update(
                {
                    "name": values["name"],
                    "source": values["source"],
                    "phone": values["phone"],
                    "followUpStatus": values["follow_up_status"],
                    "lastContactAt": values["last_contact_at"],
                    "level": values["level"],
                    "tags": list(values["tags"]),
                    "currentNeed": customer.get("currentNeed", "") if values["current_need"] is None else values["current_need"],
                    "priceType": customer.get("priceType", "") if values["price_type"] is None else values["price_type"],
                    "priceAmount": customer.get("priceAmount") if price_type is None and price_amount is None else values["price_amount"],
                    "nextAction": customer.get("nextAction", "") if values["next_action"] is None else values["next_action"],
                    "notes": customer.get("notes", "") if values["notes"] is None else values["notes"],
                }
            )
            new_revision, normalized = self.ledger.save_in_session(
                session,
                snapshot,
                expected_revision,
            )
            result = {"customer_id": customer_id, "revision": new_revision}
            self._save_request(
                session,
                request_id=request_id,
                operation=self.CUSTOMER_UPDATE,
                payload_hash=payload_hash,
                result=result,
            )
            session.commit()
            return {
                "revision": new_revision,
                "snapshot": normalized,
                "customer_id": customer_id,
                "idempotent": False,
            }

    def _build_preview(
        self,
        session: Session,
        snapshot: dict[str, Any],
        *,
        revision: int,
        project_id: str,
        current_customer_id: str,
        target_customer_id: str,
    ) -> dict[str, Any]:
        current_customer = self._customer(snapshot, current_customer_id)
        target_customer = self._customer(snapshot, target_customer_id)
        if (
            current_customer is None
            or session.get(BusinessCustomer, current_customer_id) is None
        ):
            raise CustomerRelationshipError("customer_not_found", "当前客户记录不存在")
        if target_customer is None or session.get(BusinessCustomer, target_customer_id) is None:
            raise CustomerRelationshipError("customer_not_found", "目标客户记录不存在")
        if current_customer_id == target_customer_id:
            raise CustomerRelationshipError(
                "customer_unchanged",
                "目标客户与当前客户相同，无需修正",
            )

        project = next(
            (row for row in snapshot["projects"] if str(row.get("id") or "") == project_id),
            None,
        )
        if project is None:
            raise CustomerRelationshipError("project_not_found", "项目记录不存在")
        if project.get("projectKind") == "personal":
            raise CustomerRelationshipError(
                "personal_project_forbidden",
                "个人项目不能绑定客户",
            )
        if str(project.get("customerId") or "") != current_customer_id:
            raise CustomerRelationshipError(
                "project_customer_changed",
                "项目所属客户已经变化，请刷新后重新预览",
            )

        related = {
            "payments": [row for row in snapshot["payments"] if row.get("projectId") == project_id],
            "changeOrders": [row for row in snapshot["changeOrders"] if row.get("projectId") == project_id],
            "settlementIssues": [row for row in snapshot["settlementIssues"] if row.get("projectId") == project_id],
        }
        inconsistent = [
            row
            for rows in related.values()
            for row in rows
            if str(row.get("customerId") or "") != current_customer_id
        ]
        if inconsistent:
            raise CustomerRelationshipError(
                "relationship_inconsistent",
                "项目关联记录的客户归属不一致，请先核对数据",
            )

        payments = related["payments"]
        impact = CustomerRelationImpact(
            project_count=1,
            payment_count=len(payments),
            change_order_count=len(related["changeOrders"]),
            settlement_issue_count=len(related["settlementIssues"]),
            confirmed_amount=round(
                sum(float(row.get("amount") or 0) for row in payments if row.get("status") == "confirmed"),
                2,
            ),
            pending_amount=round(
                sum(float(row.get("amount") or 0) for row in payments if row.get("status") == "pending"),
                2,
            ),
        )
        fingerprint = {
            "revision": revision,
            "project": {
                "id": project_id,
                "customer_id": current_customer_id,
                "status": str(project.get("status") or ""),
                "total_amount": float(project.get("totalAmount") or 0),
            },
            "target_customer_id": target_customer_id,
            "payments": [
                [row.get("id"), row.get("customerId"), row.get("status"), row.get("amount")]
                for row in sorted(payments, key=lambda item: str(item.get("id") or ""))
            ],
            "change_orders": [
                [row.get("id"), row.get("customerId"), row.get("status"), row.get("amount")]
                for row in sorted(related["changeOrders"], key=lambda item: str(item.get("id") or ""))
            ],
            "settlement_issues": [
                [row.get("id"), row.get("customerId"), row.get("type")]
                for row in sorted(related["settlementIssues"], key=lambda item: str(item.get("id") or ""))
            ],
        }
        preview_token = hashlib.sha256(
            canonical_json(fingerprint).encode("utf-8")
        ).hexdigest()
        warnings = []
        if impact.settlement_issue_count:
            warnings.append("项目结算异常会随项目归属同步，异常内容与金额保持不变")
        return {
            "preview_token": preview_token,
            "revision": revision,
            "project_id": project_id,
            "project_name": str(project.get("name") or "未命名项目"),
            "project_status": str(project.get("status") or "pending"),
            "contract_total": round(float(project.get("totalAmount") or 0), 2),
            "current_customer_id": current_customer_id,
            "current_customer_name": str(current_customer.get("name") or "未命名客户"),
            "target_customer_id": target_customer_id,
            "target_customer_name": str(target_customer.get("name") or "未命名客户"),
            "impact": impact.model_dump(),
            "preserves": [
                "合同金额",
                "到账与待收状态",
                "项目交付状态",
                "需求案例与渠道身份",
            ],
            "warnings": warnings,
        }

    def preview_rebind(
        self,
        *,
        expected_revision: int,
        project_id: str,
        current_customer_id: str,
        target_customer_id: str,
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
                current_customer_id=current_customer_id,
                target_customer_id=target_customer_id,
            )

    def rebind_project(
        self,
        *,
        request_id: str,
        expected_revision: int,
        preview_token: str,
        project_id: str,
        current_customer_id: str,
        target_customer_id: str,
    ) -> dict[str, Any]:
        request_payload = {
            "project_id": project_id,
            "current_customer_id": current_customer_id,
            "target_customer_id": target_customer_id,
        }
        payload_hash = self._payload_hash(self.PROJECT_REBIND, request_payload)
        with self.database.session() as session:
            repeated = self._request_result(
                session,
                request_id=request_id,
                operation=self.PROJECT_REBIND,
                payload_hash=payload_hash,
            )
            if repeated is not None:
                revision, snapshot = self.ledger.get_in_session(session)
                return {
                    "revision": revision,
                    "snapshot": snapshot,
                    "project_id": project_id,
                    "current_customer_id": current_customer_id,
                    "target_customer_id": target_customer_id,
                    "impact": repeated["impact"],
                    "idempotent": True,
                }

            revision, snapshot = self.ledger.get_in_session(session)
            if revision != expected_revision:
                raise RevisionConflict(revision)
            preview = self._build_preview(
                session,
                snapshot,
                revision=revision,
                project_id=project_id,
                current_customer_id=current_customer_id,
                target_customer_id=target_customer_id,
            )
            if preview["preview_token"] != preview_token:
                raise CustomerRelationshipError(
                    "preview_expired",
                    "关系预览已经失效，请刷新后重新预览",
                )

            project = next(row for row in snapshot["projects"] if row.get("id") == project_id)
            project["customerId"] = target_customer_id
            for collection in ("payments", "changeOrders", "settlementIssues"):
                for row in snapshot[collection]:
                    if row.get("projectId") == project_id:
                        row["customerId"] = target_customer_id

            new_revision, normalized = self.ledger.save_in_session(
                session,
                snapshot,
                expected_revision,
            )
            stored_result = {
                "revision": new_revision,
                "project_id": project_id,
                "current_customer_id": current_customer_id,
                "target_customer_id": target_customer_id,
                "impact": preview["impact"],
            }
            self._save_request(
                session,
                request_id=request_id,
                operation=self.PROJECT_REBIND,
                payload_hash=payload_hash,
                result=stored_result,
            )
            session.commit()
            return {
                **stored_result,
                "snapshot": normalized,
                "idempotent": False,
            }
