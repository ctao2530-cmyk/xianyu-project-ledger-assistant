from copy import deepcopy
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from backend.app.config import Settings
from backend.app.demo import DemoOriginRouter, build_demo_runtime, create_demo_app, demo_settings
from backend.app.demo_seed import seed_demo
from backend.app.models import Message, RequirementCase


@pytest.fixture
def demo(tmp_path):
    from backend.app.api import router
    from backend.app.ledger_api import ledger_router
    from backend.app.product_api import product_router
    from backend.app.business_analysis_api import business_analysis_router
    from backend.app.global_agent_api import global_agent_router
    from backend.app.project_task_draft_api import project_task_draft_router
    from backend.app.project_acceptance_api import acceptance_router
    from backend.app.workbench_api import workbench_router
    from backend.app.customer_conversation_api import customer_conversation_router
    from backend.app.customer_image_api import customer_image_router
    from backend.app.phrase_library_api import phrase_library_router
    from backend.app.requirement_proposal_api import requirement_proposal_router
    from backend.app.codex_plan_api import codex_plan_router
    from backend.app.traffic_growth_api import traffic_growth_router
    from backend.app.prediction_api import prediction_router
    source = Settings(_env_file=None)
    root = tmp_path / "demo"
    client_dist = tmp_path / "client"
    client_dist.mkdir()
    (client_dist / "index.html").write_text("<html><head><title>循营</title></head><body><div id='root'></div></body></html>")
    host = FastAPI()
    @host.get("/api/ledger/snapshot")
    async def real():
        return {"production": True}
    routes = []
    for value in (router, ledger_router, product_router, business_analysis_router,
                  global_agent_router, project_task_draft_router, acceptance_router,
                  workbench_router, customer_conversation_router, customer_image_router, phrase_library_router,
                  requirement_proposal_router, codex_plan_router, traffic_growth_router, prediction_router):
        routes.extend(value.routes)
    app = create_demo_app(source, root, client_dist, routes)
    host.add_middleware(DemoOriginRouter, demo_app=app)
    with TestClient(host, base_url="http://demo.localhost:8877", headers={"X-Yuda-Desktop": "1"}) as client:
        yield client, app, root
    if hasattr(app.state, "runtime"):
        app.state.runtime.database.engine.dispose()


def test_fixture_is_linked_and_financially_consistent(demo):
    client, app, root = demo
    assert client.get("/").status_code == 200
    runtime = app.state.runtime
    revision, snapshot = runtime.ledger.get()
    assert len(snapshot["projects"]) == 6
    assert len(snapshot["tasks"]) == 36
    assert len(snapshot["expenses"]) == 7
    assert [row["channelIdentities"][0]["conversationId"] for row in snapshot["customers"]] == list(range(1, 7))
    assert runtime.global_agent.tools.finance_summary("")["confirmed_receipts"] == 44300
    finance = runtime.business_analysis.overview().metrics.finance
    assert runtime.business_analysis.overview().metrics.products.active_products == 6
    assert (finance.income.current, finance.expenses.current, finance.profit.current) == (32100, 4500, 27600)
    assert (finance.income.previous, finance.expenses.previous) == (12200, 1500)
    assert sum(p["amount"] for p in snapshot["payments"] if p["status"] == "pending") == 41100
    with runtime.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 18
        assert session.scalar(select(func.count()).select_from(RequirementCase)) == 6
    seed_demo(runtime, root)
    assert runtime.ledger.get() == (revision, snapshot)
    runtime.database.engine.dispose()
    reopened = build_demo_runtime(runtime.settings, root)
    assert reopened.ledger.get() == (revision, snapshot)
    reopened.database.engine.dispose()


def test_secrets_and_paths_cannot_leak_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("XIANyu_COOKIE", "secret-sentinel")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-sentinel")
    monkeypatch.setenv("GLOBAL_AGENT_VAULT_ROOT", "/private/real-vault")
    source = Settings(_env_file=None, xianyu_cookie=SecretStr("source-secret"))
    root = tmp_path / "demo"
    settings = demo_settings(source, root)
    assert not settings.xianyu_cookie.get_secret_value()
    assert not settings.openai_api_key.get_secret_value()
    assert not settings.deepseek_api_key.get_secret_value()
    assert settings.project_root == root
    assert settings.global_agent_vault_root == str(root / "empty-knowledge")
    assert not settings.product_collection_enabled
    assert not settings.customer_analysis_enabled
    assert not settings.auto_reply_feature_enabled


