from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any

from .explanation_service import PredictionExplanationService
from .feature_service import (
    FeatureBundle,
    ProjectFeature,
    TERMINAL_CUSTOMER_STATUSES,
    number,
    parse_datetime,
)
from .schemas import PredictionDriver, PredictionFact, PredictionResult


ENGINE_VERSION = "prediction-engine-v1"
MODEL_VERSION = "transparent-baselines-v2-outcome-evaluation"
WORKLOAD_HORIZON_DAYS = 14
CASHFLOW_HORIZON_DAYS = 30

def _risk_for_load(load_rate: float) -> str:
    if load_rate > 110:
        return "overloaded"
    if load_rate >= 90:
        return "high"
    if load_rate >= 70:
        return "warning"
    return "normal"


def _result_id(target: str, entity_id: str | None = None) -> str:
    return f"live-{target}-{entity_id or 'portfolio'}"


def workload_prediction(bundle: FeatureBundle) -> PredictionResult:
    total_remaining = round(sum(row.remaining_hours for row in bundle.projects), 2)
    available = round(bundle.daily_available_hours * WORKLOAD_HORIZON_DAYS, 2)
    load_rate = round((total_remaining / available * 100) if available > 0 else 0, 1)
    risk_level = _risk_for_load(load_rate)
    estimated_coverage = (
        sum(1 for row in bundle.projects if row.estimated_hours > 0)
        / len(bundle.projects)
        if bundle.projects
        else 1.0
    )
    if not bundle.projects:
        sufficiency = "low"
    elif estimated_coverage == 1 and bundle.availability_source == "user_setting":
        sufficiency = "high"
    elif estimated_coverage >= 0.7:
        sufficiency = "medium"
    else:
        sufficiency = "low"
    contributors = sorted(
        bundle.projects, key=lambda row: (row.remaining_hours, row.id), reverse=True
    )[:5]
    drivers = [
        PredictionDriver(
            code="project_remaining_hours",
            label=row.label,
            detail=f"预计剩余 {row.remaining_hours:g} 小时",
            impact=row.remaining_hours,
            evidence_refs=[f"project:{row.id}.remaining_hours"],
        )
        for row in contributors
        if row.remaining_hours > 0
    ]
    if bundle.availability_source == "default":
        drivers.append(
            PredictionDriver(
                code="default_capacity",
                label="可用工时尚未人工设置",
                detail=f"当前按默认每天 {bundle.daily_available_hours:g} 小时估算",
                evidence_refs=["settings.default_daily_available_hours"],
            )
        )
    horizon_start = bundle.generated_at
    horizon_end = horizon_start + timedelta(days=WORKLOAD_HORIZON_DAYS)
    return PredictionResult(
        id=_result_id("workload_14d"),
        target="workload_14d",
        entity_type="portfolio",
        horizon="14d",
        horizon_days=WORKLOAD_HORIZON_DAYS,
        generated_at=bundle.generated_at,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        prediction_value=load_rate,
        score=load_rate if load_rate <= 100 else 100,
        risk_level=risk_level,  # type: ignore[arg-type]
        data_sufficiency=sufficiency,  # type: ignore[arg-type]
        method="deterministic_capacity_ratio_v1",
        model_version=MODEL_VERSION,
        summary=(
            f"未来 14 天预计负载 {load_rate:g}%，"
            f"风险为{PredictionExplanationService.risk_label(risk_level)}。"
        ),
        drivers=drivers,
        facts=[
            PredictionFact(
                key="remaining_hours",
                label="预计剩余工作",
                value=total_remaining,
                unit="hours",
                evidence_ref="projects.remaining_hours",
            ),
            PredictionFact(
                key="available_hours",
                label="未来可用工时",
                value=available,
                unit="hours",
                evidence_ref="settings.default_daily_available_hours",
            ),
            PredictionFact(
                key="active_project_count",
                label="纳入项目",
                value=len(bundle.projects),
                unit="projects",
                evidence_ref="projects.active",
            ),
        ],
        evidence_refs=[
            "projects.active",
            "projects.remaining_hours",
            "settings.default_daily_available_hours",
        ],
    )


