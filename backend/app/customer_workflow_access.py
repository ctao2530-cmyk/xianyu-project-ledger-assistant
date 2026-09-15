"""Local web workflow is not an alternate unauthenticated remote image API."""
from fastapi import HTTPException, Request


def local_customer_workflow(request: Request) -> None:
    peer = request.client.host if request.client else ""
    host = request.url.hostname or ""
    loopback = {"127.0.0.1", "localhost", "::1"}
    test_client = peer == "testclient" and host in loopback | {"testserver"}
    forwarded = any(request.headers.get(name) for name in (
        "forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip"))
    if forwarded or (not test_client and (peer not in loopback or host not in loopback)):
        raise HTTPException(403, detail={"code": "local_customer_workflow_only",
            "message": "网页图片和会话组接口仅允许本机使用；外部读取须使用已授权的MCP工具"})
