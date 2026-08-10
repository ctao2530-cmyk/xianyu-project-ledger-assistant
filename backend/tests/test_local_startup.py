from __future__ import annotations

import os

from scripts.integration import start_local


def test_configure_runtime_proxy_replaces_stale_inherited_proxy(monkeypatch) -> None:
    stale = "http://127.0.0.1:7888"
    current = "http://127.0.0.1:7892"
    monkeypatch.setenv("HTTPS_PROXY", stale)
    monkeypatch.setenv("NO_PROXY", "example.test")
    monkeypatch.setattr(
        start_local,
        "_proxy_is_reachable",
        lambda value, **_kwargs: value == current,
    )
    monkeypatch.setattr(start_local, "_system_https_proxy", lambda: current)

    assert start_local.configure_runtime_proxy() == current
    for key in start_local.PROXY_ENV_KEYS:
        assert os.environ[key] == current
    assert os.environ["NO_PROXY"] == "example.test,127.0.0.1,localhost"


def test_configure_runtime_proxy_keeps_reachable_inherited_proxy(monkeypatch) -> None:
    inherited = "http://127.0.0.1:7892"
    monkeypatch.setenv("HTTPS_PROXY", inherited)
    monkeypatch.setattr(
        start_local,
        "_proxy_is_reachable",
        lambda value, **_kwargs: value == inherited,
    )
    monkeypatch.setattr(
        start_local,
        "_system_https_proxy",
        lambda: (_ for _ in ()).throw(AssertionError("system proxy not needed")),
    )

    assert start_local.configure_runtime_proxy() == inherited


def test_configure_runtime_proxy_drops_unreachable_proxy_without_fallback(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7888")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7888")
    monkeypatch.setattr(start_local, "_proxy_is_reachable", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(start_local, "_system_https_proxy", lambda: None)

    assert start_local.configure_runtime_proxy() is None
    assert "HTTPS_PROXY" not in os.environ
    assert "HTTP_PROXY" not in os.environ
