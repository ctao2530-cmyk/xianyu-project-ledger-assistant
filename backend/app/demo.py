"""Local recording environment, served by the existing process on a separate origin.

Only demo.localhost is dispatched here. No listeners, collectors or subscriptions
are started. APIs are an explicit allowlist of existing local business handlers.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers

from .config import Settings
from .demo_seed import DEMO_MARKER, seed_demo
from .runtime import build_runtime

DEMO_HOST = "demo.localhost"


class DemoSettings(Settings):
    demo_root: Path

    @property
    def project_root(self) -> Path:
        return self.demo_root


def demo_settings(source: Settings, root: Path) -> DemoSettings:
    # Explicit values override BOTH .env and inherited process environment.
    values = {name: deepcopy(field.get_default(call_default_factory=True))
              for name, field in Settings.model_fields.items()}
    for name in ("codex_command", "codex_model", "codex_reasoning_effort",
                 "codex_timeout_seconds", "reply_balanced_model",
                 "reply_balanced_reasoning_effort", "global_agent_timeout_seconds"):
        values[name] = getattr(source, name)
    values.update(
        demo_root=root, database_url=f"sqlite:///{root / 'data' / 'demo.sqlite3'}",
        global_agent_vault_root=str(root / "empty-knowledge"),
        xunying_codex_worktree_root=str(root / "worktrees"),
        xianyu_session_cache_path=str(root / "session-cache.json"),
        product_collection_enabled=False, customer_analysis_enabled=False,
        sales_agent_enabled=False, style_learning_enabled=False,
        auto_reply_feature_enabled=False, macos_notifications=False,
        log_file=str(root / "demo.log"),
    )
    return DemoSettings(_env_file=None, **values)


def build_demo_runtime(source: Settings, root: Path):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ".demo-only"
    if not marker.exists():
        if any(root.iterdir()):
            raise ValueError("Demo root must be empty or already marked")
        marker.write_text(DEMO_MARKER)
    if marker.read_text() != DEMO_MARKER:
        raise ValueError("Invalid demo root marker")
    (root / "data").mkdir(exist_ok=True)
    runtime = build_runtime(demo_settings(source, root))
    seed_demo(runtime, root)
    runtime.product_intelligence.bootstrap_cached_state()
    runtime.product_intelligence._maintain_daily_plans()
    return runtime


# Paths are route templates, not broad URL prefixes. New application APIs do
# not automatically become available to the recording environment.
READ_PATHS = {
    "/api/health", "/api/status", "/api/ai/providers", "/api/ai/models", "/api/ledger/snapshot", "/api/operations/summary",
    "/api/predictions", "/api/predictions/calibration",
    "/api/workbench/actions", "/api/conversations", "/api/conversations/{conversation_id}",
    "/api/conversations/{conversation_id}/messages", "/api/conversations/{conversation_id}/requirements",
    "/api/requirements/versions/{version_id}", "/api/conversations/{conversation_id}/lead",
    "/api/customers/{customer_id}/requirements", "/api/requirement-cases/{case_id}",
    "/api/customers/{customer_id}/requirement-proposals",
    "/api/requirement-cases/{case_id}/codex-bindings", "/api/requirement-cases/{case_id}/codex-plan",
    "/api/projects/{project_id}/requirement-blueprints", "/api/projects/{project_id}/acceptance",
    "/api/customer-message-search", "/api/customer-message-search/context",
    "/api/customers/{customer_id}/conversation-group-candidates",
    "/api/customers/{customer_id}/conversation-groups", "/api/customer-images",
    "/api/customer-images/status", "/api/customer-images/filters", "/api/customer-images/attention",
    "/api/products/intelligence", "/api/products/market-reference", "/api/products/traffic-batches",
    "/api/products/traffic-growth",
    "/api/business-analysis", "/api/business-analysis/overview", "/api/business-analysis/history",
    "/api/business-analysis/history/{analysis_id}", "/api/business-analysis/recommendations",
    "/api/global-agent/bootstrap", "/api/global-agent/profiles", "/api/global-agent/threads",
    "/api/global-agent/customer-context-options", "/api/global-agent/threads/{thread_id}",
    "/api/global-agent/runs/{run_id}", "/api/global-agent/runs/{run_id}/trace",
    "/api/global-agent/knowledge", "/api/phrase-library",
}
WRITE_ROUTES = {
    ("POST", "/api/global-agent/threads"),
    ("POST", "/api/global-agent/threads/{thread_id}/messages"),
    ("POST", "/api/global-agent/runs/{run_id}/cancel"),
    ("DELETE", "/api/global-agent/threads/{thread_id}"),
    ("PUT", "/api/ledger/snapshot"),
    ("POST", "/api/ledger/payments/confirm"),
}


def create_demo_app(source: Settings, root: Path, client_dist: Path, routes) -> FastAPI:
    demo = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    lock = asyncio.Lock()

    async def ensure_runtime():
        async with lock:
            if not hasattr(demo.state, "runtime"):
                demo.state.runtime = build_demo_runtime(source, root)
        return demo.state.runtime

    @demo.middleware("http")
    async def demo_boundary(request: Request, call_next):
        if request.url.path in {"/api/ai/providers", "/api/ai/models"} and request.query_params.get("refresh", "false").lower() not in {"false", "0"}:
            return JSONResponse(status_code=403, content={"detail": "演示环境仅显示缓存连接状态"})
        if request.url.path.startswith("/api/"):
            runtime = await ensure_runtime()
            if (request.method == "POST" and request.url.path.startswith("/api/global-agent/threads/")
                    and request.url.path.endswith("/messages") and runtime.ai.status != "connected"):
                # Resolve the existing CLI/login on explicit use; opening the
                # recording page must not consume a model invocation.
                await runtime.ai.healthcheck(validate_execution=False)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Xunying-Environment"] = "fictional-demo"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        return response

    demo.state.ensure_runtime = ensure_runtime

    for route in routes:
        if isinstance(route, APIRoute) and any(
            (method == "GET" and route.path in READ_PATHS) or (method, route.path) in WRITE_ROUTES
            for method in route.methods
        ):
            demo.router.routes.append(route)

    @demo.get("/api/demo/manifest")
    async def manifest():
        runtime = await ensure_runtime()
        return seed_demo(runtime, root)

    # Keep websocket events isolated too; the router only subscribes to this
    # runtime's hub and never starts platform listeners.
    from .events import event_router
    demo.include_router(event_router)

    @demo.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def blocked(path: str):
        return JSONResponse(status_code=403, content={"detail": "演示环境未开放此操作；不会连接真实平台或修改真实数据。"})

    @demo.get("/")
    async def index():
        await ensure_runtime()
        page = (client_dist / "index.html").read_text()
        banner = '''<style>
        #demo-label{position:fixed;z-index:2147483647;bottom:8px;left:50%;transform:translateX(-50%);padding:5px 14px;border:1px solid #64ce9c88;border-radius:20px;background:#09271fec;color:#d7ffe9;font:12px/20px system-ui;white-space:nowrap;pointer-events:none;box-shadow:0 2px 12px #0004}
        @media(max-width:520px){#demo-label{bottom:auto;top:2px;font-size:10px;padding:0 9px}}
        </style><div id="demo-label" role="note">演示环境 · 全部业务数据为虚构</div>'''
        return HTMLResponse(page.replace("<body>", "<body>" + banner).replace("<title>", "<title>演示 · "))

    demo.mount("/", StaticFiles(directory=client_dist, html=False), name="demo-static")
    return demo


class DemoOriginRouter:
    """Host isolation before production middleware, including WebSockets.

    Normalize the already-verified loopback demo host only inside the isolated
    app, so existing local-only guards keep their original strict host checks.
    """
    def __init__(self, app, demo_app):
        self.app, self.demo_app = app, demo_app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        host = headers.get("host", "").split(":")[0]
        origin = headers.get("origin", "")
        demo_origin = urlsplit(origin).hostname == DEMO_HOST
        peer = (scope.get("client") or ("",))[0]
        is_demo = host == DEMO_HOST
        blocked = (
            (demo_origin and not is_demo)
            or (is_demo and origin and urlsplit(origin).netloc != headers.get("host"))
            or (is_demo and (peer not in {"127.0.0.1", "::1", "testclient"} or any(
                headers.get(key) for key in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip"))))
        )
        if blocked:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await JSONResponse({"detail": "演示环境仅允许本机独立来源访问"}, status_code=403)(scope, receive, send)
        if not is_demo:
            if scope["type"] == "http" and scope["path"] in {"/demo", "/demo/"}:
                port = scope.get("server", (None, 8877))[1]
                return await RedirectResponse(f"http://{DEMO_HOST}:{port}/")(scope, receive, send)
            return await self.app(scope, receive, send)
        demo_scope = dict(scope)
        demo_scope["headers"] = [(key, b"localhost" if key == b"host" else b"http://localhost" if key == b"origin" else value)
                                 for key, value in scope["headers"]]
        if scope["type"] == "websocket":
            await self.demo_app.state.ensure_runtime()
        await self.demo_app(demo_scope, receive, send)
