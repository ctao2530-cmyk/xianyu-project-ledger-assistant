#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
import secrets
import string
import subprocess
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
MANAGED_KEYS = (
    "WECHAT_PROVIDER",
    "WECOM_CORP_ID",
    "WECOM_CORP_SECRET",
    "WECOM_CALLBACK_TOKEN",
    "WECOM_ENCODING_AES_KEY",
    "WECOM_API_BASE_URL",
    "WECOM_REQUEST_TIMEOUT_SECONDS",
    "WECOM_SYNC_MAX_PAGES",
)


def parse_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return lines, values


def generated_token() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(32))


def generated_aes_key() -> str:
    # The WeChat Customer Service setup page accepts a 43-character
    # EncodingAESKey made from letters and digits.  Standard Base64 output may
    # contain "+" or "/", which is cryptographically valid but rejected by the
    # page's stricter input validation.
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(43))


def validate_value(name: str, value: str) -> str:
    value = value.strip()
    if not value or "\n" in value or "\r" in value:
        raise ValueError(f"{name} 不能为空或包含换行")
    return value


def update_env(lines: list[str], updates: dict[str, str]) -> None:
    output: list[str] = []
    replaced: set[str] = set()
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if key in updates:
            output.append(f"{key}={updates[key]}")
            replaced.add(key)
        else:
            output.append(line)
    missing = [key for key in MANAGED_KEYS if key not in replaced]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# WeCom Customer Service (managed by scripts/configure_wecom.py)")
        output.extend(f"{key}={updates[key]}" for key in missing)

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".env.wecom-", dir=ENV_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output).rstrip() + "\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, ENV_PATH)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def copy_secret(name: str) -> int:
    _lines, values = parse_env(ENV_PATH)
    key = {
        "token": "WECOM_CALLBACK_TOKEN",
        "aes-key": "WECOM_ENCODING_AES_KEY",
    }[name]
    value = values.get(key, "")
    if not value:
        print(f"{key} 尚未生成，请先运行配置向导。")
        return 1
    subprocess.run(["pbcopy"], input=value, text=True, check=True)
    print(f"{key} 已复制到剪贴板；不会在终端显示。")
    return 0


def show_status() -> int:
    _lines, values = parse_env(ENV_PATH)
    checks = {
        "provider": values.get("WECHAT_PROVIDER") == "wecom",
        "corp_id": bool(values.get("WECOM_CORP_ID")),
        "corp_secret": bool(values.get("WECOM_CORP_SECRET")),
        "callback_token": 3 <= len(values.get("WECOM_CALLBACK_TOKEN", "")) <= 32,
        "encoding_aes_key": (
            len(values.get("WECOM_ENCODING_AES_KEY", "")) == 43
            and values.get("WECOM_ENCODING_AES_KEY", "").isalnum()
        ),
    }
    for label, ready in checks.items():
        print(f"{'✓' if ready else '✗'} {label}")
    return 0 if all(checks.values()) else 1


def rotate_aes_key() -> int:
    lines, existing = parse_env(ENV_PATH)
    if not existing:
        print(".env 尚未配置，请先运行配置向导。")
        return 1
    updates = {
        key: generated_aes_key() if key == "WECOM_ENCODING_AES_KEY" else existing.get(key, "")
        for key in MANAGED_KEYS
    }
    update_env(lines, updates)
    print("WECOM_ENCODING_AES_KEY 已安全轮换为微信页面兼容格式。")
    print("运行 --copy aes-key 可复制新值；密钥不会在终端显示。")
    return 0


def configure() -> int:
    lines, existing = parse_env(ENV_PATH)
    current_id = existing.get("WECOM_CORP_ID", "")
    hint = f"（当前后四位 {current_id[-4:]}，直接回车保留）" if current_id else ""
    corp_id = input(f"企业 ID / CorpID {hint}: ").strip() or current_id
    corp_id = validate_value("CorpID", corp_id)

    current_secret = existing.get("WECOM_CORP_SECRET", "")
    prompt = "微信客服 API Secret（输入时不会显示）"
    if current_secret:
        prompt += "，直接回车保留现有值"
    corp_secret = getpass.getpass(f"{prompt}: ").strip() or current_secret
    corp_secret = validate_value("微信客服 API Secret", corp_secret)

    callback_token = existing.get("WECOM_CALLBACK_TOKEN") or generated_token()
    aes_key = existing.get("WECOM_ENCODING_AES_KEY") or generated_aes_key()
    updates = {
        "WECHAT_PROVIDER": "wecom",
        "WECOM_CORP_ID": corp_id,
        "WECOM_CORP_SECRET": corp_secret,
        "WECOM_CALLBACK_TOKEN": callback_token,
        "WECOM_ENCODING_AES_KEY": aes_key,
        "WECOM_API_BASE_URL": existing.get(
            "WECOM_API_BASE_URL", "https://qyapi.weixin.qq.com"
        ),
        "WECOM_REQUEST_TIMEOUT_SECONDS": existing.get(
            "WECOM_REQUEST_TIMEOUT_SECONDS", "15"
        ),
        "WECOM_SYNC_MAX_PAGES": existing.get("WECOM_SYNC_MAX_PAGES", "10"),
    }
    update_env(lines, updates)
    print("\n企业微信配置已安全写入 .env（权限 600），未打印任何密钥。")
    print("将回调参数复制到企业微信后台：")
    print("  python scripts/configure_wecom.py --copy token")
    print("  python scripts/configure_wecom.py --copy aes-key")
    print("之后运行：python scripts/verify_wecom.py")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="安全配置企业微信客服官方接口")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--copy", choices=("token", "aes-key"))
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--rotate-aes-key", action="store_true")
    args = parser.parse_args()
    if args.copy:
        return copy_secret(args.copy)
    if args.check:
        return show_status()
    if args.rotate_aes_key:
        return rotate_aes_key()
    return configure()


if __name__ == "__main__":
    raise SystemExit(main())
