from __future__ import annotations

import base64
import importlib.util
import stat
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "configure_wecom.py"
SPEC = importlib.util.spec_from_file_location("root_configure_wecom", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
configure_wecom = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configure_wecom)


def test_generated_callback_values_match_wecom_format() -> None:
    token = configure_wecom.generated_token()
    aes_key = configure_wecom.generated_aes_key()

    assert len(token) == 32
    assert token.isalnum()
    assert len(aes_key) == 43
    assert aes_key.isalnum()
    assert len(base64.b64decode(aes_key + "=")) == 32


def test_configure_wecom_updates_env_atomically_without_removing_other_values(
    tmp_path, monkeypatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("XIANYU_COOKIE=keep-me\nWECHAT_PROVIDER=mock\n", encoding="utf-8")
    monkeypatch.setattr(configure_wecom, "ENV_PATH", env_path)
    lines, _values = configure_wecom.parse_env(env_path)
    updates = {
        "WECHAT_PROVIDER": "wecom",
        "WECOM_CORP_ID": "ww-corp",
        "WECOM_CORP_SECRET": "secret-value",
        "WECOM_CALLBACK_TOKEN": "T" * 32,
        "WECOM_ENCODING_AES_KEY": "A" * 43,
        "WECOM_API_BASE_URL": "https://qyapi.weixin.qq.com",
        "WECOM_REQUEST_TIMEOUT_SECONDS": "15",
        "WECOM_SYNC_MAX_PAGES": "10",
    }

    configure_wecom.update_env(lines, updates)

    _updated_lines, values = configure_wecom.parse_env(env_path)
    assert values["XIANYU_COOKIE"] == "keep-me"
    assert values["WECHAT_PROVIDER"] == "wecom"
    assert values["WECOM_CORP_SECRET"] == "secret-value"
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
