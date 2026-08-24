from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Database
from .models import (
    AttachmentMetadata,
    BusinessCustomer,
    BusinessExpense,
    BusinessProject,
    BusinessSetting,
    BusinessTask,
    Item,
    LedgerState,
    PaymentNode,
    ProjectChangeOrderRecord,
    ProjectSettlementIssueRecord,
    ProductMonitor,
    ProjectDevelopmentLog,
    utcnow,
)


COLLECTIONS = (
    "projects",
    "changeOrders",
    "payments",
    "settlementIssues",
    "expenses",
    "customers",
    "tasks",
    "logs",
    "attachments",
)


def default_snapshot() -> dict[str, Any]:
    return {
        "projects": [],
        "changeOrders": [],
        "payments": [],
        "settlementIssues": [],
        "expenses": [],
        "customers": [],
        "tasks": [],
        "logs": [],
        "attachments": [],
        "settings": {
            "xianyuStartedAt": "2026-05-28",
            "monthlyIncomeGoal": 0,
            "profileName": "张同学",
            "profileRole": "个人开发者",
            "profilePhone": "",
            "profileBio": "专注把每个接单项目做成可复用的长期能力。",
            "accountEmail": "",
            "accountPlan": "高级版",
            "defaultDurationDays": 30,
            "defaultPaymentType": "full",
            "reminderDays": 3,
            "decimalPlaces": 2,
            "notificationsEnabled": True,
            "paymentRemindersEnabled": True,
            "goalRemindersEnabled": True,
            "autoBackupEnabled": True,
            "backupTime": "23:30",
            "themeColor": "#6544f4",
            "colorMode": "light",
            "targetHourlyRate": None,
            "quoteRiskBuffer": 0.15,
            "defaultDailyAvailableHours": 8,
        },
        "completedOrderCount": 0,
    }


def normalize_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(default_snapshot())
    if not isinstance(value, dict):
        return normalized
    for collection in COLLECTIONS:
        rows = value.get(collection)
        if isinstance(rows, list):
            normalized[collection] = [row for row in rows if isinstance(row, dict)]
    settings = value.get("settings")
    if isinstance(settings, dict):
        normalized["settings"].update(settings)
    completed = value.get("completedOrderCount")
    if isinstance(completed, (int, float)):
        normalized["completedOrderCount"] = max(0, int(completed))
    return normalized


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _same(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return canonical_json(left) == canonical_json(right)


def _identity_key(collection: str, row: dict[str, Any]) -> tuple[Any, ...] | None:
    if collection == "customers":
        return (str(row.get("name", "")).strip().casefold(),)
    if collection == "projects":
        return (str(row.get("name", "")).strip().casefold(), row.get("startDate", ""))
    if collection == "changeOrders":
        return (
            row.get("projectId", ""),
            str(row.get("title", "")).strip().casefold(),
            float(row.get("amount", 0) or 0),
            row.get("confirmedAt", ""),
        )
    if collection == "payments":
        return (row.get("projectId", ""), float(row.get("amount", 0) or 0), row.get("dueAt", ""))
    if collection == "settlementIssues":
        return (
            row.get("projectId", ""),
            row.get("type", ""),
            row.get("occurredAt", ""),
            str(row.get("reason", "")).strip().casefold(),
        )
    if collection == "expenses":
        return (str(row.get("name", "")).strip().casefold(), row.get("paidAt", ""))
    if collection == "tasks":
        return (row.get("projectId", ""), str(row.get("title", "")).strip().casefold())
    if collection == "logs":
        return (row.get("projectId", ""), row.get("createdAt", ""), str(row.get("content", ""))[:80])
    if collection == "attachments":
        return (row.get("projectId", ""), str(row.get("name", "")).strip().casefold())
    return None


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or "")


class RevisionConflict(RuntimeError):
    def __init__(self, revision: int) -> None:
        super().__init__(f"ledger revision conflict: {revision}")
        self.revision = revision


class MigrationTokenMismatch(RuntimeError):
    pass


class PaymentConfirmationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "invalid_payment") -> None:
        super().__init__(message)
        self.code = code


class ProjectChangeOrderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "invalid_change_order") -> None:
        super().__init__(message)
        self.code = code


class SettlementIssueError(RuntimeError):
    def __init__(self, message: str, *, code: str = "invalid_settlement_issue") -> None:
        super().__init__(message)
        self.code = code


class LedgerValidationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "invalid_ledger_data") -> None:
        super().__init__(message)
        self.code = code


TERMINAL_SETTLEMENT_ISSUE_TYPES = {
    "project_cancelled",
    "cooperation_terminated",
}