@pytest.mark.parametrize("path", [
    "/api/ledger/snapshot", "/api/workbench/actions", "/api/conversations",
    "/api/conversations/1/messages?before_message_id=3", "/api/customers/demo-customer-1/requirements",
    "/api/requirement-cases/demo-case-1", "/api/projects/demo-project-1/requirement-blueprints",
    "/api/projects/demo-project-2/acceptance", "/api/products/intelligence",
    "/api/business-analysis/overview", "/api/global-agent/bootstrap",
    "/api/customers/demo-customer-1/requirement-proposals",
    "/api/customers/demo-customer-1/conversation-group-candidates",
    "/api/requirement-cases/demo-case-1/codex-bindings", "/api/requirement-cases/demo-case-1/codex-plan",
    "/api/products/traffic-growth", "/api/ai/providers",
    "/api/predictions", "/api/predictions/calibration",
])
def test_existing_business_handlers_use_demo_runtime(demo, path):
    client, _, _ = demo
    result = client.get(path)
    assert result.status_code == 200, result.text
    assert result.headers["x-xunying-environment"] == "fictional-demo"


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/messages/1/send"), ("POST", "/api/products/collect/manual"),
    ("GET", "/api/products/owned-listings/discover"), ("POST", "/api/desktop/listener/resume"),
    ("POST", "/api/customer-context/grants"), ("POST", "/api/connection-recovery/xianyu"),
    ("POST", "/api/global-agent/knowledge/reindex"), ("GET", "/api/unknown"),
])
def test_external_and_unknown_apis_fail_closed(demo, method, path):
    client, _, _ = demo
    assert client.request(method, path).status_code == 403


def test_origins_separate_ledger_and_reject_cross_origin(demo):
    client, _, _ = demo
    actual = client.get("http://127.0.0.1:8877/api/ledger/snapshot")
    assert actual.json() == {"production": True}
    assert client.get("http://127.0.0.1:8877/api/ledger/snapshot", headers={"Origin": "http://demo.localhost:8877"}).status_code == 403
    assert client.get("/api/ledger/snapshot", headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.get("/api/ledger/snapshot", headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 403
    page = client.get("/")
    assert "全部业务数据为虚构" in page.text
    assert "connect-src 'self'" in page.headers["content-security-policy"]


def test_demo_write_uses_revision_guard_and_does_not_reach_production(demo):
    client, _, _ = demo
    before = client.get("/api/ledger/snapshot").json()
    changed = deepcopy(before["snapshot"])
    changed["expenses"][0]["amount"] = 780
    payload = {"expected_revision": before["revision"], "snapshot": changed}
    response = client.put("/api/ledger/snapshot", json=payload, headers={"Origin": "http://demo.localhost:8877"})
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == before["revision"] + 1
    assert sum(row["amount"] for row in response.json()["snapshot"]["expenses"]) == 6100
    assert client.put("/api/ledger/snapshot", json=payload).status_code == 409
    assert client.get("http://127.0.0.1:8877/api/ledger/snapshot").json() == {"production": True}


def test_month_question_reads_monthly_evidence(demo):
    client, app, _ = demo
    client.get("/")
    tools = app.state.runtime.global_agent.tools
    planned = tools.plan("请总结我本月的收入、支出、净额和待回款情况。", maximum=5)
    assert [name for name, _ in planned] == ["finance_summary", "business_analysis"]
    result = tools.business_analysis("")
    assert result["metrics"]["finance"]["income"]["current"] == 32100
    assert result["period"]["timezone"] == "Asia/Shanghai"


def test_project_summary_wording_is_not_used_as_a_project_name(demo):
    client, app, _ = demo
    client.get("/")
    tools = app.state.runtime.global_agent.tools
    question = "我现在有哪些项目？哪些正在开发、等待验收、已经完成、尚未启动？接下来优先做什么？请用项目名称和具体事实说明，任务完成不等于客户验收。"
    planned = dict(tools.plan(question, maximum=5))
    assert planned["project_summary"] == {"query": ""}
    assert tools.project_summary(planned["project_summary"]["query"])["returned_count"] == 6
    assert tools._query_hint('查看项目「云栖预约小程序」', ("项目",)) == "云栖预约小程序"
    assert tools._query_hint('查看项目：云栖预约小程序', ("项目",)) == "云栖预约小程序"
    assert tools.project_summary("不存在的项目")["returned_count"] == 0


def test_refuses_unmarked_or_non_demo_database(demo, tmp_path):
    client, app, root = demo
    client.get("/")
    unmarked = tmp_path / "real"
    unmarked.mkdir()
    (unmarked / "real.sqlite3").write_text("do not touch")
    with pytest.raises(ValueError):
        build_demo_runtime(app.state.runtime.settings, unmarked)
    with pytest.raises(ValueError):
        seed_demo(app.state.runtime, unmarked)
    assert (unmarked / "real.sqlite3").read_text() == "do not touch"
