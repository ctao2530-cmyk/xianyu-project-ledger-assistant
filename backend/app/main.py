from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .project_acceptance_api import acceptance_router
from .maintenance_api import maintenance_router
from .workbench_api import workbench_router
from .api import router
from .business_analysis_api import business_analysis_router
from .customer_image_api import customer_image_router
from .customer_analysis_api import customer_analysis_router
from .customer_context_api import customer_context_router
from .customer_conversation_api import customer_conversation_router
from .customer_context_mcp import bridge as customer_context_mcp_bridge
from .customer_context_mcp import customer_context_mcp_app
from .config import get_settings
from .codex_plan_api import codex_plan_router
from .codex_sync_api import codex_sync_router
from .codex_runtime_api import codex_runtime_router
from .codex_verification_api import codex_verification_router
from .customer_relationship_api import customer_relationship_router
from .customer_intake_api import customer_intake_router
from .events import event_router
from .ledger_api import ledger_router
from .global_agent_api import global_agent_router
from .logging_config import configure_logging
from .product_api import product_router
from .prediction_api import prediction_router
from .phrase_library_api import phrase_library_router
from .project_product_api import project_product_router
from .project_task_draft_api import project_task_draft_router
from .requirement_proposal_api import requirement_proposal_router
from .runtime import build_runtime
from .services.customer_context_oauth import (
    CustomerContextOAuthConfig,
    CustomerContextOAuthVerifier,
)
from .services.customer_context_tunnel import CustomerContextTunnelConfig
from .sales_api import sales_router
from .traffic_growth_api import traffic_growth_router
from .wechat_api import wechat_router


