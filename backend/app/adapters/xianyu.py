from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import random
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import msgpack
import websockets
from websockets.asyncio.client import ClientConnection

from ..channels.base import ChannelConversationInfo, ChannelMessage
from ..config import PROJECT_ROOT, Settings
from .base import (
    AdapterAccessVerificationError,
    AdapterDisconnectedError,
    AdapterError,
    IncomingMessage,
    ItemInfo,
    LoginExpiredError,
)


logger = logging.getLogger(__name__)

MTOP_APP_KEY = "34839810"
IM_APP_KEY = "444e9908a51d1cb236a27862abc769c9"
LOGIN_TOKEN_API = "mtop.taobao.idlemessage.pc.login.token"
LOGIN_USER_API = "mtop.taobao.idlemessage.pc.loginuser.get"
ITEM_DETAIL_API = "mtop.taobao.idle.pc.detail"
MTOP_BASE = "https://h5api.m.goofish.com/h5"
ITEM_DETAIL_SPM = "a21ybx.item.0.0"
IM_SPM = "a21ybx.im.0.0"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
SESSION_COOKIE_NAMES = ("_m_h5_tk", "_m_h5_tk_enc")
VERIFICATION_HOST_SUFFIXES = (".taobao.com", ".goofish.com", ".alibaba.com")


def parse_cookie_string(raw: str) -> dict[str, str]:
    cookie = SimpleCookie()
    cookie.load(raw)
    return {key: morsel.value for key, morsel in cookie.items()}


def mtop_sign(token: str, timestamp_ms: str, data: str) -> str:
    source = f"{token}&{timestamp_ms}&{MTOP_APP_KEY}&{data}"
    return hashlib.md5(source.encode("utf-8")).hexdigest()  # noqa: S324 - protocol requirement


def generate_mid() -> str:
    return f"{random.randint(0, 999)}{int(time.time() * 1000)} 0"


def decode_sync_payload(payload: str) -> dict:
    """Decode the MessagePack payload used by the current Goofish web client."""
    decoded = base64.b64decode(payload)
    value = msgpack.unpackb(decoded, raw=False, strict_map_key=False)
    if not isinstance(value, dict):
        raise ValueError("unexpected sync payload")
    return value


def _lookup(mapping: dict, key: int | str, default=None):
    return mapping.get(key, mapping.get(str(key), default))


def _verification_url(payload: object, *, depth: int = 0) -> str | None:
    """Return only a platform-owned HTTPS verification URL from an RPC response."""
    if depth > 8:
        return None
    if isinstance(payload, dict):
        prioritized = [payload.get(key) for key in ("url", "redirectUrl", "punishUrl")]
        prioritized.extend(
            value
            for key, value in payload.items()
            if key not in {"url", "redirectUrl", "punishUrl"}
        )
        for value in prioritized:
            candidate = _verification_url(value, depth=depth + 1)
            if candidate:
                return candidate
        return None
    if isinstance(payload, list):
        for value in payload:
            candidate = _verification_url(value, depth=depth + 1)
            if candidate:
                return candidate
        return None
    if not isinstance(payload, str):
        return None
    value = payload.strip()
    if not value.startswith("https://"):
        return None
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if any(hostname.endswith(suffix) for suffix in VERIFICATION_HOST_SUFFIXES):
        return value
    return None


def is_subscription_confirmation(frame: dict, registration_mid: str) -> bool:
    """Return true only after the IM server acknowledges or starts sync."""
    headers = frame.get("headers") or {}
    if frame.get("lwp") == "/s/vulcan":
        return True
    if str(headers.get("mid") or "") == registration_mid and frame.get("code") == 200:
        return True
    body = frame.get("body") or {}
    return isinstance(body, dict) and isinstance(body.get("syncPushPackage"), dict)


def _parse_extension_json(extension: dict) -> dict:
    raw = extension.get("extJson") or extension.get("bizTag") or "{}"
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _named_values(value, name: str, *, depth: int = 0):
    """Yield named nested values from an RPC response with a depth guard."""
    if depth > 12:
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == name:
                yield nested
            yield from _named_values(nested, name, depth=depth + 1)
    elif isinstance(value, list):
        for nested in value:
            yield from _named_values(nested, name, depth=depth + 1)


def _item_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    values = parse_qs(urlparse(url).query)
    item_id = values.get("itemId", [None])[0]
    return str(item_id) if item_id else None