def _capacity_pressure_score(
    project: ProjectFeature,
    projects: list[ProjectFeature],
    *,
    today: date,
    daily_hours: float,
) -> tuple[float, str]:
    if project.due_date is None:
        return 0.0, "缺少交付日期，未计算容量缺口"
    days = min(
        WORKLOAD_HORIZON_DAYS,
        max(0, (project.due_date - today).days + 1),
    )
    available = days * daily_hours
    competing = sum(
        row.remaining_hours
        for row in projects
        if row.due_date is not None and row.due_date <= project.due_date
    )
    if competing <= 0:
        return 0.0, "交付前没有待完成工时"
    if available <= 0:
        return 35.0, f"交付日已到，但仍有 {competing:g} 小时待完成"
    ratio = competing / available
    if ratio > 1.25:
        score = 35.0
    elif ratio > 1:
        score = 28.0
    elif ratio > 0.8:
        score = 18.0
    elif ratio > 0.6:
        score = 8.0
    else:
        score = 0.0
    return score, f"交付前累计待完成 {competing:g} 小时，可用约 {available:g} 小时"


def _schedule_gap_score(project: ProjectFeature, today: date) -> tuple[float, str]:
    if project.start_date is None or project.due_date is None:
        return 0.0, "缺少完整起止日期，未计算计划进度差"
    total_days = max(1, (project.due_date - project.start_date).days)
    elapsed = max(0, (today - project.start_date).days)
    expected_progress = min(100.0, elapsed / total_days * 100)
    gap = expected_progress - project.progress
    if gap >= 40:
        score = 25.0
    elif gap >= 25:
        score = 18.0
    elif gap >= 10:
        score = 10.0
    else:
        score = 0.0
    return score, f"按日期应约完成 {expected_progress:.0f}%，当前记录 {project.progress}%"


