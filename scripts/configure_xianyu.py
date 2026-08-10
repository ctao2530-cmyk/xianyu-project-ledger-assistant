#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import platform
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_SESSION_CACHE_PATH = "data/private/xianyu-session.json"
DEFAULT_GOOFISH_COOKIE_PATH = Path.home() / ".goofish-cli" / "cookies.json"
REQUIRED_COOKIE_NAMES = ("_m_h5_tk", "_m_h5_tk_enc", "unb", "cookie2")
GOOFISH_COOKIE_SALT = b"goofish-cli-cookie-enc-v1"
GOOFISH_COOKIE_ITERATIONS = 480_000


def _unquote_env_value(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value.strip('"')
        return decoded if isinstance(decoded, str) else value
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def parse_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = _unquote_env_value(value)
    return lines, values


def normalize_cookie(raw: str) -> str:
    value = raw.strip()
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()
    if not value or "\n" in value or "\r" in value:
        raise ValueError("Cookie 不能为空或包含多行内容")
    return value


def token_expiry_ms(token_value: str) -> int | None:
    suffix = token_value.rsplit("_", 1)[-1]
    if not suffix.isdigit():
        return None
    value = int(suffix)
    return value * 1000 if value < 10_000_000_000 else value


def validate_cookie(raw: str, *, now_ms: int | None = None) -> dict[str, object]:
    value = normalize_cookie(raw)
    parsed = SimpleCookie()
    try:
        parsed.load(value)
    except Exception as exc:
        raise ValueError("Cookie 格式无法解析") from exc
    names = set(parsed.keys())
    missing = [name for name in REQUIRED_COOKIE_NAMES if name not in names]
    if missing:
        raise ValueError(f"Cookie 缺少必要字段：{', '.join(missing)}")
    expiry_ms = token_expiry_ms(parsed["_m_h5_tk"].value)
    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    if expiry_ms is not None and expiry_ms <= current_ms:
        raise ValueError("_m_h5_tk 已过期，请从刚刚刷新的 Edge 请求重新复制")
    return {
        "value": value,
        "field_count": len(names),
        "expiry_ms": expiry_ms,
    }


def update_env(
    path: Path,
    lines: list[str],
    *,
    cookie: str,
    session_cache_mode: str = "keep",
) -> None:
    updates = {"XIANYU_COOKIE": json.dumps(cookie, ensure_ascii=False)}
    if session_cache_mode == "enable":
        updates["XIANYU_SESSION_CACHE_PATH"] = DEFAULT_SESSION_CACHE_PATH
    elif session_cache_mode == "disable":
        updates["XIANYU_SESSION_CACHE_PATH"] = ""

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
    missing = [key for key in updates if key not in replaced]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# Xianyu local credentials (managed by scripts/configure_xianyu.py)")
        output.extend(f"{key}={updates[key]}" for key in missing)

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".env.xianyu-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output).rstrip() + "\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def read_clipboard() -> str:
    completed = subprocess.run(
        ["pbpaste"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _goofish_machine_key(
    *, hostname: str | None = None, username: str | None = None
) -> bytes:
    """Derive the same machine-local key used by the installed Goofish CLI.

    The decrypted value never leaves this process.  This bridge deliberately
    avoids asking the user to copy a full Cookie through chat or a terminal.
    """
    machine = hostname if hostname is not None else platform.node()
    user = username if username is not None else getpass.getuser()
    raw = f"{machine}:{user}:goofish-cli".encode()
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        raw,
        GOOFISH_COOKIE_SALT,
        GOOFISH_COOKIE_ITERATIONS,
    )
    return base64.urlsafe_b64encode(derived)


def read_goofish_cookie_store(path: Path) -> str:
    """Read Goofish's encrypted, mode-0600 cookie store without displaying it."""
    resolved = path.expanduser()
    if resolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"Goofish 登录缓存不存在或不是普通文件：{resolved}")
    metadata = resolved.stat()
    if metadata.st_uid != os.getuid():
        raise ValueError("Goofish 登录缓存不属于当前用户，拒绝读取")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("Goofish 登录缓存权限过宽，请先修正为 600")
    try:
        decrypted = Fernet(_goofish_machine_key()).decrypt(resolved.read_bytes())
    except InvalidToken as exc:
        raise ValueError("Goofish 登录缓存无法在当前 Mac 上解密") from exc
    try:
        payload = json.loads(decrypted)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Goofish 登录缓存内容格式无效") from exc
    if isinstance(payload, list):
        cookies = {
            str(item["name"]): str(item["value"])
            for item in payload
            if isinstance(item, dict) and "name" in item and "value" in item
        }
    elif isinstance(payload, dict):
        cookies = {str(key): str(value) for key, value in payload.items()}
    else:
        raise ValueError("Goofish 登录缓存内容格式无效")
    if not cookies:
        raise ValueError("Goofish 登录缓存为空")
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _format_expiry(expiry_ms: int | None) -> str:
    if expiry_ms is None:
        return "未携带可解析的有效期"
    value = datetime.fromtimestamp(expiry_ms / 1000, tz=timezone.utc)
    return value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S 北京时间")


def show_status() -> int:
    _lines, values = parse_env(ENV_PATH)
    raw = values.get("XIANYU_COOKIE", "")
    try:
        summary = validate_cookie(raw)
    except ValueError as exc:
        print(f"✗ 闲鱼 Cookie 不可用：{exc}")
        return 1
    cache_enabled = bool(values.get("XIANYU_SESSION_CACHE_PATH", "").strip())
    print("✓ 闲鱼 Cookie 结构完整")
    print(f"✓ 共 {summary['field_count']} 个 Cookie 字段；内容不会显示")
    print(f"✓ _m_h5_tk 有效期：{_format_expiry(summary['expiry_ms'])}")
    print(f"{'✓' if cache_enabled else '○'} 本机会话续期缓存：{'已启用' if cache_enabled else '未启用'}")
    return 0


def configure(
    *,
    use_clipboard: bool,
    goofish_store: str | None,
    session_cache_mode: str,
) -> int:
    lines, _values = parse_env(ENV_PATH)
    if use_clipboard:
        raw = read_clipboard()
        source_label = "剪贴板"
    elif goofish_store is not None:
        try:
            raw = read_goofish_cookie_store(Path(goofish_store))
        except ValueError as exc:
            print(f"配置未写入：{exc}")
            return 1
        source_label = "Goofish 加密登录缓存"
    else:
        raw = getpass.getpass("粘贴 Edge 请求中的完整 Cookie（输入不会显示）: ")
        source_label = "隐藏输入"
    try:
        summary = validate_cookie(raw)
    except ValueError as exc:
        print(f"配置未写入：{exc}")
        return 1
    update_env(
        ENV_PATH,
        lines,
        cookie=str(summary["value"]),
        session_cache_mode=session_cache_mode,
    )
    print(
        f"已从{source_label}安全更新闲鱼 Cookie（.env 权限 600），内容未显示。"
    )
    print(f"_m_h5_tk 有效期：{_format_expiry(summary['expiry_ms'])}")
    if session_cache_mode == "enable":
        print("本机会话续期缓存将在下次服务启动后启用，仅保存两个短期 MTop 令牌。")
    elif session_cache_mode == "disable":
        print("本机会话续期缓存已关闭。")
    print("下一步应重启唯一 8877 服务，并且只验证一件商品。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="安全更新本机闲鱼 Cookie")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--clipboard",
        action="store_true",
        help="从本机剪贴板读取 Cookie；不会输出内容",
    )
    source.add_argument(
        "--goofish-store",
        nargs="?",
        const=str(DEFAULT_GOOFISH_COOKIE_PATH),
        metavar="PATH",
        help=(
            "从 Goofish CLI 的加密登录缓存读取；省略 PATH 时使用 "
            "~/.goofish-cli/cookies.json"
        ),
    )
    parser.add_argument("--check", action="store_true", help="只检查当前配置")
    cache = parser.add_mutually_exclusive_group()
    cache.add_argument("--enable-session-cache", action="store_true")
    cache.add_argument("--disable-session-cache", action="store_true")
    args = parser.parse_args()
    if args.check:
        return show_status()
    cache_mode = (
        "enable"
        if args.enable_session_cache
        else "disable"
        if args.disable_session_cache
        else "keep"
    )
    return configure(
        use_clipboard=args.clipboard,
        goofish_store=args.goofish_store,
        session_cache_mode=cache_mode,
    )


if __name__ == "__main__":
    raise SystemExit(main())