settings = get_settings()
configure_logging(
    settings.log_level,
    secrets=(
        settings.xianyu_cookie.get_secret_value(),
        settings.ai_api_key.get_secret_value(),
        settings.openai_api_key.get_secret_value(),
        settings.deepseek_api_key.get_secret_value(),
        settings.wecom_corp_secret.get_secret_value(),
        settings.wecom_callback_token.get_secret_value(),
        settings.wecom_encoding_aes_key.get_secret_value(),
        settings.xunying_codex_event_secret.get_secret_value(),
        settings.customer_context_tunnel_secret.get_secret_value(),
    ),
    file_path=settings.log_file,
    max_bytes=settings.log_max_bytes,
    backup_count=settings.log_backup_count,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = build_runtime(settings)
    app.state.runtime = runtime
    oauth_config = CustomerContextOAuthConfig.from_settings(settings)
    oauth_verifier = CustomerContextOAuthVerifier(oauth_config)
    tunnel_config = CustomerContextTunnelConfig.from_settings(settings)
    app.state.customer_context_oauth_config = oauth_config
    app.state.customer_context_tunnel_config = tunnel_config
    customer_context_mcp_bridge.bind(
        runtime.customer_context_reader,
        runtime.customer_context_gateway,
        oauth_config,
        oauth_verifier,
        tunnel_config,
    )
    mcp_lifespan = customer_context_mcp_app.router.lifespan_context(
        customer_context_mcp_app
    )
    await mcp_lifespan.__aenter__()
    await runtime.ai_queue.start()
    runtime.customer_images.start(runtime.processor.media_fetchers, runtime.event_hub)
    await runtime.customer_auto_analysis.start()
    await runtime.requirements.start()
    await runtime.product_intelligence.start()
    await runtime.listener_supervisor.start()
    await runtime.codex_development.start()
    # WeCom credential validation uses an external API and must never delay or
    # prevent the existing Xianyu listener from starting.
    wecom_health_task = asyncio.create_task(runtime.wecom.start())

    async def check_ai_environment() -> None:
        health = await runtime.ai.healthcheck()
        if runtime.settings.deepseek_configured:
            await runtime.deepseek.healthcheck()
        if health.status != "connected":
            repair = f"；修复命令：{health.repair_command}" if health.repair_command else ""
            await runtime.notifier.notify(
                "闲鱼助手：AI 环境异常",
                f"{health.detail or 'Codex 无法使用'}{repair}",
                "闲鱼消息仍会继续保存",
            )

    health_task = asyncio.create_task(check_ai_environment())
    try:
        yield
    finally:
        for task in (health_task, wecom_health_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await runtime.listener_supervisor.shutdown()
        await runtime.customer_images.stop()
        await runtime.wecom.stop()
        await runtime.requirements.stop()
        await runtime.sales_agent.stop()
        await runtime.ai_queue.stop()
        await runtime.customer_auto_analysis.close()
        await runtime.product_intelligence.stop()
        await runtime.global_agent.shutdown()
        await runtime.codex_development.close()
        await oauth_verifier.close()
        await mcp_lifespan.__aexit__(None, None, None)


app = FastAPI(
    title="闲鱼智能客服助手",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "X-Yuda-Desktop",
        "X-Xunying-Timestamp",
        "X-Xunying-Signature",
    ],
)


@app.get("/.well-known/oauth-protected-resource/mcp/customer-context")
@app.get("/.well-known/oauth-protected-resource")
async def customer_context_protected_resource_metadata(request: Request):
    tunnel_config = getattr(request.app.state, "customer_context_tunnel_config", None)
    if tunnel_config is None:
        tunnel_config = CustomerContextTunnelConfig.from_settings(settings)
    if tunnel_config.enabled:
        return JSONResponse(
            status_code=404,
            content={
                "code": "oauth_discovery_disabled",
                "message": "当前使用 Secure MCP Tunnel 本地绑定模式",
            },
        )
    oauth_config = getattr(request.app.state, "customer_context_oauth_config", None)
    if oauth_config is None:
        oauth_config = CustomerContextOAuthConfig.from_settings(settings)
    if not oauth_config.enabled:
        return JSONResponse(
            status_code=503,
            content={
                "code": "oauth_not_configured",
                "message": "循营客户上下文 OAuth 尚未配置",
            },
        )
    return JSONResponse(
        content=oauth_config.protected_resource_metadata(),
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if (
        request.method != "OPTIONS"
        and (
            request.url.path.startswith("/api/")
            or request.url.path.startswith("/wechat/")
        )
        and hasattr(request.app.state, "runtime")
    ):
        runtime = request.app.state.runtime
        client = request.client.host if request.client else "local"
        key = f"{client}:{request.method}:{request.url.path}"
        if not await runtime.api_limiter.allow(key):
            return JSONResponse(
                status_code=429,
                content={"detail": "页面请求过于频繁，请稍后重试"},
                headers={"Retry-After": "5"},
            )
    response = await call_next(request)
    if (
        request.method == "GET"
        and not request.url.path.startswith(("/api/", "/events", "/wechat/"))
    ):
        # This is a single-user local application. Always revalidate the shell
        # and hashed assets so Edge and the in-app browser cannot keep serving a
        # previous build after the persistent service restarts.
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.include_router(acceptance_router)
app.include_router(maintenance_router)
app.include_router(workbench_router)
app.include_router(router)
app.include_router(codex_plan_router)
app.include_router(codex_sync_router)
app.include_router(codex_runtime_router)
app.include_router(codex_verification_router)
app.include_router(business_analysis_router)
app.include_router(customer_relationship_router)
app.include_router(customer_intake_router)
app.include_router(ledger_router)
app.include_router(product_router)
app.include_router(traffic_growth_router)
app.include_router(prediction_router)
app.include_router(project_product_router)
app.include_router(project_task_draft_router)
app.include_router(requirement_proposal_router)
app.include_router(sales_router)
app.include_router(event_router)
app.include_router(wechat_router)
app.include_router(customer_image_router)
app.include_router(customer_analysis_router)
app.include_router(customer_context_router)
app.include_router(customer_conversation_router)
app.include_router(global_agent_router)
app.include_router(phrase_library_router)
app.mount(
    "/mcp/customer-context",
    customer_context_mcp_app,
    name="customer-context-mcp",
)

# Local production uses one 127.0.0.1 origin. Hash routing keeps all frontend
# navigation in index.html, while API and callback routes above remain FastAPI.
client_dist = settings.project_root / "dist" / "client"
if client_dist.is_dir():
    app.mount("/", StaticFiles(directory=client_dist, html=True), name="client")