def project_delay_predictions(bundle: FeatureBundle) -> list[PredictionResult]:
    today = bundle.local_now.date()
    parallel_count = len(bundle.projects)
    results: list[PredictionResult] = []
    for project in bundle.projects:
        drivers: list[PredictionDriver] = []
        score = 0.0
        if project.due_date is None:
            deadline_score = 0.0
            deadline_detail = "缺少交付日期"
        else:
            remaining_days = (project.due_date - today).days
            if remaining_days < 0:
                deadline_score = 20.0
                deadline_detail = f"交付日已过去 {abs(remaining_days)} 天"
            elif remaining_days <= 2:
                deadline_score = 18.0
                deadline_detail = f"距离交付仅 {remaining_days} 天"
            elif remaining_days <= 7:
                deadline_score = 12.0
                deadline_detail = f"距离交付 {remaining_days} 天"
            elif remaining_days <= 14:
                deadline_score = 6.0
                deadline_detail = f"距离交付 {remaining_days} 天"
            else:
                deadline_score = 0.0
                deadline_detail = f"距离交付 {remaining_days} 天"
        if deadline_score:
            drivers.append(
                PredictionDriver(
                    code="deadline_urgency",
                    label="交付时间压力",
                    detail=deadline_detail,
                    impact=deadline_score,
                    evidence_refs=[f"project:{project.id}.due_date"],
                )
            )
        score += deadline_score

        capacity_score, capacity_detail = _capacity_pressure_score(
            project,
            bundle.projects,
            today=today,
            daily_hours=bundle.daily_available_hours,
        )
        if capacity_score:
            drivers.append(
                PredictionDriver(
                    code="capacity_gap",
                    label="交付前容量压力",
                    detail=capacity_detail,
                    impact=capacity_score,
                    evidence_refs=[
                        f"project:{project.id}.remaining_hours",
                        "settings.default_daily_available_hours",
                    ],
                )
            )
        score += capacity_score

        gap_score, gap_detail = _schedule_gap_score(project, today)
        if gap_score:
            drivers.append(
                PredictionDriver(
                    code="schedule_progress_gap",
                    label="计划进度滞后",
                    detail=gap_detail,
                    impact=gap_score,
                    evidence_refs=[
                        f"project:{project.id}.progress",
                        f"project:{project.id}.start_date",
                        f"project:{project.id}.due_date",
                    ],
                )
            )
        score += gap_score

        if project.estimated_hours > 0 and project.actual_hours > project.estimated_hours:
            overrun_ratio = project.actual_hours / project.estimated_hours
            overrun_score = 10.0 if overrun_ratio > 1.2 else 6.0
            score += overrun_score
            drivers.append(
                PredictionDriver(
                    code="effort_overrun",
                    label="工时已经超出预计",
                    detail=(
                        f"累计实际 {project.actual_hours:g} 小时，"
                        f"预计 {project.estimated_hours:g} 小时"
                    ),
                    impact=overrun_score,
                    evidence_refs=[f"project:{project.id}.task_hours"],
                )
            )

        change_score = min(5.0, project.change_order_count * 2.5)
        if change_score:
            score += change_score
            drivers.append(
                PredictionDriver(
                    code="change_orders",
                    label="已确认需求变更",
                    detail=f"已记录 {project.change_order_count} 次追加变更",
                    impact=change_score,
                    evidence_refs=[f"project:{project.id}.change_orders"],
                )
            )

        parallel_score = 5.0 if parallel_count >= 4 else 3.0 if parallel_count == 3 else 1.0 if parallel_count == 2 else 0.0
        if parallel_score:
            score += parallel_score
            drivers.append(
                PredictionDriver(
                    code="parallel_projects",
                    label="并行项目压力",
                    detail=f"当前共有 {parallel_count} 个待推进项目",
                    impact=parallel_score,
                    evidence_refs=["projects.active"],
                )
            )
        score = round(min(100.0, score), 1)
        risk_level = "high" if score >= 70 else "warning" if score >= 40 else "normal"
        required_fields = [project.start_date is not None, project.due_date is not None, project.estimated_hours > 0]
        if all(required_fields) and project.task_estimate_coverage == 1 and bundle.availability_source == "user_setting":
            sufficiency = "high"
        elif sum(required_fields) >= 2:
            sufficiency = "medium"
        else:
            sufficiency = "low"
        horizon_days = max(
            1,
            min(
                WORKLOAD_HORIZON_DAYS,
                (project.due_date - today).days + 1 if project.due_date else WORKLOAD_HORIZON_DAYS,
            ),
        )
        results.append(
            PredictionResult(
                id=_result_id("project_delay_risk", project.id),
                target="project_delay_risk",
                entity_type="project",
                entity_id=project.id,
                entity_label=project.label,
                horizon=f"{horizon_days}d",
                horizon_days=horizon_days,
                generated_at=bundle.generated_at,
                horizon_start=bundle.generated_at,
                horizon_end=bundle.generated_at + timedelta(days=horizon_days),
                score=score,
                risk_level=risk_level,  # type: ignore[arg-type]
                data_sufficiency=sufficiency,  # type: ignore[arg-type]
                method="transparent_delay_rules_v1",
                model_version=MODEL_VERSION,
                summary=(
                    f"延期风险分 {score:g}/100，"
                    f"风险为{PredictionExplanationService.risk_label(risk_level)}。"
                ),
                drivers=sorted(
                    drivers,
                    key=lambda row: (row.impact or 0, row.code),
                    reverse=True,
                ),
                facts=[
                    PredictionFact(
                        key="remaining_hours",
                        label="预计剩余工时",
                        value=project.remaining_hours,
                        unit="hours",
                        evidence_ref=f"project:{project.id}.remaining_hours",
                    ),
                    PredictionFact(
                        key="progress",
                        label="当前进度",
                        value=project.progress,
                        unit="percent",
                        evidence_ref=f"project:{project.id}.progress",
                    ),
                    PredictionFact(
                        key="change_order_count",
                        label="需求变更",
                        value=project.change_order_count,
                        unit="count",
                        evidence_ref=f"project:{project.id}.change_orders",
                    ),
                    PredictionFact(
                        key="planned_due_date",
                        label="预测时交付日期",
                        value=project.due_date.isoformat() if project.due_date else None,
                        unit="date",
                        evidence_ref=f"project:{project.id}.due_date",
                    ),
                ],
                evidence_refs=sorted(
                    {
                        evidence
                        for driver in drivers
                        for evidence in driver.evidence_refs
                    }
                ),
            )
        )
    return results


