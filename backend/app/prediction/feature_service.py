from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..database import Database
from ..ledger import LedgerService
from ..models import (
    BusinessProject,
    BusinessSetting,
    Conversation,
    CustomerChannelIdentity,
    Message,
    QuoteProposal,
    RequirementCase,
    SalesAnalysisRun,
    SalesLead,
)
from ..services.project_outcomes import ProjectOutcomeService


PREDICTION_TIMEZONE = "Asia/Shanghai"
FEATURE_SCHEMA_VERSION = "prediction-features-v2-verified-outcomes"
ACTIVE_PROJECT_STATUSES = {"pending", "in_progress", "overdue"}
TERMINAL_PROJECT_ISSUE_TYPES = {"project_cancelled", "cooperation_terminated"}
TERMINAL_CUSTOMER_STATUSES = {"won", "lost", "inactive"}


def parse_datetime(value: Any, zone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


@dataclass(slots=True)
class ProjectFeature:
    id: str
    label: str
    status: str
    start_date: date | None
    due_date: date | None
    progress: int
    estimated_hours: float
    actual_hours: float
    remaining_hours: float
    remaining_source: str
    task_count: int
    unfinished_task_count: int
    task_estimate_coverage: float
    change_order_count: int
    blocker_count: int
    test_failure_count: int
    rework_hours: float
    verified_progress: int
    outcome_available_at: datetime
    outcome_finalized_at: datetime | None


@dataclass(slots=True)
class CustomerFeature:
    id: str
    label: str
    follow_up_status: str
    last_contact_at: datetime | None
    conversation_ids: list[int]
    unread_count: int
    last_message_at: datetime | None
    last_message_direction: str | None
    inbound_24h: int
    inbound_7d: int
    outbound_7d: int
    requirement_count: int
    quote_count: int
    confirmed_sales_stage: str | None
    confirmed_need_signal_count: int


@dataclass(slots=True)
class FeatureBundle:
    generated_at: datetime
    local_now: datetime
    ledger_revision: int
    input_snapshot_hash: str
    daily_available_hours: float
    availability_source: str
    projects: list[ProjectFeature]
    customers: list[CustomerFeature]
    payments: list[dict[str, Any]]
    expenses: list[dict[str, Any]]
    settlement_issues: list[dict[str, Any]]


class PredictionFeatureService:
    """Build a privacy-minimized, deterministic feature snapshot.

    Message content is never copied into the prediction snapshot. Customer
    priority uses relationship, direction, timestamps, unread state and only
    human-confirmed structured sales signals.
    """

    def __init__(
        self,
        database: Database,
        ledger: LedgerService,
        outcomes: ProjectOutcomeService | None = None,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.outcomes = outcomes or ProjectOutcomeService()
        self.zone = ZoneInfo(PREDICTION_TIMEZONE)

    def build(self, *, now: datetime | None = None) -> FeatureBundle:
        generated_at = now or datetime.now(timezone.utc)
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        generated_at = generated_at.astimezone(timezone.utc).replace(microsecond=0)
        local_now = generated_at.astimezone(self.zone)
        ledger_revision, snapshot = self.ledger.get()

        raw_hours = snapshot.get("settings", {}).get("defaultDailyAvailableHours")
        configured_hours = number(raw_hours)
        daily_available_hours = configured_hours if configured_hours > 0 else 8.0

        with self.database.session() as session:
            setting_row = session.get(BusinessSetting, "defaultDailyAvailableHours")
            availability_source = "user_setting" if setting_row is not None else "default"
            identities = list(session.scalars(select(CustomerChannelIdentity)))
            leads = list(session.scalars(select(SalesLead)))
            conversations = list(session.scalars(select(Conversation)))
            messages = list(
                session.scalars(
                    select(Message).order_by(Message.received_at.asc(), Message.id.asc())
                )
            )
            requirement_cases = list(session.scalars(select(RequirementCase)))
            quotes = list(session.scalars(select(QuoteProposal)))
            confirmed_runs = list(
                session.scalars(
                    select(SalesAnalysisRun)
                    .where(
                        SalesAnalysisRun.status == "completed",
                        SalesAnalysisRun.confirmed_at.is_not(None),
                    )
                    .order_by(SalesAnalysisRun.created_at.desc())
                )
            )
            relational_projects = {
                row.id: row for row in session.scalars(select(BusinessProject))
            }

        tasks_by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in snapshot.get("tasks", []):
            project_id = str(row.get("projectId") or "")
            if project_id:
                tasks_by_project[project_id].append(row)
        changes_by_project: dict[str, int] = defaultdict(int)
        for row in snapshot.get("changeOrders", []):
            if str(row.get("status") or "confirmed") != "confirmed":
                continue
            project_id = str(row.get("projectId") or "")
            if project_id:
                changes_by_project[project_id] += 1
        settlement_issues = [
            dict(row) for row in snapshot.get("settlementIssues", [])
        ]
        terminal_project_ids = {
            str(row.get("projectId") or "")
            for row in settlement_issues
            if str(row.get("type") or "") in TERMINAL_PROJECT_ISSUE_TYPES
        }

        projects: list[ProjectFeature] = []
        for row in snapshot.get("projects", []):
            status = str(row.get("status") or "pending")
            if status not in ACTIVE_PROJECT_STATUSES:
                continue
            project_id = str(row.get("id") or "")
            if not project_id or project_id in terminal_project_ids:
                continue
            project_tasks = tasks_by_project.get(project_id, [])
            unfinished = [
                task
                for task in project_tasks
                if str(task.get("status") or "todo") not in {"done", "completed"}
            ]
            covered = [task for task in unfinished if number(task.get("estimatedHours")) > 0]
            task_coverage = len(covered) / len(unfinished) if unfinished else 1.0
            project_estimated = max(0.0, number(row.get("estimatedHours")))
            relational = relational_projects.get(project_id)
            project_progress = max(
                0,
                min(
                    100,
                    int(relational.progress if relational is not None else number(row.get("progress"))),
                ),
            )
            outcome = self.outcomes.build(
                session,
                project_id,
                verified_progress=project_progress,
            )
            if unfinished and task_coverage == 1.0:
                remaining = sum(
                    max(
                        0.0,
                        number(task.get("estimatedHours"))
                        - number(task.get("actualHours")),
                    )
                    for task in unfinished
                )
                remaining_source = "tasks"
            else:
                remaining = project_estimated * (100 - project_progress) / 100
                remaining_source = "project_progress"
            projects.append(
                ProjectFeature(
                    id=project_id,
                    label=str(row.get("name") or "未命名项目"),
                    status=status,
                    start_date=parse_date(row.get("startDate")),
                    due_date=parse_date(row.get("dueDate")),
                    progress=project_progress,
                    estimated_hours=round(project_estimated, 2),
                    actual_hours=round(outcome.actual_hours, 2),
                    remaining_hours=round(max(0.0, remaining), 2),
                    remaining_source=remaining_source,
                    task_count=len(project_tasks),
                    unfinished_task_count=len(unfinished),
                    task_estimate_coverage=round(task_coverage, 4),
                    change_order_count=outcome.change_order_count,
                    blocker_count=outcome.blocker_count,
                    test_failure_count=outcome.test_failure_count,
                    rework_hours=outcome.rework_hours,
                    verified_progress=outcome.verified_progress,
                    outcome_available_at=outcome.available_at,
                    outcome_finalized_at=outcome.finalized_at,
                )
            )

        customer_conversations: dict[str, set[int]] = defaultdict(set)
        for identity in identities:
            if identity.customer_id and identity.conversation_id is not None:
                customer_conversations[str(identity.customer_id)].add(
                    int(identity.conversation_id)
                )
        for lead in leads:
            if lead.customer_id:
                customer_conversations[str(lead.customer_id)].add(int(lead.conversation_id))

        conversation_by_id = {row.id: row for row in conversations}
        messages_by_conversation: dict[int, list[Message]] = defaultdict(list)
        for message in messages:
            messages_by_conversation[int(message.conversation_id)].append(message)
        requirement_counts: dict[str, int] = defaultdict(int)
        for row in requirement_cases:
            requirement_counts[str(row.customer_id)] += 1
        lead_customer = {row.id: str(row.customer_id) for row in leads if row.customer_id}
        quote_counts: dict[str, int] = defaultdict(int)
        for quote in quotes:
            customer_id = lead_customer.get(quote.lead_id)
            if customer_id:
                quote_counts[customer_id] += 1
        confirmed_by_conversation: dict[int, SalesAnalysisRun] = {}
        for run in confirmed_runs:
            confirmed_by_conversation.setdefault(int(run.conversation_id), run)

        customers: list[CustomerFeature] = []
        for row in snapshot.get("customers", []):
            customer_id = str(row.get("id") or "")
            if not customer_id:
                continue
            conversation_ids = sorted(customer_conversations.get(customer_id, set()))
            related_messages = [
                message
                for conversation_id in conversation_ids
                for message in messages_by_conversation.get(conversation_id, [])
            ]
            related_messages.sort(key=lambda item: (item.received_at, item.id))
            last_message = related_messages[-1] if related_messages else None
            unread_count = sum(
                max(0, int(conversation_by_id[conversation_id].unread_count or 0))
                for conversation_id in conversation_ids
                if conversation_id in conversation_by_id
            )
            cutoff_24h = generated_at - timedelta(hours=24)
            cutoff_7d = generated_at - timedelta(days=7)
            stages: list[str] = []
            need_signal_count = 0
            for conversation_id in conversation_ids:
                run = confirmed_by_conversation.get(conversation_id)
                if run is None or not run.structured_json:
                    continue
                try:
                    payload = json.loads(run.structured_json)
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    if payload.get("stage"):
                        stages.append(str(payload["stage"]))
                    signals = payload.get("need_signals")
                    if isinstance(signals, list):
                        need_signal_count += len(signals)
            customers.append(
                CustomerFeature(
                    id=customer_id,
                    label=str(row.get("name") or "未命名客户"),
                    follow_up_status=str(row.get("followUpStatus") or "new"),
                    last_contact_at=parse_datetime(row.get("lastContactAt"), self.zone),
                    conversation_ids=conversation_ids,
                    unread_count=unread_count,
                    last_message_at=(
                        parse_datetime(last_message.received_at, self.zone)
                        if last_message is not None
                        else None
                    ),
                    last_message_direction=(
                        str(last_message.direction) if last_message is not None else None
                    ),
                    inbound_24h=sum(
                        1
                        for message in related_messages
                        if message.direction == "inbound"
                        and message.received_at.replace(tzinfo=message.received_at.tzinfo or timezone.utc)
                        >= cutoff_24h
                    ),
                    inbound_7d=sum(
                        1
                        for message in related_messages
                        if message.direction == "inbound"
                        and message.received_at.replace(tzinfo=message.received_at.tzinfo or timezone.utc)
                        >= cutoff_7d
                    ),
                    outbound_7d=sum(
                        1
                        for message in related_messages
                        if message.direction == "outbound"
                        and message.received_at.replace(tzinfo=message.received_at.tzinfo or timezone.utc)
                        >= cutoff_7d
                    ),
                    requirement_count=requirement_counts.get(customer_id, 0),
                    quote_count=quote_counts.get(customer_id, 0),
                    confirmed_sales_stage=stages[0] if stages else None,
                    confirmed_need_signal_count=need_signal_count,
                )
            )

        hash_payload = {
            "ledger_revision": ledger_revision,
            "daily_available_hours": daily_available_hours,
            "availability_source": availability_source,
            "projects": [asdict(row) for row in projects],
            "customers": [asdict(row) for row in customers],
            "payments": snapshot.get("payments", []),
            "expenses": snapshot.get("expenses", []),
            "settlement_issues": settlement_issues,
        }
        encoded = json.dumps(
            hash_payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
        input_snapshot_hash = hashlib.sha256(encoded).hexdigest()
        return FeatureBundle(
            generated_at=generated_at,
            local_now=local_now,
            ledger_revision=ledger_revision,
            input_snapshot_hash=input_snapshot_hash,
            daily_available_hours=round(daily_available_hours, 2),
            availability_source=availability_source,
            projects=projects,
            customers=customers,
            payments=[dict(row) for row in snapshot.get("payments", [])],
            expenses=[dict(row) for row in snapshot.get("expenses", [])],
            settlement_issues=settlement_issues,
        )