def _deterministic_message_id(
    conversation_id: str, sender_id: str, timestamp: int | str, content: str
) -> str:
    raw = f"{conversation_id}|{sender_id}|{timestamp}|{content}"
    return "fallback-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _iter_live_message_candidates(value, *, depth: int = 0):
    """Yield strongly-shaped messages from single or batched sync envelopes."""
    if depth > 8:
        return
    if isinstance(value, dict):
        extension = _lookup(value, 10)
        if (
            _lookup(value, 2)
            and isinstance(extension, dict)
            and extension.get("senderUserId")
        ):
            yield value
            return
        for key, nested in value.items():
            if key in (10, "10"):
                continue
            if isinstance(nested, (dict, list)):
                yield from _iter_live_message_candidates(nested, depth=depth + 1)
    elif isinstance(value, list):
        for nested in value:
            if isinstance(nested, (dict, list)):
                yield from _iter_live_message_candidates(nested, depth=depth + 1)


def _parse_live_message_candidate(
    message: dict, own_user_id: str
) -> IncomingMessage | None:
    extension = _lookup(message, 10, {})
    if not isinstance(extension, dict):
        extension = {}
    conversation_id = str(_lookup(message, 2, "")).split("@")[0]
    sender_id = str(extension.get("senderUserId") or "")
    if not conversation_id or not sender_id:
        return None

    timestamp_ms = _lookup(message, 5, int(time.time() * 1000))
    content = str(
        extension.get("reminderContent")
        or extension.get("detailNotice")
        or "[暂不支持的消息类型]"
    ).strip()
    ext_json = _parse_extension_json(extension)
    external_id = str(ext_json.get("messageId") or "")
    if not external_id:
        external_id = _deterministic_message_id(
            conversation_id, sender_id, timestamp_ms, content
        )
    try:
        received_at = datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        received_at = datetime.now(timezone.utc)

    return IncomingMessage(
        external_id=external_id,
        conversation_id=conversation_id,
        sender_id=sender_id,
        sender_name=str(extension.get("reminderTitle") or "闲鱼客户"),
        content=content,
        message_type="text" if content != "[暂不支持的消息类型]" else "unsupported",
        received_at=received_at,
        item_id=_item_id_from_url(extension.get("reminderUrl")),
        direction="outbound" if sender_id == own_user_id else "inbound",
    )


def parse_live_messages(payload: dict, own_user_id: str) -> list[IncomingMessage]:
    """Parse every distinct chat message contained in one live sync payload."""
    root = _lookup(payload, 1, payload)
    messages: list[IncomingMessage] = []
    seen_ids: set[str] = set()
    for candidate in _iter_live_message_candidates(root):
        event = _parse_live_message_candidate(candidate, own_user_id)
        if not event or event.external_id in seen_ids:
            continue
        seen_ids.add(event.external_id)
        messages.append(event)
    return messages


def parse_live_message(payload: dict, own_user_id: str) -> IncomingMessage | None:
    """Compatibility wrapper for callers expecting one message per frame."""
    messages = parse_live_messages(payload, own_user_id)
    return messages[0] if messages else None