def _month_key(value: datetime) -> tuple[int, int]:
    return value.year, value.month


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _cashflow_history(bundle: FeatureBundle) -> list[float]:
    monthly_income: dict[tuple[int, int], float] = defaultdict(float)
    monthly_expense: dict[tuple[int, int], float] = defaultdict(float)
    for row in bundle.payments:
        if str(row.get("status") or "") not in {"confirmed", "refunded"}:
            continue
        parsed = parse_datetime(row.get("paidAt"), bundle.local_now.tzinfo)  # type: ignore[arg-type]
        if parsed is None:
            continue
        amount = number(row.get("amount"))
        monthly_income[_month_key(parsed)] += amount
        if row.get("status") == "refunded":
            monthly_income[_month_key(parsed)] -= amount
    for row in bundle.settlement_issues:
        parsed = parse_datetime(row.get("occurredAt"), bundle.local_now.tzinfo)  # type: ignore[arg-type]
        if parsed is not None:
            monthly_income[_month_key(parsed)] -= number(row.get("refundAmount"))
    for row in bundle.expenses:
        parsed = parse_datetime(row.get("paidAt"), bundle.local_now.tzinfo)  # type: ignore[arg-type]
        if parsed is not None:
            monthly_expense[_month_key(parsed)] += number(row.get("amount"))
    values: list[float] = []
    year, month = _previous_month(bundle.local_now.year, bundle.local_now.month)
    for _ in range(24):
        key = (year, month)
        if key not in monthly_income and key not in monthly_expense:
            break
        values.append(round(monthly_income[key] - monthly_expense[key], 2))
        year, month = _previous_month(year, month)
    return values


def cashflow_prediction(bundle: FeatureBundle) -> PredictionResult:
    horizon_start = bundle.generated_at
    horizon_end = horizon_start + timedelta(days=CASHFLOW_HORIZON_DAYS)
    known_inflow = 0.0
    scheduled_count = 0
    pending_without_due = 0
    for row in bundle.payments:
        if str(row.get("status") or "") != "pending":
            continue
        due = parse_datetime(row.get("dueAt"), bundle.local_now.tzinfo)  # type: ignore[arg-type]
        if due is None:
            pending_without_due += 1
            continue
        if horizon_start <= due.astimezone(horizon_start.tzinfo) < horizon_end:
            known_inflow += number(row.get("amount"))
            scheduled_count += 1
    # The current ledger has no planned-expense entity. Historical paid
    # expenses are facts, not future commitments, so known outflow stays zero.
    known_outflow = 0.0
    history = _cashflow_history(bundle)
    baseline = round(mean(history[:3]), 2) if len(history) >= 3 else None
    known_net = round(known_inflow - known_outflow, 2)
    prediction_value = round(known_net + baseline, 2) if baseline is not None else known_net
    if len(history) >= 6 and pending_without_due == 0:
        sufficiency = "high"
    elif len(history) >= 3 or scheduled_count > 0:
        sufficiency = "medium"
    else:
        sufficiency = "low"
    drivers = [
        PredictionDriver(
            code="known_receipts",
            label="已计划回款",
            detail=f"未来 30 天有 {scheduled_count} 个明确回款节点",
            impact=round(known_inflow, 2),
            evidence_refs=["ledger.payments.pending_due"],
        ),
        PredictionDriver(
            code="planned_expense_gap",
            label="尚无计划支出结构",
            detail="当前只能读取已发生支出，不能把历史支出伪装成未来确定支出",
            evidence_refs=["ledger.expenses.paid"],
        ),
    ]
    if baseline is not None:
        drivers.append(
            PredictionDriver(
                code="historical_moving_average",
                label="历史净现金流基线",
                detail=f"使用最近 3 个连续完整月份均值 {baseline:g} 元",
                impact=baseline,
                evidence_refs=["ledger.finance.trailing_complete_months"],
            )
        )
    else:
        drivers.append(
            PredictionDriver(
                code="history_insufficient",
                label="历史月份不足",
                detail=f"当前只有 {len(history)} 个连续完整月份，未启用移动平均",
                evidence_refs=["ledger.finance.trailing_complete_months"],
            )
        )
    return PredictionResult(
        id=_result_id("cashflow_30d"),
        target="cashflow_30d",
        entity_type="portfolio",
        horizon="30d",
        horizon_days=CASHFLOW_HORIZON_DAYS,
        generated_at=bundle.generated_at,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        prediction_value=prediction_value,
        data_sufficiency=sufficiency,  # type: ignore[arg-type]
        method=("known_plus_moving_average_v1" if baseline is not None else "known_cashflow_only_v1"),
        model_version=MODEL_VERSION,
        summary=(
            f"未来 30 天已知净现金流 {known_net:g} 元。"
            + (
                f"加入历史基线后估计为 {prediction_value:g} 元。"
                if baseline is not None
                else "历史不足，未生成基线新增收入。"
            )
        ),
        drivers=drivers,
        facts=[
            PredictionFact(
                key="known_inflow",
                label="确定性流入",
                value=round(known_inflow, 2),
                unit="CNY",
                evidence_ref="ledger.payments.pending_due",
            ),
            PredictionFact(
                key="known_outflow",
                label="已知计划支出",
                value=known_outflow,
                unit="CNY",
                evidence_ref="ledger.expenses.planned",
            ),
            PredictionFact(
                key="baseline_estimate",
                label="历史基线估计",
                value=baseline,
                unit="CNY",
                evidence_ref="ledger.finance.trailing_complete_months",
            ),
            PredictionFact(
                key="history_months",
                label="连续完整月份",
                value=len(history),
                unit="months",
                evidence_ref="ledger.finance.trailing_complete_months",
            ),
        ],
        evidence_refs=[
            "ledger.payments.pending_due",
            "ledger.expenses.planned",
            "ledger.finance.trailing_complete_months",
        ],
    )


