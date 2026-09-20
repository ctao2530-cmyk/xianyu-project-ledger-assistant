"""Fictional recording fixtures. Never import or seed the operator's database."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from copy import deepcopy
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .ledger import default_snapshot
from .models import (
    Conversation, CustomerChannelIdentity, Item, Message, ProductDailySnapshot,
    ProductMonitor, RequirementCase, RequirementCaseSource, RequirementDocumentVersion,
)
from .requirement_blueprints import RequirementBlueprintV2
from .services.project_acceptance import ProjectAcceptanceService

DEMO_MARKER = "xunying-fictional-recording-v1"
BEIJING = ZoneInfo("Asia/Shanghai")


def demo_snapshot(today: date) -> dict:
    """Dates follow the recording month; amounts and object links are deterministic."""
    snapshot = default_snapshot()
    first = today.replace(day=1)
    previous = first - timedelta(days=1)

    def day(offset: int) -> str:
        return (today + timedelta(days=offset)).isoformat()

    def paid_day(index: int, prior: bool = False) -> str:
        month = previous if prior else today
        return month.replace(day=min(index, month.day)).isoformat() + "T10:00:00+08:00"

    # name, type, contract, status, completed task count, due offset, payments
    specs = [
        ("云栖预约小程序", "小程序开发", 18000, "in_progress", 4, 7, [(5400, 8, True), (7200, 8, False)]),
        ("青禾品牌官网", "企业官网", 9600, "completed", 6, -5, [(4800, 3, False), (4800, 15, False)]),
        ("星桥进销存系统", "管理系统", 24000, "in_progress", 2, 18, [(7200, 6, False)]),
        ("拾光活动 H5", "活动页面", 6800, "completed", 6, -25, [(6800, 20, True)]),
        ("山海经营数据看板", "数据可视化", 15000, "delivered", 6, 2, [(4500, 10, False)]),
        ("橙子会员管理系统", "管理系统", 12000, "pending", 0, 28, [(3600, 18, False)]),
    ]
    names = ["云栖工作室", "青禾品牌", "星桥商贸", "拾光策划", "山海运营团队", "橙子门店"]
    next_steps = ["完成移动端适配与联调", "已验收，整理交付归档", "优先完成库存出入库校验", "已验收并结清", "等待客户验收后跟进尾款", "开工前确认会员等级规则"]
    task_names = ["需求与原型确认", "页面与组件实现", "核心业务接口", "权限与异常处理", "移动端与联调测试", "交付文档与验收"]
    for index, (name, kind, contract, status, done, due, receipts) in enumerate(specs, 1):
        customer_id, project_id = f"demo-customer-{index}", f"demo-project-{index}"
        snapshot["customers"].append({
            "id": customer_id, "name": names[index - 1], "source": "xianyu", "phone": "",
            "followUpStatus": "won", "lastContactAt": day(-1), "level": "A" if index in (1, 3, 5) else "B",
            "tags": ["演示数据", kind], "currentNeed": name, "nextAction": next_steps[index - 1],
            "notes": "完全虚构的录屏演示客户，不对应真实联系人。",
            "channelIdentities": [{"channel": "xianyu", "externalCustomerId": f"demo-channel-{index}", "conversationId": index}],
        })
        snapshot["projects"].append({
            "id": project_id, "name": name, "customerId": customer_id, "totalAmount": contract,
            "startDate": day(-40 if index == 4 else -18), "dueDate": day(due),
            "progress": round(done / 6 * 100), "progressSource": "task_completion",
            "status": status, "type": kind, "projectKind": "client", "estimatedHours": 48 + index * 8,
            "accent": ["blue", "green", "purple", "orange"][(index - 1) % 4],
            "notes": next_steps[index - 1] + "。任务完成、客户验收与回款分别记录。此项目为演示数据。",
            "conversationId": index, "itemExternalId": f"demo-service-{index}",
        })
        for task_index, title in enumerate(task_names, 1):
            snapshot["tasks"].append({
                "id": f"demo-task-{index}-{task_index}", "projectId": project_id, "title": title,
                "status": "done" if task_index <= done else "in_progress" if task_index == done + 1 and status == "in_progress" else "todo",
                "startDate": day(-18 + task_index), "dueDate": day(due - 6 + task_index),
                "estimatedHours": 8 + index, "actualHours": 7 + index if task_index <= done else 0,
                "notes": "演示任务；完成情况不代表客户验收。",
            })
        for receipt_index, (amount, day_number, prior) in enumerate(receipts, 1):
            snapshot["payments"].append({
                "id": f"demo-receipt-{index}-{receipt_index}", "projectId": project_id,
                "customerId": customer_id, "amount": amount, "status": "confirmed",
                "type": "full" if amount == contract else "deposit" if receipt_index == 1 else "milestone",
                "paidAt": paid_day(day_number, prior), "dueAt": paid_day(day_number, prior)[:10],
                "notes": "演示到账记录，非真实收入。",
            })
        outstanding = contract - sum(row[0] for row in receipts)
        if outstanding:
            snapshot["payments"].append({
                "id": f"demo-balance-{index}", "projectId": project_id, "customerId": customer_id,
                "amount": outstanding, "status": "pending", "type": "final",
                "paidAt": day(due) + "T10:00:00+08:00", "dueAt": day(due),
                "notes": "验收后支付尾款；演示数据。",
            })
        snapshot["logs"].append({"id": f"demo-log-{index}", "projectId": project_id,
            "createdAt": day(-1) + "T10:00:00+08:00", "content": next_steps[index - 1], "hours": 2, "category": "development"})

    costs = [
        ("服务器与数据库", "server", 680, 1, 2, False),
        ("AI 接口与开发工具", "software", 420, None, 5, False),
        ("品牌视觉设计协作", "outsourcing", 1800, 2, 9, False),
        ("系统联调与测试协作", "outsourcing", 1200, 3, 16, False),
        ("域名与素材授权", "other", 400, 5, 18, False),
        ("上月开发工具", "software", 300, None, 5, True),
        ("活动页面视觉素材", "other", 1200, 4, 15, True),
    ]
    for index, (name, category, amount, project, day_number, prior) in enumerate(costs, 1):
        snapshot["expenses"].append({"id": f"demo-expense-{index}", "name": name,
            "category": category, "amount": amount, "projectId": f"demo-project-{project}" if project else None,
            "paidAt": paid_day(day_number, prior), "notes": "演示支出，非真实费用。"})
    snapshot["settings"].update(profileName="循营演示经营者", monthlyIncomeGoal=35000,
        profileRole="独立开发者 · 演示空间", profileBio="用于演示客户接单、项目交付、回款与 AI 经营分析。",
        xianyuStartedAt=previous.replace(day=1).isoformat(), autoBackupEnabled=False)
    snapshot["completedOrderCount"] = 2
    return snapshot


def blueprint(project: dict, conversation_id: int) -> dict:
    return RequirementBlueprintV2.model_validate({
        "title": project["name"] + "需求与交付说明", "project_type": project["type"],
        "readiness": "approved", "change_summary": "录屏演示用正式需求示例，全部内容均为虚构。",
        "objectives": [{"id": "goal-main", "title": "完成可验收的业务闭环", "description": project["name"] + "需要覆盖日常操作、记录查询与交付验收。", "evidence_refs": ["evidence-demo"]}],
        "capabilities": [
            {"id": "cap-flow", "title": "核心业务流程", "description": "支持核心记录创建、状态更新、查询与筛选。", "objective_ids": ["goal-main"]},
            {"id": "cap-access", "title": "权限与异常处理", "description": "校验必填字段、权限边界，并明确展示失败状态。", "objective_ids": ["goal-main"]},
            {"id": "cap-delivery", "title": "移动适配与交付", "description": "桌面与手机均能完成主要流程，提供交付说明。", "objective_ids": ["goal-main"]},
        ],
        "stages": [
            {"id": "stage-build", "task_key": "DEMO-BUILD", "title": "功能实现", "objective": "完成主要业务流程", "implementation": "按已确认原型实现页面、接口、校验与查询。", "estimated_hours": 32, "capability_ids": ["cap-flow", "cap-access"], "work_items": ["实现核心页面", "实现业务接口与校验"], "deliverables": ["可运行应用", "接口与异常说明"], "process_tests": ["关键流程正常与失败分支测试"]},
            {"id": "stage-delivery", "task_key": "DEMO-DELIVERY", "title": "联调与验收", "objective": "验证完整流程并交付", "implementation": "完成响应式检查、业务联调和客户验收记录。", "estimated_hours": 16, "capability_ids": ["cap-delivery"], "dependency_ids": ["stage-build"], "work_items": ["响应式检查", "交付文档整理"], "deliverables": ["验收清单", "使用说明"]},
        ],
        "acceptance_gates": [{"id": "gate-flow", "title": "主要流程验收", "description": "按确认需求逐项核对。", "stage_ids": ["stage-build", "stage-delivery"], "criteria": ["核心流程可完成且数据保存正确", "390px 与桌面主要内容可读", "权限和错误提示符合预期", "客户验收结果另行记录"]}],
        "out_of_scope": ["真实支付接入", "真实客户消息发送"],
        "assumptions": ["所有业务对象和证据均来自独立演示数据库。"],
        "evidence_refs": [{"id": "evidence-demo", "conversation_id": conversation_id, "message_number": 1, "quote": "希望把核心业务流程、状态查询和交付验收串起来，手机也能使用。"}],
    }).model_dump(mode="json")


def seed_demo(runtime, root: Path, today: date | None = None) -> dict:
    root = root.resolve()
    expected = root / "data" / "demo.sqlite3"
    if runtime.database.engine.url.database != str(expected) or (root / ".demo-only").read_text() != DEMO_MARKER:
        raise ValueError("Demo seed refused: database is not the marked isolated demo database")
    manifest = root / "manifest.json"
    if manifest.exists():
        return json.loads(manifest.read_text())
    revision, existing = runtime.ledger.get()
    if revision or any(existing[key] for key in ("projects", "customers", "payments", "expenses")):
        raise ValueError("Demo seed refuses to overwrite existing records")
    today = today or datetime.now(BEIJING).date()
    snapshot = demo_snapshot(today)
    with runtime.database.session() as session:
        for index, project in enumerate(snapshot["projects"], 1):
            item = Item(id=index, external_id=f"demo-service-{index}", title=project["type"] + "定制服务", price=str(project["totalAmount"]), description="虚构的服务商品，仅供录屏演示。", raw_json="{}")
            session.add(item)
            session.flush()
            session.add(ProductMonitor(item_id=index, enabled=True, ownership_status="owned", ownership_source="fictional_demo", source="fictional_demo", last_collection_status="success"))
            session.add(Conversation(id=index, external_id=f"demo-conversation-{index}", customer_id=f"demo-channel-{index}", customer_name=snapshot["customers"][index - 1]["name"], item_id=index, unread_count=2 if index in (1, 3, 5) else 0, last_message_at=datetime.combine(today, datetime.min.time(), BEIJING).astimezone(timezone.utc)))
            session.flush()
            texts = ["希望把核心业务流程、状态查询和交付验收串起来，手机也能使用。", "收到，我们按需求确认、开发联调、交付验收三个步骤推进。", project["notes"].split("。")[0] + "，后续按验收结果安排尾款。"]
            for message_index, content in enumerate(texts, 1):
                inbound = message_index != 2
                session.add(Message(external_id=f"demo-message-{index}-{message_index}", platform_message_id=f"demo-platform-{index}-{message_index}", conversation_id=index, sender_id=f"demo-channel-{index}" if inbound else "demo-operator", sender_name=snapshot["customers"][index - 1]["name"] if inbound else "演示经营者", direction="inbound" if inbound else "outbound", content=content, status="new" if inbound else "sent", received_at=datetime.combine(today - timedelta(days=3 - message_index), datetime.min.time(), BEIJING).astimezone(timezone.utc), source_item_external_id=item.external_id))
            for offset in range(14):
                recorded = today - timedelta(days=13 - offset)
                earned = sum(row["amount"] for row in snapshot["payments"] if row["projectId"] == project["id"] and row["status"] == "confirmed" and row["paidAt"][:10] <= recorded.isoformat())
                spent = sum(row["amount"] for row in snapshot["expenses"] if row.get("projectId") == project["id"] and row["paidAt"][:10] <= recorded.isoformat())
                session.add(ProductDailySnapshot(item_id=index, snapshot_date=recorded.isoformat(), source="fictional_demo", title=item.title, price=project["totalAmount"], status="onsale", raw_browse_count=90 + index * 20 + offset * (7 + index), browse_count=90 + index * 20 + offset * (7 + index), collection_views_excluded=0, inquiry_count=2 + offset // 3, want_count=offset // 4, converted_project_count=1, revenue_total=earned, profit_total=earned-spent, captured_at=datetime.combine(recorded, datetime.min.time(), BEIJING).astimezone(timezone.utc)))
        session.commit()
    with runtime.database.session() as session:
        # Flush parent rows first: ledger models intentionally use scalar FKs
        # rather than ORM relationships for their canonical snapshot projection.
        parents = deepcopy(snapshot)
        for key in ("projects", "tasks", "payments", "expenses", "logs"):
            parents[key] = []
        runtime.ledger.save_in_session(session, parents, revision, trusted_delivery_sync=True, trusted_task_trace_sync=True)
        parents["projects"] = snapshot["projects"]
        runtime.ledger.save_in_session(session, parents, revision + 1, trusted_delivery_sync=True, trusted_task_trace_sync=True)
        runtime.ledger.save_in_session(session, snapshot, revision + 2, trusted_delivery_sync=True, trusted_task_trace_sync=True)
        session.commit()
    with runtime.database.session() as session:
        for index, project in enumerate(snapshot["projects"], 1):
            session.add(CustomerChannelIdentity(id=f"demo-identity-{index}", customer_id=project["customerId"], channel="xianyu", external_customer_id=f"demo-channel-{index}", display_name=snapshot["customers"][index - 1]["name"], conversation_id=index))
            case_id = f"demo-case-{index}"
            session.add(RequirementCase(id=case_id, customer_id=project["customerId"], item_id=index, title=project["name"], status="approved", current_version=1, project_id=project["id"]))
            session.flush()
            session.add(RequirementCaseSource(id=f"demo-case-source-{index}", case_id=case_id, conversation_id=index))
            content = blueprint(project, index)
            version = RequirementDocumentVersion(case_id=case_id, project_id=project["id"], conversation_id=index, schema_version="2.0", source_type="manual", source_label="虚构演示需求", version=1, title=content["title"], readiness="approved", change_summary=content["change_summary"], structured_json=json.dumps(content, ensure_ascii=False), content_markdown="# " + content["title"] + "\n\n演示数据，非真实客户需求。", model="demo-manual")
            session.add(version)
        session.commit()
    for index in (2, 4):
        revision, _ = runtime.ledger.get()
        ProjectAcceptanceService(runtime.database, runtime.ledger).record(f"demo-project-{index}", {"request_id": f"demo-acceptance-{index}", "expected_revision": revision, "case_id": f"demo-case-{index}", "version": 1, "decision": "accepted", "reviewer": "演示客户代表", "evidence": "虚构验收记录：主要流程与交付文档已核对。", "confirmed": True})
    result = {"fixture": DEMO_MARKER, "seed_date": today.isoformat(), "fictional": True,
        "project_count": 6, "customer_count": 6, "task_count": 36, "product_count": 6,
        "expected": {"contract_total": 85400, "confirmed_receipts": 44300, "expenses": 6000,
            "actual_profit": 38300, "outstanding_receivables": 41100,
            "month_income": 32100, "month_expenses": 4500, "month_net": 27600,
            "previous_month_income": 12200, "previous_month_expenses": 1500}}
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result