def parse_history_message(model: dict, own_user_id: str) -> IncomingMessage | None:
    message = model.get("message", model)
    if not isinstance(message, dict):
        return None
    extension = message.get("extension") or {}
    content_block = message.get("content") or {}
    custom = content_block.get("custom") or {}
    decoded_content: dict = {}
    try:
        decoded_content = json.loads(base64.b64decode(custom.get("data", "")).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        pass

    text = (
        (decoded_content.get("text") or {}).get("text")
        if isinstance(decoded_content.get("text"), dict)
        else None
    )
    text = text or extension.get("reminderContent") or "[暂不支持的历史消息类型]"
    sender_id = str(extension.get("senderUserId") or "")
    conversation_id = str(message.get("cid") or message.get("conversationId") or "").split("@")[0]
    if not conversation_id:
        reminder_url = extension.get("reminderUrl") or ""
        conversation_id = str(parse_qs(urlparse(reminder_url).query).get("sid", [""])[0])
    if not sender_id or not conversation_id:
        return None

    ext_json = _parse_extension_json(extension)
    timestamp_ms = (
        message.get("createAt")
        or message.get("createTime")
        or message.get("sendTime")
        or int(time.time() * 1000)
    )
    external_id = str(ext_json.get("messageId") or message.get("uuid") or "")
    if not external_id:
        external_id = _deterministic_message_id(conversation_id, sender_id, timestamp_ms, str(text))
    try:
        received_at = datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        received_at = datetime.now(timezone.utc)
    return IncomingMessage(
        external_id=external_id,
        conversation_id=conversation_id,
        sender_id=sender_id,
        sender_name=str(extension.get("reminderTitle") or "闲鱼客户"),
        content=str(text),
        message_type="text" if text != "[暂不支持的历史消息类型]" else "unsupported",
        received_at=received_at,
        item_id=_item_id_from_url(extension.get("reminderUrl")),
        direction="outbound" if sender_id == own_user_id else "inbound",
    )


class XianyuAdapter:
    channel = "xianyu"

    async def receive_message(self, payload: ChannelMessage) -> ChannelMessage:
        """Expose the existing normalized event through the shared channel boundary."""
        if not isinstance(payload, ChannelMessage):
            raise TypeError("闲鱼渠道只接受已标准化的 ChannelMessage")
        payload.channel = self.channel
        if not payload.platform_message_id:
            payload.platform_message_id = payload.external_id
        return payload

    async def get_conversation_info(
        self, conversation_id: str
    ) -> ChannelConversationInfo | None:
        messages = await self.fetch_recent_messages(conversation_id, 1)
        if not messages:
            return None
        message = messages[-1]
        return ChannelConversationInfo(
            channel=self.channel,
            conversation_id=conversation_id,
            customer_id=message.sender_id,
            customer_name=message.sender_name,
        )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cookies = parse_cookie_string(settings.xianyu_cookie.get_secret_value())
        self.own_user_id = self.cookies.get("unb", "")
        self._session_cache_path = self._resolve_session_cache_path(
            settings.xianyu_session_cache_path
        )
        self._persisted_session_snapshot: tuple[str, str] | None = None
        self._session_cache_warning_emitted = False
        self._load_session_cache()
        self.device_id = f"{uuid.uuid4()}-{self.own_user_id}"
        self.http = httpx.AsyncClient(
            cookies=self.cookies,
            timeout=httpx.Timeout(20),
            trust_env=settings.xianyu_use_system_proxy,
            headers={
                "User-Agent": USER_AGENT,
                "Origin": "https://www.goofish.com",
                "Referer": "https://www.goofish.com/",
                "Accept": "application/json",
                "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8,zh-TW;q=0.7,ja;q=0.6",
                "Cache-Control": "no-cache",
                "Content-Type": "application/x-www-form-urlencoded",
                "Pragma": "no-cache",
                "Priority": "u=1, i",
                "Sec-CH-UA": (
                    '"Chromium";v="146", "Not-A.Brand";v="24", '
                    '"Google Chrome";v="146"'
                ),
                "Sec-CH-UA-Mobile": "?0",
                "Sec-CH-UA-Platform": '"macOS"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
            },
        )
        self.ws: ClientConnection | None = None
        self.connected = False
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._fatal_error: Exception | None = None
        self.subscription_confirmed = False
        self.last_frame_at: datetime | None = None
        self.last_decoded_at: datetime | None = None
        self.last_live_message_at: datetime | None = None
        self.frames_received = 0
        self.decode_failures = 0
        self.parse_dropped = 0
        self.live_messages_received = 0

    @staticmethod
    def _resolve_session_cache_path(raw_path: str) -> Path | None:
        value = raw_path.strip()
        if not value:
            return None
        path = Path(value).expanduser()
        return path if path.is_absolute() else PROJECT_ROOT / path

    @staticmethod
    def _token_expiry_ms(token_value: str) -> int | None:
        suffix = token_value.rsplit("_", 1)[-1]
        if not suffix.isdigit():
            return None
        try:
            return int(suffix)
        except ValueError:
            return None

    def _session_account_fingerprint(self) -> str:
        if not self.own_user_id:
            return ""
        return hashlib.sha256(self.own_user_id.encode("utf-8")).hexdigest()

    def _warn_session_cache_once(self, exc: Exception) -> None:
        if self._session_cache_warning_emitted:
            return
        self._session_cache_warning_emitted = True
        logger.warning(
            "闲鱼短期会话缓存不可用 error=%s",
            type(exc).__name__,
        )

    def _load_session_cache(self) -> None:
        path = self._session_cache_path
        account = self._session_account_fingerprint()
        if path is None or not account or not path.exists():
            return
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError("invalid session cache file")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != 1:
                return
            if payload.get("account_fingerprint") != account:
                return
            cached = payload.get("cookies")
            if not isinstance(cached, dict):
                return
            token = str(cached.get("_m_h5_tk") or "")
            expiry_ms = self._token_expiry_ms(token)
            if not token or (expiry_ms is not None and expiry_ms <= int(time.time() * 1000)):
                return
            for name in SESSION_COOKIE_NAMES:
                value = str(cached.get(name) or "")
                if value:
                    self.cookies[name] = value
            os.chmod(path, 0o600)
            self._persisted_session_snapshot = tuple(
                self.cookies.get(name, "") for name in SESSION_COOKIE_NAMES
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._warn_session_cache_once(exc)

    def _persist_refreshed_session_cookies(self) -> None:
        path = self._session_cache_path
        account = self._session_account_fingerprint()
        if path is None or not account:
            return
        values = {name: self._cookie_value(name) for name in SESSION_COOKIE_NAMES}
        token = values["_m_h5_tk"]
        expiry_ms = self._token_expiry_ms(token)
        if not token or (expiry_ms is not None and expiry_ms <= int(time.time() * 1000)):
            return
        snapshot = tuple(values[name] for name in SESSION_COOKIE_NAMES)
        if snapshot == self._persisted_session_snapshot:
            return
        payload = {
            "version": 1,
            "account_fingerprint": account,
            "cookies": values,
            "token_expires_at_ms": expiry_ms,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary_name = ""
        try:
            parent_existed = path.parent.exists()
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not parent_existed:
                os.chmod(path.parent, 0o700)
            fd, temporary_name = tempfile.mkstemp(
                prefix=".xianyu-session-",
                dir=path.parent,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, path)
            self._persisted_session_snapshot = snapshot
        except OSError as exc:
            self._warn_session_cache_once(exc)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @staticmethod
    def _cookie_domain_matches(cookie_domain: str, host: str) -> bool:
        normalized = cookie_domain.lstrip(".").lower()
        return not normalized or host == normalized or host.endswith(f".{normalized}")

    def _cookie_value(self, name: str, *, host: str = "h5api.m.goofish.com") -> str:
        """Read one applicable cookie without HTTPX's ambiguous-name lookup.

        HTTPX intentionally raises ``CookieConflict`` when cookies with the same
        name exist on different domains or paths. MTop periodically refreshes its
        token with a domain-scoped Set-Cookie while the user-provided cookie is
        initially domainless, so both entries can legitimately coexist.
        """
        candidates = [
            cookie
            for cookie in self.http.cookies.jar
            if cookie.name == name
            and self._cookie_domain_matches(cookie.domain or "", host)
        ]
        if not candidates:
            return ""

        def preference(cookie) -> tuple[int, int, int]:
            domain = (cookie.domain or "").lstrip(".").lower()
            exact_host = int(domain == host)
            domain_scoped = int(bool(domain))
            return (exact_host, domain_scoped, len(domain) + len(cookie.path or ""))

        return str(max(candidates, key=preference).value or "")

    def _cookie_token(self) -> str:
        token = self._cookie_value("_m_h5_tk")
        return token.split("_", 1)[0]

    def _cookie_header(self) -> str:
        names = dict.fromkeys(cookie.name for cookie in self.http.cookies.jar)
        pairs = []
        for name in names:
            value = self._cookie_value(name)
            if value:
                pairs.append(f"{name}={value}")
        return "; ".join(pairs)

    async def _mtop(
        self,
        api: str,
        data: dict,
        *,
        spm_cnt: str = IM_SPM,
        retry: bool = True,
    ) -> dict:
        token = self._cookie_token()
        if not token:
            raise LoginExpiredError("Cookie 中缺少 _m_h5_tk")
        timestamp = str(int(time.time() * 1000))
        data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        params = {
            "jsv": "2.7.2",
            "appKey": MTOP_APP_KEY,
            "t": timestamp,
            "sign": mtop_sign(token, timestamp, data_json),
            "v": "1.0",
            "type": "originaljson",
            "accountSite": "xianyu",
            "dataType": "json",
            "timeout": "20000",
            "api": api,
            "sessionOption": "AutoLoginOnly",
            "spm_cnt": spm_cnt,
        }
        url = f"{MTOP_BASE}/{api}/1.0/"
        # Always provide a single value per cookie name. After a MTop token
        # refresh HTTPX's jar may temporarily contain both the original
        # domainless token and the new domain-scoped token. Letting the jar
        # render that state would send two _m_h5_tk values, and MTop can read
        # the stale one before the refreshed value.
        response = await self.http.post(
            url,
            params=params,
            data={"data": data_json},
            headers={"Cookie": self._cookie_header()},
        )
        self._persist_refreshed_session_cookies()
        response.raise_for_status()
        payload = response.json()
        ret = " ".join(payload.get("ret") or [])
        if any(marker in ret.upper() for marker in ("SESSION_EXPIRED", "SID_INVALID", "NEED_LOGIN")):
            raise LoginExpiredError("闲鱼登录已失效")
        if any(
            marker in ret.upper()
            for marker in ("FAIL_SYS_USER_VALIDATE", "RGV587_ERROR")
        ):
            raise AdapterAccessVerificationError(
                "闲鱼商品接口要求在浏览器中完成访问验证",
                verification_url=_verification_url(payload),
            )
        if "令牌过期" in ret and retry:
            return await self._mtop(api, data, spm_cnt=spm_cnt, retry=False)
        return payload

    async def _access_token(self) -> str:
        payload = await self._mtop(
            LOGIN_TOKEN_API, {"appKey": IM_APP_KEY, "deviceId": self.device_id}
        )
        token = str((payload.get("data") or {}).get("accessToken") or "")
        if not token:
            ret = " ".join(payload.get("ret") or [])
            if any(word in ret for word in ("登录", "会话", "令牌", "cookie")):
                raise LoginExpiredError("闲鱼登录已失效")
            raise AdapterError(f"未获取到闲鱼 IM 令牌：{ret or '未知响应'}")
        return token

    async def _refresh_loop(self) -> None:
        while self.ws is not None:
            await asyncio.sleep(600)
            try:
                await self._mtop(LOGIN_USER_API, {})
            except Exception as exc:
                self._fatal_error = exc
                if self.ws:
                    await self.ws.close(code=1000, reason="login refresh failed")
                return

    async def _heartbeat(self) -> None:
        while self.ws is not None:
            await asyncio.sleep(15)
            try:
                await self._send_json({"lwp": "/!", "headers": {"mid": generate_mid()}})
            except Exception:
                return

    async def _send_json(self, payload: dict) -> None:
        if not self.ws:
            raise AdapterDisconnectedError("闲鱼监听未连接")
        async with self._send_lock:
            await self.ws.send(json.dumps(payload, ensure_ascii=False))

    async def _register(self, access_token: str) -> str:
        now_ms = int(time.time() * 1000)
        registration_mid = generate_mid()
        await self._send_json(
            {
                "lwp": "/reg",
                "headers": {
                    "cache-header": "app-key token ua wv",
                    "app-key": IM_APP_KEY,
                    "token": access_token,
                    "ua": f"{USER_AGENT} DingTalk(2.1.5) OS(macOS) DingWeb/2.1.5",
                    "dt": "j",
                    "wv": "im:3,au:3,sy:6",
                    "sync": "0,0;0;0;",
                    "did": self.device_id,
                    "mid": registration_mid,
                },
            }
        )
        await self._send_json(
            {
                "lwp": "/r/SyncStatus/ackDiff",
                "headers": {"mid": generate_mid()},
                "body": [
                    {
                        "pipeline": "sync",
                        "tooLong2Tag": "PNM,1",
                        "channel": "sync",
                        "topic": "sync",
                        "highPts": 0,
                        "pts": now_ms * 1000,
                        "seq": 0,
                        "timestamp": now_ms,
                    }
                ],
            }
        )
        return registration_mid

    async def _subscription_watchdog(self, websocket: ClientConnection) -> None:
        await asyncio.sleep(self.settings.xianyu_subscription_timeout_seconds)
        if self.ws is websocket and not self.subscription_confirmed:
            self._fatal_error = AdapterDisconnectedError("闲鱼消息订阅确认超时")
            await websocket.close(code=1000, reason="subscription confirmation timeout")

    @staticmethod
    def _safe_payload_shape(payload: dict) -> str:
        root = _lookup(payload, 1)
        root_keys = list(root.keys())[:16] if isinstance(root, dict) else []
        return f"top={list(payload.keys())[:8]} field1_type={type(root).__name__} field1_keys={root_keys}"

    def _record_decode_failure(self) -> None:
        self.decode_failures += 1
        if self.decode_failures <= 3 or self.decode_failures % 25 == 0:
            logger.warning(
                "忽略无法解码的闲鱼同步消息 count=%s", self.decode_failures
            )

    def _record_parse_drop(self, payload: dict) -> None:
        self.parse_dropped += 1
        if self.parse_dropped <= 3 or self.parse_dropped % 25 == 0:
            logger.warning(
                "闲鱼同步帧已解码但未识别为客户消息 count=%s shape=%s",
                self.parse_dropped,
                self._safe_payload_shape(payload),
            )

    async def _ack(self, message: dict) -> None:
        headers = message.get("headers") or {}
        ack_headers = {
            "mid": headers.get("mid") or generate_mid(),
            "sid": headers.get("sid") or "",
        }
        for key in ("app-key", "ua", "dt"):
            if key in headers:
                ack_headers[key] = headers[key]
        await self._send_json({"code": 200, "headers": ack_headers})

    async def _request(self, lwp: str, body: list, timeout: float = 15) -> dict:
        if not self.connected:
            raise AdapterDisconnectedError("闲鱼监听未连接")
        mid = generate_mid()
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[mid] = future
        try:
            await self._send_json({"lwp": lwp, "headers": {"mid": mid}, "body": body})
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(mid, None)

    async def listen(
        self, on_ready: Callable[[], None] | None = None
    ) -> AsyncIterator[IncomingMessage]:
        if not self.settings.xianyu_configured:
            raise LoginExpiredError("未配置有效的 XIANYU_COOKIE")
        access_token = await self._access_token()
        cookie_header = self._cookie_header()
        headers = {
            "Cookie": cookie_header,
            "User-Agent": USER_AGENT,
            "Origin": "https://www.goofish.com",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
        }
        heartbeat: asyncio.Task | None = None
        refresh: asyncio.Task | None = None
        subscription_watchdog: asyncio.Task | None = None
        self._fatal_error = None
        self.subscription_confirmed = False
        try:
            async with websockets.connect(
                self.settings.xianyu_ws_url,
                additional_headers=headers,
                proxy=True if self.settings.xianyu_use_system_proxy else None,
                open_timeout=20,
                close_timeout=5,
                ping_interval=None,
                max_size=8 * 1024 * 1024,
            ) as websocket:
                self.ws = websocket
                registration_mid = await self._register(access_token)
                heartbeat = asyncio.create_task(self._heartbeat())
                refresh = asyncio.create_task(self._refresh_loop())
                subscription_watchdog = asyncio.create_task(
                    self._subscription_watchdog(websocket)
                )
                async for raw in websocket:
                    self.frames_received += 1
                    self.last_frame_at = datetime.now(timezone.utc)
                    try:
                        message = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        logger.warning("忽略无法解析的闲鱼 WebSocket 帧")
                        continue
                    await self._ack(message)
                    if not self.subscription_confirmed and is_subscription_confirmation(
                        message, registration_mid
                    ):
                        self.subscription_confirmed = True
                        self.connected = True
                        if on_ready:
                            on_ready()
                    headers = message.get("headers") or {}
                    if (
                        str(headers.get("mid") or "") == registration_mid
                        and message.get("code") not in (None, 200)
                    ):
                        raise AdapterDisconnectedError(
                            f"闲鱼消息订阅失败（code={message.get('code')}）"
                        )
                    mid = str((message.get("headers") or {}).get("mid") or "")
                    pending = self._pending.get(mid)
                    if pending and not pending.done():
                        pending.set_result(message)
                        continue

                    try:
                        sync_data = message["body"]["syncPushPackage"]["data"][0]["data"]
                    except (KeyError, IndexError, TypeError):
                        continue
                    try:
                        unpacked = json.loads(sync_data)
                        if not isinstance(unpacked, dict):
                            continue
                    except (TypeError, json.JSONDecodeError):
                        try:
                            unpacked = decode_sync_payload(sync_data)
                        except (ValueError, TypeError, msgpack.UnpackException):
                            self._record_decode_failure()
                            continue
                    self.last_decoded_at = datetime.now(timezone.utc)
                    events = parse_live_messages(unpacked, self.own_user_id)
                    inbound_events = [
                        event for event in events if event.direction == "inbound"
                    ]
                    if inbound_events:
                        self.live_messages_received += len(inbound_events)
                        self.last_live_message_at = datetime.now(timezone.utc)
                        for event in inbound_events:
                            yield event
                    elif not events:
                        self._record_parse_drop(unpacked)
        except LoginExpiredError:
            raise
        except Exception as exc:
            if self._fatal_error:
                raise self._fatal_error
            raise AdapterDisconnectedError(str(exc)) from exc
        finally:
            self.connected = False
            self.subscription_confirmed = False
            self.ws = None
            for task in (heartbeat, refresh, subscription_watchdog):
                if task:
                    task.cancel()
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(AdapterDisconnectedError("闲鱼连接已断开"))
            self._pending.clear()

    async def fetch_recent_messages(
        self, conversation_id: str, limit: int
    ) -> list[IncomingMessage]:
        response = await self._request(
            "/r/MessageManager/listUserMessages",
            [f"{conversation_id}@goofish", False, 9007199254740991, limit, False],
        )
        models = (response.get("body") or {}).get("userMessageModels") or []
        parsed = [parse_history_message(model, self.own_user_id) for model in models]
        return sorted(
            [message for message in parsed if message is not None],
            key=lambda value: value.received_at,
        )

    async def fetch_recent_conversation_messages(
        self, limit: int
    ) -> list[IncomingMessage]:
        """Fetch one latest message per recent conversation as a push fallback.

        This is a single lightweight RPC used at a bounded interval. It does not
        mark messages read and does not send anything to customers.
        """
        response = await self._request(
            "/r/Conversation/listNewest",
            [0, min(max(1, limit), 200)],
        )
        body = response.get("body") or []
        candidates = list(_named_values(body, "lastMessage"))
        parsed = [parse_history_message(candidate, self.own_user_id) for candidate in candidates]
        unique: dict[str, IncomingMessage] = {}
        for message in parsed:
            if message is not None:
                unique[message.external_id] = message
        if body and not candidates:
            body_keys = list(body.keys())[:12] if isinstance(body, dict) else []
            logger.warning(
                "闲鱼会话补偿响应中未找到 lastMessage body_type=%s body_keys=%s",
                type(body).__name__,
                body_keys,
            )
        return sorted(unique.values(), key=lambda value: value.received_at)

    async def fetch_item(self, item_id: str) -> ItemInfo | None:
        payload = await self._mtop(
            ITEM_DETAIL_API,
            {"itemId": item_id},
            spm_cnt=ITEM_DETAIL_SPM,
        )
        item = ((payload.get("data") or {}).get("itemDO") or {})
        if not isinstance(item, dict) or not item:
            return None
        sold_price = item.get("soldPrice")
        price = None if sold_price in (None, "") else f"¥{sold_price}"
        track_params = item.get("trackParams")
        seller_id = (
            str(track_params.get("sellerId") or "").strip()
            if isinstance(track_params, dict)
            else ""
        )
        return ItemInfo(
            external_id=item_id,
            title=str(item.get("title") or "未知商品"),
            price=price,
            description=str(item.get("desc") or "") or None,
            raw=item,
            seller_id=seller_id or None,
        )

    async def send_text(
        self,
        conversation_id: str,
        receiver_id: str,
        text: str,
        client_message_id: str,
    ) -> None:
        if not self.connected:
            raise AdapterDisconnectedError("闲鱼监听未连接，不能发送")
        payload = {
            "contentType": 1,
            "text": {"text": text},
        }
        encoded = base64.b64encode(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        response = await self._request(
            "/r/MessageSend/sendByReceiverScope",
            [
                {
                    "uuid": client_message_id,
                    "cid": f"{conversation_id}@goofish",
                    "conversationType": 1,
                    "content": {"contentType": 101, "custom": {"type": 1, "data": encoded}},
                    "redPointPolicy": 0,
                    "extension": {"extJson": "{}"},
                    "ctx": {"appVersion": "1.0", "platform": "web"},
                    "mtags": {},
                    "msgReadStatusSetting": 1,
                },
                {
                    "actualReceivers": [
                        f"{receiver_id}@goofish",
                        f"{self.own_user_id}@goofish",
                    ]
                },
            ],
        )
        if response.get("code", 200) not in (0, 200):
            raise AdapterError(f"闲鱼发送失败，返回码：{response.get('code')}")

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()
        await self.http.aclose()