class LedgerService:
    def __init__(self, database: Database, project_root: Path) -> None:
        self.database = database
        self.project_root = project_root
        self.data_dir = project_root / "data"
        self.attachments_dir = self.data_dir / "attachments"
        self.backups_dir = self.data_dir / "backups"

    def _state(self, session: Session) -> LedgerState:
        state = session.get(LedgerState, 1)
        if state is None:
            state = LedgerState(id=1, revision=0, snapshot_json=canonical_json(default_snapshot()))
            session.add(state)
            session.flush()
        return state

    def get(self) -> tuple[int, dict[str, Any]]:
        with self.database.session() as session:
            state = self._state(session)
            session.commit()
            return state.revision, normalize_snapshot(json.loads(state.snapshot_json))

    def get_in_session(self, session: Session) -> tuple[int, dict[str, Any]]:
        """Read the canonical snapshot inside a caller-owned transaction."""

        state = self._state(session)
        return state.revision, normalize_snapshot(json.loads(state.snapshot_json))

    def save(self, snapshot: dict[str, Any], expected_revision: int) -> tuple[int, dict[str, Any]]:
        with self.database.session() as session:
            revision, normalized = self.save_in_session(session, snapshot, expected_revision)
            session.commit()
            return revision, normalized

    def upsert_system_expense_in_session(
        self,
        session: Session,
        *,
        expense_id: str,
        name: str,
        category: str,
        amount: float,
        paid_at: str,
        notes: str = "",
    ) -> tuple[int, bool]:
        """Write an idempotent system expense inside the caller's transaction.

        Product-intelligence actions and the canonical ledger must commit as one
        SQLite transaction.  The stable expense id prevents request retries from
        creating duplicate costs, while advancing the ledger revision ensures a
        browser holding an older snapshot receives the normal 409 on its next
        write instead of silently overwriting this expense.
        """

        state = self._state(session)
        snapshot = normalize_snapshot(json.loads(state.snapshot_json))
        normalized_amount = round(max(0, float(amount)), 2)
        expense = {
            "id": expense_id,
            "name": name.strip() or "系统经营支出",
            "category": category.strip() or "other",
            "amount": normalized_amount,
            "paidAt": paid_at,
            "notes": notes.strip(),
        }
        existing_index = next(
            (
                index
                for index, row in enumerate(snapshot["expenses"])
                if str(row.get("id") or "") == expense_id
            ),
            None,
        )
        if existing_index is not None:
            current = snapshot["expenses"][existing_index]
            comparable = {
                "id": str(current.get("id") or ""),
                "name": str(current.get("name") or ""),
                "category": str(current.get("category") or "other"),
                "amount": round(float(current.get("amount") or 0), 2),
                "paidAt": str(current.get("paidAt") or ""),
                "notes": str(current.get("notes") or ""),
            }
            if comparable == expense:
                return state.revision, False
            snapshot["expenses"][existing_index] = expense
        else:
            snapshot["expenses"].insert(0, expense)

        revision, _normalized = self.save_in_session(
            session,
            snapshot,
            state.revision,
        )
        return revision, True

    def create_project_change_order(
        self,
        *,
        request_id: str,
        expected_revision: int,
        project_id: str,
        title: str,
        amount: float,
        confirmed_at: str,
        notes: str,
        payment_plan: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Add paid scope to an existing project and create its receipts atomically."""

        title = title.strip()
        amount = round(float(amount), 2)
        if len(title) < 2:
            raise ProjectChangeOrderError(
                "请填写至少 2 个字的追加修改内容",
                code="title_invalid",
            )
        if amount <= 0:
            raise ProjectChangeOrderError(
                "追加金额必须大于 0",
                code="amount_invalid",
            )
        if not payment_plan:
            raise ProjectChangeOrderError(
                "请至少设置一笔到账或待收安排",
                code="payment_plan_required",
            )

        normalized_plan: list[dict[str, Any]] = []
        for index, row in enumerate(payment_plan):
            planned_amount = round(float(row.get("amount") or 0), 2)
            payment_status = str(row.get("status") or "")
            payment_type = str(row.get("type") or "")
            paid_at = str(row.get("paidAt") or "")
            due_at = str(row.get("dueAt") or "")
            if planned_amount <= 0:
                raise ProjectChangeOrderError(
                    f"第 {index + 1} 笔金额必须大于 0",
                    code="payment_amount_invalid",
                )
            if payment_status not in {"confirmed", "pending"}:
                raise ProjectChangeOrderError(
                    "追加订单只支持已到账或待收节点",
                    code="payment_status_invalid",
                )
            if payment_type not in {"deposit", "milestone", "final", "full"}:
                raise ProjectChangeOrderError(
                    "收款类型无效",
                    code="payment_type_invalid",
                )
            if payment_status == "confirmed" and not paid_at:
                raise ProjectChangeOrderError(
                    f"第 {index + 1} 笔已到账记录缺少到账时间",
                    code="paid_at_required",
                )
            if payment_status == "pending" and not due_at:
                raise ProjectChangeOrderError(
                    f"第 {index + 1} 笔待收记录缺少应收日期",
                    code="due_at_required",
                )
            normalized_plan.append(
                {
                    "amount": planned_amount,
                    "status": payment_status,
                    "type": payment_type,
                    "paidAt": paid_at,
                    "dueAt": due_at,
                    "notes": str(row.get("notes") or "").strip(),
                }
            )

        plan_total = round(sum(row["amount"] for row in normalized_plan), 2)
        if abs(plan_total - amount) > 0.005:
            raise ProjectChangeOrderError(
                f"收款安排合计 ¥{plan_total:,.2f}，必须等于追加金额 ¥{amount:,.2f}",
                code="payment_plan_total_mismatch",
            )

        with self.database.session() as session:
            state = self._state(session)
            snapshot = normalize_snapshot(json.loads(state.snapshot_json))
            previous = next(
                (
                    row
                    for row in snapshot["changeOrders"]
                    if row.get("requestId") == request_id
                ),
                None,
            )
            if previous is not None:
                if (
                    str(previous.get("projectId") or "") != project_id
                    or str(previous.get("title") or "").strip() != title
                    or abs(float(previous.get("amount") or 0) - amount) > 0.005
                ):
                    raise ProjectChangeOrderError(
                        "该追加订单请求编号已经用于另一笔记录，请重新打开窗口",
                        code="request_reused",
                    )
                change_order_id = str(previous.get("id") or "")
                return {
                    "revision": state.revision,
                    "snapshot": snapshot,
                    "change_order_id": change_order_id,
                    "payment_ids": [
                        str(row.get("id") or "")
                        for row in snapshot["payments"]
                        if row.get("changeOrderId") == change_order_id
                    ],
                    "idempotent": True,
                }
            if state.revision != expected_revision:
                raise RevisionConflict(state.revision)

            project = next(
                (row for row in snapshot["projects"] if row.get("id") == project_id),
                None,
            )
            if project is None:
                raise ProjectChangeOrderError(
                    "项目不存在或已被删除",
                    code="project_missing",
                )
            customer_id = str(project.get("customerId") or "")
            if not customer_id or project.get("projectKind") == "personal":
                raise ProjectChangeOrderError(
                    "个人项目不支持记录客户追加订单",
                    code="customer_missing",
                )
            if not any(row.get("id") == customer_id for row in snapshot["customers"]):
                raise ProjectChangeOrderError(
                    "项目关联客户不存在，请先修复客户关系",
                    code="customer_missing",
                )
            if any(
                row.get("projectId") == project_id
                and row.get("type") in TERMINAL_SETTLEMENT_ISSUE_TYPES
                for row in snapshot["settlementIssues"]
            ):
                raise ProjectChangeOrderError(
                    "该项目已经取消或终止合作，请为新的付费需求创建新项目",
                    code="project_terminated",
                )

            digest = hashlib.sha1(request_id.encode("utf-8")).hexdigest()[:24]
            change_order_id = f"change-{digest}"
            created_at = utcnow().isoformat()
            snapshot["changeOrders"].insert(
                0,
                {
                    "id": change_order_id,
                    "projectId": project_id,
                    "customerId": customer_id,
                    "title": title,
                    "amount": amount,
                    "confirmedAt": confirmed_at,
                    "status": "confirmed",
                    "notes": notes,
                    "requestId": request_id,
                    "createdAt": created_at,
                },
            )
            project["totalAmount"] = round(
                float(project.get("totalAmount") or 0) + amount,
                2,
            )

            payment_ids: list[str] = []
            for index, row in enumerate(normalized_plan):
                payment_id = f"pay-change-{digest}-{index + 1}"
                payment_ids.append(payment_id)
                payment_notes = row["notes"] or (
                    f"{title} · 已确认到账"
                    if row["status"] == "confirmed"
                    else f"{title} · 等待收款"
                )
                payment: dict[str, Any] = {
                    "id": payment_id,
                    "projectId": project_id,
                    "customerId": customer_id,
                    "changeOrderId": change_order_id,
                    "amount": row["amount"],
                    "type": row["type"],
                    "status": row["status"],
                    "paidAt": row["paidAt"],
                    "dueAt": row["dueAt"] or row["paidAt"][:10],
                    "notes": payment_notes,
                }
                if row["status"] == "confirmed":
                    payment["confirmationRequestId"] = f"{request_id}-change-{index + 1}"
                snapshot["payments"].append(payment)

            revision, normalized = self.save_in_session(
                session, snapshot, expected_revision
            )
            session.commit()
            return {
                "revision": revision,
                "snapshot": normalized,
                "change_order_id": change_order_id,
                "payment_ids": payment_ids,
                "idempotent": False,
            }

    def confirm_payment(
        self,
        *,
        request_id: str,
        expected_revision: int,
        project_id: str,
        payment_id: str | None,
        amount: float,
        paid_at: str,
        payment_type: str,
        notes: str,
    ) -> dict[str, Any]:
        """Confirm a receipt atomically without silently overwriting another browser."""

        amount = round(float(amount), 2)
        if amount <= 0:
            raise PaymentConfirmationError(
                "到账金额必须大于 0",
                code="amount_invalid",
            )
        with self.database.session() as session:
            state = self._state(session)
            snapshot = normalize_snapshot(json.loads(state.snapshot_json))
            previous = next(
                (
                    row
                    for row in snapshot["payments"]
                    if row.get("confirmationRequestId") == request_id
                ),
                None,
            )
            if previous is not None:
                if (
                    str(previous.get("projectId") or "") != project_id
                    or abs(float(previous.get("amount") or 0) - amount) > 0.005
                ):
                    raise PaymentConfirmationError(
                        "该到账请求编号已经用于另一笔收款，请重新打开确认窗口",
                        code="request_reused",
                    )
                return {
                    "revision": state.revision,
                    "snapshot": snapshot,
                    "payment_id": str(previous.get("id") or ""),
                    "remainder_payment_id": next(
                        (
                            str(row.get("id"))
                            for row in snapshot["payments"]
                            if row.get("remainderOfRequestId") == request_id
                        ),
                        None,
                    ),
                    "idempotent": True,
                }
            if state.revision != expected_revision:
                raise RevisionConflict(state.revision)

            project = next(
                (row for row in snapshot["projects"] if row.get("id") == project_id),
                None,
            )
            if project is None:
                raise PaymentConfirmationError("项目不存在或已被删除", code="project_missing")
            customer_id = str(project.get("customerId") or "")
            if not customer_id:
                raise PaymentConfirmationError(
                    "个人项目不支持记录客户回款",
                    code="customer_missing",
                )
            gross_receipts = round(
                sum(
                    float(row.get("amount") or 0)
                    for row in snapshot["payments"]
                    if row.get("projectId") == project_id
                    and row.get("status") in {"confirmed", "refunded"}
                ),
                2,
            )
            uncollectible = round(
                sum(
                    float(row.get("receivableImpact") or 0)
                    for row in snapshot["settlementIssues"]
                    if row.get("projectId") == project_id
                ),
                2,
            )
            outstanding = round(
                max(
                    0.0,
                    float(project.get("totalAmount") or 0)
                    - gross_receipts
                    - uncollectible,
                ),
                2,
            )
            if outstanding <= 0:
                raise PaymentConfirmationError(
                    "该项目已经没有未收金额",
                    code="already_settled",
                )
            if amount > outstanding + 0.005:
                raise PaymentConfirmationError(
                    f"到账金额不能超过当前未收金额 ¥{outstanding:,.2f}",
                    code="amount_exceeds_outstanding",
                )

            project_pending = [
                row
                for row in snapshot["payments"]
                if row.get("projectId") == project_id and row.get("status") == "pending"
            ]
            selected = None
            if payment_id:
                selected = next(
                    (row for row in project_pending if row.get("id") == payment_id),
                    None,
                )
                if selected is None:
                    raise PaymentConfirmationError(
                        "待收节点不存在或已经处理，请刷新后重试",
                        code="payment_node_stale",
                    )
            elif len(project_pending) == 1:
                selected = project_pending[0]
            elif len(project_pending) > 1:
                raise PaymentConfirmationError(
                    "该项目有多个待收节点，请先选择本次到账对应的节点",
                    code="payment_node_required",
                )

            paid_at_value = str(paid_at)
            confirmed_id: str
            remainder_id: str | None = None
            if selected is not None:
                planned_amount = round(float(selected.get("amount") or 0), 2)
                if amount > planned_amount + 0.005:
                    raise PaymentConfirmationError(
                        f"本次金额不能超过所选节点 ¥{planned_amount:,.2f}",
                        code="amount_exceeds_node",
                    )
                confirmed_id = str(selected.get("id") or "")
                due_at = str(selected.get("dueAt") or project.get("dueDate") or "")
                selected.update(
                    {
                        "amount": amount,
                        "type": payment_type,
                        "status": "confirmed",
                        "paidAt": paid_at_value,
                        "dueAt": due_at,
                        "notes": notes or "已确认到账",
                        "confirmationRequestId": request_id,
                    }
                )
                remainder = round(min(planned_amount - amount, outstanding - amount), 2)
                if remainder > 0.005:
                    remainder_id = f"pay-remain-{request_id}"
                    snapshot["payments"].append(
                        {
                            "id": remainder_id,
                            "projectId": project_id,
                            "customerId": customer_id,
                            "changeOrderId": selected.get("changeOrderId"),
                            "amount": remainder,
                            "type": payment_type,
                            "status": "pending",
                            "paidAt": paid_at_value,
                            "dueAt": due_at,
                            "notes": "部分到账后的剩余应收",
                            "remainderOfRequestId": request_id,
                        }
                    )
            else:
                confirmed_id = f"pay-{request_id}"
                due_at = str(project.get("dueDate") or paid_at_value[:10])
                snapshot["payments"].append(
                    {
                        "id": confirmed_id,
                        "projectId": project_id,
                        "customerId": customer_id,
                        "amount": amount,
                        "type": payment_type,
                        "status": "confirmed",
                        "paidAt": paid_at_value,
                        "dueAt": due_at,
                        "notes": notes or "已确认到账",
                        "confirmationRequestId": request_id,
                    }
                )
                remainder = round(outstanding - amount, 2)
                if remainder > 0.005:
                    remainder_id = f"pay-remain-{request_id}"
                    snapshot["payments"].append(
                        {
                            "id": remainder_id,
                            "projectId": project_id,
                            "customerId": customer_id,
                            "amount": remainder,
                            "type": "final",
                            "status": "pending",
                            "paidAt": paid_at_value,
                            "dueAt": due_at,
                            "notes": "本次到账后的剩余应收",
                            "remainderOfRequestId": request_id,
                        }
                    )

            revision, normalized = self.save_in_session(
                session, snapshot, expected_revision
            )
            session.commit()
            return {
                "revision": revision,
                "snapshot": normalized,
                "payment_id": confirmed_id,
                "remainder_payment_id": remainder_id,
                "idempotent": False,
            }

    def record_settlement_issue(
        self,
        *,
        request_id: str,
        expected_revision: int,
        project_id: str,
        issue_type: str,
        receivable_impact: float,
        refund_amount: float,
        occurred_at: str,
        reason: str,
        notes: str,
    ) -> dict[str, Any]:
        """Record a client-project exception and atomically adjust collectible cash flow."""

        receivable_impact = round(float(receivable_impact), 2)
        refund_amount = round(float(refund_amount), 2)
        reason = reason.strip()
        notes = notes.strip()
        if receivable_impact < 0 or refund_amount < 0:
            raise SettlementIssueError("异常影响金额不能小于 0", code="amount_invalid")
        if not reason:
            raise SettlementIssueError("请填写异常原因", code="reason_required")

        with self.database.session() as session:
            state = self._state(session)
            snapshot = normalize_snapshot(json.loads(state.snapshot_json))
            previous = next(
                (
                    row
                    for row in snapshot["settlementIssues"]
                    if row.get("requestId") == request_id
                ),
                None,
            )
            if previous is not None:
                same_request = (
                    str(previous.get("projectId") or "") == project_id
                    and str(previous.get("type") or "") == issue_type
                    and abs(float(previous.get("receivableImpact") or 0) - receivable_impact) <= 0.005
                    and abs(float(previous.get("refundAmount") or 0) - refund_amount) <= 0.005
                    and str(previous.get("reason") or "").strip() == reason
                )
                if not same_request:
                    raise SettlementIssueError(
                        "该异常请求编号已经用于其他记录，请重新打开异常窗口",
                        code="request_reused",
                    )
                return {
                    "revision": state.revision,
                    "snapshot": snapshot,
                    "issue_id": str(previous.get("id") or ""),
                    "idempotent": True,
                }
            if state.revision != expected_revision:
                raise RevisionConflict(state.revision)

            project = next(
                (row for row in snapshot["projects"] if row.get("id") == project_id),
                None,
            )
            if project is None:
                raise SettlementIssueError("项目不存在或已被删除", code="project_missing")
            customer_id = str(project.get("customerId") or "")
            if project.get("projectKind") == "personal" or not customer_id:
                raise SettlementIssueError(
                    "只有接单项目可以记录客户与结算异常",
                    code="client_project_required",
                )

            project_payments = [
                row for row in snapshot["payments"] if row.get("projectId") == project_id
            ]
            gross_receipts = round(
                sum(
                    float(row.get("amount") or 0)
                    for row in project_payments
                    if row.get("status") in {"confirmed", "refunded"}
                ),
                2,
            )
            legacy_refunds = round(
                sum(
                    float(row.get("amount") or 0)
                    for row in project_payments
                    if row.get("status") == "refunded"
                ),
                2,
            )
            project_issues = [
                row
                for row in snapshot["settlementIssues"]
                if row.get("projectId") == project_id
            ]
            previous_uncollectible = round(
                sum(float(row.get("receivableImpact") or 0) for row in project_issues),
                2,
            )
            previous_issue_refunds = round(
                sum(float(row.get("refundAmount") or 0) for row in project_issues),
                2,
            )
            collectible_outstanding = round(
                max(
                    0.0,
                    float(project.get("totalAmount") or 0)
                    - gross_receipts
                    - previous_uncollectible,
                ),
                2,
            )
            refundable = round(
                max(0.0, gross_receipts - legacy_refunds - previous_issue_refunds),
                2,
            )
            if receivable_impact > collectible_outstanding + 0.005:
                raise SettlementIssueError(
                    f"确认无法收回的金额不能超过当前可收余额 ¥{collectible_outstanding:,.2f}",
                    code="impact_exceeds_outstanding",
                )
            if (
                issue_type in TERMINAL_SETTLEMENT_ISSUE_TYPES
                and abs(receivable_impact - collectible_outstanding) > 0.005
            ):
                raise SettlementIssueError(
                    f"项目取消或终止合作时，必须将当前可收余额 ¥{collectible_outstanding:,.2f} 全部确认为无法收回",
                    code="terminal_issue_requires_full_writeoff",
                )
            if refund_amount > refundable + 0.005:
                raise SettlementIssueError(
                    f"实际退款不能超过当前可退款净到账 ¥{refundable:,.2f}",
                    code="refund_exceeds_receipts",
                )

            digest = hashlib.sha1(request_id.encode("utf-8")).hexdigest()[:24]
            issue_id = f"issue-{digest}"
            created_at = utcnow().isoformat()
            issue = {
                "id": issue_id,
                "projectId": project_id,
                "customerId": customer_id,
                "type": issue_type,
                "receivableImpact": receivable_impact,
                "refundAmount": refund_amount,
                "occurredAt": str(occurred_at),
                "reason": reason,
                "notes": notes,
                "createdAt": created_at,
                "requestId": request_id,
            }
            snapshot["settlementIssues"].insert(0, issue)
            self._write_off_pending_nodes(
                snapshot,
                project_id=project_id,
                customer_id=customer_id,
                issue_id=issue_id,
                occurred_at=str(occurred_at),
                amount=receivable_impact,
            )

            revision, normalized = self.save_in_session(
                session, snapshot, expected_revision
            )
            session.commit()
            return {
                "revision": revision,
                "snapshot": normalized,
                "issue_id": issue_id,
                "idempotent": False,
            }

    @staticmethod
    def _write_off_pending_nodes(
        snapshot: dict[str, Any],
        *,
        project_id: str,
        customer_id: str,
        issue_id: str,
        occurred_at: str,
        amount: float,
    ) -> None:
        remaining = round(float(amount), 2)
        if remaining <= 0.005:
            return
        pending = sorted(
            (
                row
                for row in snapshot["payments"]
                if row.get("projectId") == project_id and row.get("status") == "pending"
            ),
            key=lambda row: str(row.get("dueAt") or ""),
            reverse=True,
        )
        suffix = issue_id.removeprefix("issue-")
        for index, row in enumerate(pending):
            if remaining <= 0.005:
                break
            planned = round(float(row.get("amount") or 0), 2)
            if planned <= 0:
                continue
            applied = min(planned, remaining)
            original_notes = str(row.get("notes") or "").strip()
            write_off_note = f"项目异常核销 · {issue_id}"
            if applied >= planned - 0.005:
                row["status"] = "written_off"
                row["notes"] = f"{original_notes}；{write_off_note}" if original_notes else write_off_note
            else:
                row["amount"] = round(planned - applied, 2)
                snapshot["payments"].append(
                    {
                        "id": f"writeoff-{suffix}-{index}",
                        "projectId": project_id,
                        "customerId": customer_id,
                        "amount": round(applied, 2),
                        "type": str(row.get("type") or "final"),
                        "status": "written_off",
                        "paidAt": occurred_at,
                        "dueAt": str(row.get("dueAt") or occurred_at[:10]),
                        "notes": write_off_note,
                    }
                )
            remaining = round(remaining - applied, 2)

    def save_in_session(
        self,
        session: Session,
        snapshot: dict[str, Any],
        expected_revision: int,
        *,
        trusted_delivery_sync: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        state = self._state(session)
        if state.revision != expected_revision:
            raise RevisionConflict(state.revision)
        normalized = normalize_snapshot(snapshot)
        if not trusted_delivery_sync:
            self._preserve_derived_delivery_fields(session, normalized)
        state.revision += 1
        state.snapshot_json = canonical_json(normalized)
        state.updated_at = utcnow()
        self._sync_normalized(session, normalized)
        session.flush()
        return state.revision, normalized

    @staticmethod
    def _preserve_derived_delivery_fields(
        session: Session,
        snapshot: dict[str, Any],
    ) -> None:
        """Reject legacy snapshot overwrites of phase-four derived values."""

        project_ids = [
            str(row.get("id") or "")
            for row in snapshot.get("projects", [])
            if str(row.get("id") or "")
        ]
        existing_projects = (
            {
                row.id: row
                for row in session.scalars(
                    select(BusinessProject).where(BusinessProject.id.in_(project_ids))
                )
            }
            if project_ids
            else {}
        )
        for row in snapshot.get("projects", []):
            project_id = str(row.get("id") or "")
            existing = existing_projects.get(project_id)
            row["progress"] = int(existing.progress) if existing else 0
            row["progressSource"] = (
                str(existing.progress_source or "verified") if existing else "verified"
            )
            if existing and existing.legacy_progress is not None:
                row["legacyProgress"] = int(existing.legacy_progress)

        task_ids = [
            str(row.get("id") or "")
            for row in snapshot.get("tasks", [])
            if str(row.get("id") or "")
        ]
        existing_tasks = (
            {
                row.id: row
                for row in session.scalars(
                    select(BusinessTask).where(BusinessTask.id.in_(task_ids))
                )
            }
            if task_ids
            else {}
        )
        for row in snapshot.get("tasks", []):
            task_id = str(row.get("id") or "")
            existing = existing_tasks.get(task_id)
            row["actualHours"] = (
                round(float(existing.actual_hours), 6) if existing else 0.0
            )

        # Old clients used physical removal as "delete". Phase four keeps
        # delivery history and requires an explicit retirement operation, so an
        # ordinary ledger save cannot silently erase an active task from the
        # canonical snapshot.
        snapshot_task_ids = {
            str(row.get("id") or "") for row in snapshot.get("tasks", [])
        }
        snapshot_project_ids = {
            str(row.get("id") or "") for row in snapshot.get("projects", [])
        }
        missing_active_tasks = list(
            session.scalars(
                select(BusinessTask).where(
                    BusinessTask.project_id.in_(snapshot_project_ids),
                    BusinessTask.delivery_scope_active.is_(True),
                    BusinessTask.id.not_in(snapshot_task_ids),
                )
            )
        ) if snapshot_project_ids else []
        for task in missing_active_tasks:
            snapshot["tasks"].append(
                {
                    "id": task.id,
                    "projectId": task.project_id,
                    "title": task.title,
                    "status": task.status,
                    "startDate": task.start_date,
                    "dueDate": task.due_date,
                    "estimatedHours": float(task.estimated_hours),
                    "actualHours": round(float(task.actual_hours), 6),
                    "stage": _safe_json_object(task.stage_payload_json),
                }
            )

    def _sync_normalized(self, session: Session, snapshot: dict[str, Any]) -> None:
        def put(model, record_id: str, values: dict[str, Any]):
            row = session.get(model, record_id)
            if row is None:
                row = model(id=record_id, **values)
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)

        for row in snapshot["customers"]:
            if not _row_id(row):
                continue
            put(BusinessCustomer, _row_id(row), {
                "name": str(row.get("name") or "未命名客户"),
                "source": str(row.get("source") or "other"),
                "phone": str(row.get("phone") or ""),
                "follow_up_status": str(row.get("followUpStatus") or "new"),
                "last_contact_at": str(row.get("lastContactAt") or ""),
                "level": str(row.get("level") or "C"),
                "tags_json": canonical_json(row.get("tags") or []),
                "current_need": str(row.get("currentNeed") or ""),
                "price_type": str(row.get("priceType") or ""),
                "price_amount": (
                    float(row["priceAmount"])
                    if row.get("priceAmount") is not None
                    else None
                ),
                "next_action": str(row.get("nextAction") or ""),
                "notes": str(row.get("notes") or ""),
            })
        for row in snapshot["projects"]:
            if not _row_id(row):
                continue
            project_kind = "personal" if row.get("projectKind") == "personal" else "client"
            item_external_id = str(row.get("itemExternalId") or "").strip()
            item_id = None
            if item_external_id:
                item_id = session.scalar(
                    select(Item.id)
                    .join(ProductMonitor, ProductMonitor.item_id == Item.id)
                    .where(
                        Item.external_id == item_external_id,
                        ProductMonitor.ownership_status == "owned",
                    )
                    .limit(1)
                )
                if item_id is None:
                    raise LedgerValidationError(
                        "来源商品必须是当前账号已确认的本人商品",
                        code="owned_product_required",
                    )
            put(BusinessProject, _row_id(row), {
                "name": str(row.get("name") or "未命名项目"),
                "customer_id": str(row["customerId"]) if row.get("customerId") else None,
                "project_kind": project_kind,
                "lead_id": row.get("leadId"),
                "conversation_id": row.get("conversationId"),
                "item_id": item_id,
                "requirement_version_id": row.get("requirementVersionId"),
                "quote_id": row.get("quoteId"),
                "total_amount": float(row.get("totalAmount") or 0),
                "start_date": str(row.get("startDate") or ""),
                "due_date": str(row.get("dueDate") or ""),
                "progress": int(row.get("progress") or 0),
                "legacy_progress": (
                    int(row["legacyProgress"])
                    if row.get("legacyProgress") is not None
                    else None
                ),
                "progress_source": str(row.get("progressSource") or "verified"),
                "status": str(row.get("status") or "pending"),
                "type": str(row.get("type") or "定制开发"),
                "estimated_hours": float(row.get("estimatedHours") or 0),
                "accent": str(row.get("accent") or "blue"),
                "notes": str(row.get("notes") or ""),
            })
        for row in snapshot["changeOrders"]:
            if (
                not _row_id(row)
                or not row.get("projectId")
                or not row.get("customerId")
            ):
                continue
            created_at_raw = str(row.get("createdAt") or "")
            try:
                created_at_value = datetime.fromisoformat(
                    created_at_raw.replace("Z", "+00:00")
                )
            except ValueError:
                created_at_value = utcnow()
            put(ProjectChangeOrderRecord, _row_id(row), {
                "project_id": str(row["projectId"]),
                "customer_id": str(row["customerId"]),
                "title": str(row.get("title") or "追加订单"),
                "amount": float(row.get("amount") or 0),
                "confirmed_at": str(row.get("confirmedAt") or ""),
                "status": str(row.get("status") or "confirmed"),
                "notes": str(row.get("notes") or ""),
                "request_id": str(row.get("requestId") or _row_id(row)),
                "created_at": created_at_value,
            })
        # The payment-node table is upgraded additively on existing SQLite
        # databases. Flush the parent audit rows before linking new children so
        # foreign-key enforcement remains deterministic across both fresh and
        # upgraded schemas.
        if snapshot["changeOrders"]:
            session.flush()
        for row in snapshot["tasks"]:
            if not _row_id(row) or not row.get("projectId"):
                continue
            put(BusinessTask, _row_id(row), {
                "project_id": str(row["projectId"]),
                "title": str(row.get("title") or "未命名任务"),
                "status": str(row.get("status") or "todo"),
                "start_date": str(row.get("startDate") or ""),
                "due_date": str(row.get("dueDate") or ""),
                "estimated_hours": float(row.get("estimatedHours") or 0),
                "actual_hours": float(row.get("actualHours") or 0),
                "stage_payload_json": canonical_json(row.get("stage") or {}),
            })
        for row in snapshot["payments"]:
            if not _row_id(row) or not row.get("projectId") or not row.get("customerId"):
                continue
            put(PaymentNode, _row_id(row), {
                "project_id": str(row["projectId"]),
                "customer_id": str(row["customerId"]),
                "change_order_id": row.get("changeOrderId"),
                "amount": float(row.get("amount") or 0),
                "type": str(row.get("type") or "milestone"),
                "status": str(row.get("status") or "pending"),
                "paid_at": str(row.get("paidAt") or ""),
                "due_at": str(row.get("dueAt") or ""),
                "notes": str(row.get("notes") or ""),
            })
        for row in snapshot["settlementIssues"]:
            if not _row_id(row) or not row.get("projectId") or not row.get("customerId"):
                continue
            created_at_raw = str(row.get("createdAt") or "")
            try:
                created_at_value = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
            except ValueError:
                created_at_value = utcnow()
            put(ProjectSettlementIssueRecord, _row_id(row), {
                "project_id": str(row["projectId"]),
                "customer_id": str(row["customerId"]),
                "issue_type": str(row.get("type") or "other"),
                "receivable_impact": float(row.get("receivableImpact") or 0),
                "refund_amount": float(row.get("refundAmount") or 0),
                "occurred_at": str(row.get("occurredAt") or ""),
                "reason": str(row.get("reason") or ""),
                "notes": str(row.get("notes") or ""),
                "request_id": str(row.get("requestId") or _row_id(row)),
                "created_at": created_at_value,
            })
        for row in snapshot["expenses"]:
            if not _row_id(row):
                continue
            put(BusinessExpense, _row_id(row), {
                "project_id": row.get("projectId"),
                "name": str(row.get("name") or "未命名支出"),
                "category": str(row.get("category") or "other"),
                "amount": float(row.get("amount") or 0),
                "paid_at": str(row.get("paidAt") or ""),
                "notes": str(row.get("notes") or ""),
            })
        for row in snapshot["logs"]:
            if not _row_id(row) or not row.get("projectId"):
                continue
            put(ProjectDevelopmentLog, _row_id(row), {
                "project_id": str(row["projectId"]),
                "created_at_text": str(row.get("createdAt") or ""),
                "content": str(row.get("content") or ""),
                "hours": float(row.get("hours") or 0),
                "category": str(row.get("category") or "development"),
            })
        for row in snapshot["attachments"]:
            if not _row_id(row) or not row.get("projectId"):
                continue
            put(AttachmentMetadata, _row_id(row), {
                "project_id": str(row["projectId"]),
                "name": str(row.get("name") or "附件"),
                "size": str(row.get("size") or ""),
                "type": str(row.get("type") or "document"),
                "uploaded_at": str(row.get("uploadedAt") or ""),
                "storage_path": str(row.get("storagePath") or ""),
            })
        for key, value in snapshot["settings"].items():
            setting = session.get(BusinessSetting, key)
            if setting is None:
                session.add(BusinessSetting(key=key, value_json=canonical_json(value)))
            else:
                setting.value_json = canonical_json(value)

    def _preview_details(self, incoming: dict[str, Any], revision: int, current: dict[str, Any]):
        additions: dict[str, int] = {}
        identical: dict[str, int] = {}
        conflicts: list[dict[str, Any]] = []
        for collection in COLLECTIONS:
            current_rows = current[collection]
            by_id = {_row_id(row): row for row in current_rows if _row_id(row)}
            by_identity = {
                key: row
                for row in current_rows
                if (key := _identity_key(collection, row)) is not None
            }
            additions[collection] = 0
            identical[collection] = 0
            for row in incoming[collection]:
                row_id = _row_id(row)
                existing = by_id.get(row_id) if row_id else None
                reason = ""
                if existing is not None:
                    if _same(existing, row):
                        identical[collection] += 1
                        continue
                    reason = "同一 ID 的内容不同"
                else:
                    key = _identity_key(collection, row)
                    existing = by_identity.get(key) if key is not None else None
                    if existing is not None and not _same(existing, row):
                        reason = "名称与关键日期相似，可能是重复记录"
                if existing is not None and reason:
                    existing_id = _row_id(existing)
                    conflicts.append({
                        "key": f"{collection}:{row_id or hashlib.sha1(canonical_json(row).encode()).hexdigest()[:12]}",
                        "collection": collection,
                        "incoming_id": row_id,
                        "existing_id": existing_id,
                        "reason": reason,
                        "incoming": row,
                        "existing": existing,
                    })
                else:
                    additions[collection] += 1
        token_source = {"revision": revision, "incoming": incoming}
        token = hashlib.sha256(canonical_json(token_source).encode("utf-8")).hexdigest()
        return token, additions, identical, conflicts

    def preview_migration(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        incoming = normalize_snapshot(snapshot)
        revision, current = self.get()
        token, additions, identical, conflicts = self._preview_details(incoming, revision, current)
        return {
            "token": token,
            "current_revision": revision,
            "incoming_counts": {key: len(incoming[key]) for key in COLLECTIONS},
            "additions": additions,
            "identical": identical,
            "conflicts": conflicts,
            "can_import_without_review": not conflicts,
        }

    def _write_backups(self, current: dict[str, Any], incoming: dict[str, Any]) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"ledger-migration-{stamp}"
        folder = self.backups_dir / name
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "sqlite-ledger.json").write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (folder / "browser-ledger.json").write_text(
            json.dumps(incoming, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        database_path = self.database.engine.url.database
        if database_path:
            source = sqlite3.connect(database_path)
            target = sqlite3.connect(folder / "xianyu-operator.db")
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
        return name

    def _extract_attachments(self, snapshot: dict[str, Any]) -> int:
        written = 0
        for row in snapshot["attachments"]:
            data_url = row.pop("dataUrl", None)
            if not isinstance(data_url, str) or not data_url.startswith("data:"):
                continue
            match = re.match(r"^data:([^;,]+)?(;base64)?,(.*)$", data_url, re.DOTALL)
            if not match:
                continue
            try:
                raw = base64.b64decode(match.group(3)) if match.group(2) else match.group(3).encode()
            except (ValueError, TypeError):
                continue
            project_id = re.sub(r"[^a-zA-Z0-9._-]", "_", str(row.get("projectId") or "unknown"))
            filename = re.sub(r"[^a-zA-Z0-9._\u4e00-\u9fff-]", "_", str(row.get("name") or row.get("id") or "attachment"))
            target_dir = self.attachments_dir / project_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / filename
            if target.exists():
                target = target_dir / f"{row.get('id', 'attachment')}-{filename}"
            target.write_bytes(raw)
            row["storagePath"] = str(target.relative_to(self.project_root))
            written += 1
        return written

    def commit_migration(
        self,
        snapshot: dict[str, Any],
        token: str,
        resolutions: dict[str, str],
    ) -> dict[str, Any]:
        incoming = normalize_snapshot(snapshot)
        revision, current = self.get()
        expected_token, additions, _identical, conflicts = self._preview_details(incoming, revision, current)
        if token != expected_token:
            raise MigrationTokenMismatch("迁移预览已过期，请重新预览")
        backup_name = self._write_backups(current, incoming)
        conflict_by_incoming = {
            (item["collection"], item["incoming_id"]): item for item in conflicts
        }
        imported = {key: 0 for key in COLLECTIONS}
        kept_sqlite = 0
        merged = deepcopy(current)
        for collection in COLLECTIONS:
            rows = merged[collection]
            by_id = {_row_id(row): index for index, row in enumerate(rows) if _row_id(row)}
            for row in incoming[collection]:
                row_id = _row_id(row)
                conflict = conflict_by_incoming.get((collection, row_id))
                if conflict:
                    if resolutions.get(conflict["key"], "sqlite") != "browser":
                        kept_sqlite += 1
                        continue
                    existing_id = conflict["existing_id"]
                    index = by_id.get(existing_id)
                    if index is not None:
                        rows[index] = row
                    else:
                        rows.append(row)
                    imported[collection] += 1
                    continue
                if row_id and row_id in by_id:
                    continue
                if any(_same(existing, row) for existing in rows):
                    continue
                rows.append(row)
                imported[collection] += 1
        merged["settings"] = {**merged["settings"], **incoming["settings"]}
        merged["completedOrderCount"] = max(
            int(merged.get("completedOrderCount") or 0),
            int(incoming.get("completedOrderCount") or 0),
        )
        attachments_written = self._extract_attachments(merged)
        new_revision, normalized = self.save(merged, revision)
        return {
            "revision": new_revision,
            "imported": imported,
            "kept_sqlite": kept_sqlite,
            "attachments_written": attachments_written,
            "backup_name": backup_name,
            "snapshot": normalized,
        }