def customer_priority_predictions(bundle: FeatureBundle) -> list[PredictionResult]:
    results: list[PredictionResult] = []
    for customer in bundle.customers:
        if customer.follow_up_status in TERMINAL_CUSTOMER_STATUSES:
            continue
        score = 10.0
        drivers: list[PredictionDriver] = []
        if customer.last_message_direction == "inbound":
            score += 35
            drivers.append(
                PredictionDriver(
                    code="waiting_for_us",
                    label="客户正在等待我方回复",
                    detail="最近一条已绑定会话消息来自客户",
                    impact=35,
                    evidence_refs=[f"customer:{customer.id}.last_message_direction"],
                )
            )
        if customer.unread_count > 0:
            unread_score = min(15.0, 5.0 + customer.unread_count * 2)
            score += unread_score
            drivers.append(
                PredictionDriver(
                    code="unread_messages",
                    label="存在未读消息",
                    detail=f"当前有 {customer.unread_count} 条未读",
                    impact=unread_score,
                    evidence_refs=[f"customer:{customer.id}.unread_count"],
                )
            )
        if customer.inbound_24h >= 3:
            activity_score = 15.0
        elif customer.inbound_24h > 0:
            activity_score = 7.0
        else:
            activity_score = 0.0
        if activity_score:
            score += activity_score
            drivers.append(
                PredictionDriver(
                    code="recent_inbound_activity",
                    label="近期联系活跃",
                    detail=f"24 小时内客户发送 {customer.inbound_24h} 条消息",
                    impact=activity_score,
                    evidence_refs=[f"customer:{customer.id}.message_activity"],
                )
            )
        if customer.last_message_at is not None:
            age = bundle.local_now - customer.last_message_at
            recency_score = 15.0 if age <= timedelta(days=1) else 10.0 if age <= timedelta(days=3) else 5.0 if age <= timedelta(days=7) else 0.0
            if recency_score:
                score += recency_score
                drivers.append(
                    PredictionDriver(
                        code="recent_contact",
                        label="最近发生联系",
                        detail=f"最近联系距今约 {max(0, int(age.total_seconds() // 3600))} 小时",
                        impact=recency_score,
                        evidence_refs=[f"customer:{customer.id}.last_message_at"],
                    )
                )
        stage_score = 10.0 if customer.follow_up_status == "proposal" else 5.0 if customer.follow_up_status in {"contacted", "following", "follow_up"} else 0.0
        if stage_score:
            score += stage_score
            drivers.append(
                PredictionDriver(
                    code="customer_stage",
                    label="客户处于跟进阶段",
                    detail=f"当前状态为 {customer.follow_up_status}",
                    impact=stage_score,
                    evidence_refs=[f"customer:{customer.id}.follow_up_status"],
                )
            )
        if customer.requirement_count:
            score += 5
            drivers.append(
                PredictionDriver(
                    code="structured_requirement",
                    label="已有结构化需求",
                    detail=f"已关联 {customer.requirement_count} 个需求案例",
                    impact=5,
                    evidence_refs=[f"customer:{customer.id}.requirement_cases"],
                )
            )
        if customer.quote_count:
            score += 10
            drivers.append(
                PredictionDriver(
                    code="quote_exists",
                    label="已经形成报价记录",
                    detail=f"已关联 {customer.quote_count} 个报价版本",
                    impact=10,
                    evidence_refs=[f"customer:{customer.id}.quotes"],
                )
            )
        if customer.confirmed_sales_stage:
            score += 5
            drivers.append(
                PredictionDriver(
                    code="confirmed_sales_signal",
                    label="已有人工确认的销售信号",
                    detail=(
                        f"阶段为 {customer.confirmed_sales_stage}，"
                        f"记录 {customer.confirmed_need_signal_count} 项需求信号"
                    ),
                    impact=5,
                    evidence_refs=[f"customer:{customer.id}.confirmed_sales_analysis"],
                )
            )
        score = round(min(100.0, max(0.0, score)), 1)
        level = "urgent" if score >= 75 else "high" if score >= 55 else "normal" if score >= 30 else "low"
        if customer.conversation_ids and customer.last_contact_at and (
            customer.requirement_count or customer.quote_count or customer.confirmed_sales_stage
        ):
            sufficiency = "high"
        elif customer.conversation_ids or customer.last_contact_at:
            sufficiency = "medium"
        else:
            sufficiency = "low"
        results.append(
            PredictionResult(
                id=_result_id("customer_followup_priority", customer.id),
                target="customer_followup_priority",
                entity_type="customer",
                entity_id=customer.id,
                entity_label=customer.label,
                horizon="1d",
                horizon_days=1,
                generated_at=bundle.generated_at,
                horizon_start=bundle.generated_at,
                horizon_end=bundle.generated_at + timedelta(days=1),
                score=score,
                risk_level=level,  # type: ignore[arg-type]
                data_sufficiency=sufficiency,  # type: ignore[arg-type]
                method="followup_priority_rules_v1",
                model_version=MODEL_VERSION,
                summary=(
                    f"今日跟进优先级 {score:g}/100，"
                    f"等级为{PredictionExplanationService.risk_label(level)}。"
                ),
                drivers=sorted(
                    drivers,
                    key=lambda row: (row.impact or 0, row.code),
                    reverse=True,
                ),
                facts=[
                    PredictionFact(
                        key="unread_count",
                        label="未读消息",
                        value=customer.unread_count,
                        unit="messages",
                        evidence_ref=f"customer:{customer.id}.unread_count",
                    ),
                    PredictionFact(
                        key="inbound_24h",
                        label="24 小时客户消息",
                        value=customer.inbound_24h,
                        unit="messages",
                        evidence_ref=f"customer:{customer.id}.message_activity",
                    ),
                    PredictionFact(
                        key="requirement_count",
                        label="需求案例",
                        value=customer.requirement_count,
                        unit="cases",
                        evidence_ref=f"customer:{customer.id}.requirement_cases",
                    ),
                ],
                evidence_refs=sorted(
                    {
                        evidence
                        for driver in drivers
                        for evidence in driver.evidence_refs
                    }
                ),
            )
        )
    results.sort(key=lambda row: (row.score or 0, row.entity_id or ""), reverse=True)
    return results


def build_all_predictions(bundle: FeatureBundle) -> list[PredictionResult]:
    return [
        workload_prediction(bundle),
        *project_delay_predictions(bundle),
        cashflow_prediction(bundle),
        *customer_priority_predictions(bundle),
    ]
