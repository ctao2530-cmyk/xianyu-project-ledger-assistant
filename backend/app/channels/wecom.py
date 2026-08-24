from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import struct
import time
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ..config import Settings
from .base import ChannelMedia, ChannelMediaContent


logger = logging.getLogger(__name__)


class WeComError(RuntimeError):
    """Base exception with a sanitized user-facing message."""


class WeComConfigurationError(WeComError):
    pass


class WeComSignatureError(WeComError):
    pass


class WeComAPIError(WeComError):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"企业微信接口错误 {code}：{message[:200]}")


@dataclass(frozen=True, slots=True)
class WeComCallbackEvent:
    event: str
    callback_token: str
    open_kfid: str


class WeComCrypto:
    """Official WeCom callback SHA1 verification and AES-CBC decoding."""

    def __init__(self, token: str, encoding_aes_key: str, receive_id: str) -> None:
        if not token or not receive_id:
            raise WeComConfigurationError("企业微信回调 Token 或 CorpID 未配置")
        try:
            key = base64.b64decode(encoding_aes_key + "=", validate=True)
        except Exception as exc:
            raise WeComConfigurationError("企业微信 EncodingAESKey 格式无效") from exc
        if len(encoding_aes_key) != 43 or len(key) != 32:
            raise WeComConfigurationError("企业微信 EncodingAESKey 必须为 43 位")
        self.token = token
        self.key = key
        self.receive_id = receive_id

    def signature(self, timestamp: str, nonce: str, encrypted: str) -> str:
        source = "".join(sorted((self.token, timestamp, nonce, encrypted)))
        return hashlib.sha1(source.encode("utf-8")).hexdigest()

    def decrypt(
        self,
        encrypted: str,
        *,
        signature: str,
        timestamp: str,
        nonce: str,
    ) -> str:
        expected = self.signature(timestamp, nonce, encrypted)
        if not secrets.compare_digest(expected, signature):
            raise WeComSignatureError("企业微信回调签名校验失败")
        try:
            ciphertext = base64.b64decode(encrypted, validate=True)
            decryptor = Cipher(
                algorithms.AES(self.key), modes.CBC(self.key[:16])
            ).decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            unpadder = padding.PKCS7(256).unpadder()
            plain = unpadder.update(padded) + unpadder.finalize()
            message_length = struct.unpack("!I", plain[16:20])[0]
            end = 20 + message_length
            message = plain[20:end].decode("utf-8")
            receive_id = plain[end:].decode("utf-8")
        except Exception as exc:
            raise WeComSignatureError("企业微信回调内容解密失败") from exc
        if receive_id != self.receive_id:
            raise WeComSignatureError("企业微信回调接收方不匹配")
        return message

    def encrypt_for_test(
        self,
        message: str,
        *,
        timestamp: str = "1700000000",
        nonce: str = "test-nonce",
        random_bytes: bytes | None = None,
    ) -> tuple[str, str]:
        """Create a protocol-valid fixture; production callbacks are inbound only."""
        prefix = random_bytes or (b"0123456789abcdef")
        if len(prefix) != 16:
            raise ValueError("random_bytes must contain 16 bytes")
        encoded = message.encode("utf-8")
        plain = prefix + struct.pack("!I", len(encoded)) + encoded + self.receive_id.encode()
        padder = padding.PKCS7(256).padder()
        padded = padder.update(plain) + padder.finalize()
        encryptor = Cipher(
            algorithms.AES(self.key), modes.CBC(self.key[:16])
        ).encryptor()
        encrypted = base64.b64encode(
            encryptor.update(padded) + encryptor.finalize()
        ).decode("ascii")
        return encrypted, self.signature(timestamp, nonce, encrypted)


def encrypted_value_from_xml(payload: bytes) -> str:
    try:
        root = ElementTree.fromstring(payload)
        encrypted = root.findtext("Encrypt")
    except ElementTree.ParseError as exc:
        raise WeComSignatureError("企业微信回调 XML 无法解析") from exc
    if not encrypted:
        raise WeComSignatureError("企业微信回调缺少 Encrypt 字段")
    return encrypted.strip()


def callback_event_from_xml(payload: str) -> WeComCallbackEvent:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise WeComSignatureError("企业微信事件 XML 无法解析") from exc
    event = (root.findtext("Event") or "").strip()
    callback_token = (root.findtext("Token") or "").strip()
    open_kfid = (root.findtext("OpenKfId") or "").strip()
    if event != "kf_msg_or_event" or not open_kfid:
        raise WeComSignatureError("不是可处理的微信客服消息事件")
    return WeComCallbackEvent(event, callback_token, open_kfid)


class WeComAPIClient:
    TOKEN_ERRORS = {40014, 42001, 42007, 42009}

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.base_url = settings.wecom_api_base_url.rstrip("/")
        self._client = http_client or httpx.AsyncClient(
            timeout=settings.wecom_request_timeout_seconds
        )
        self._owns_client = http_client is None
        self._access_token = ""
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        if not self.settings.wecom_configured:
            raise WeComConfigurationError("企业微信官方接口尚未配置完整")
        async with self._token_lock:
            if (
                not force_refresh
                and self._access_token
                and time.monotonic() < self._token_expires_at
            ):
                return self._access_token
            response = await self._client.get(
                f"{self.base_url}/cgi-bin/gettoken",
                params={
                    "corpid": self.settings.wecom_corp_id,
                    "corpsecret": self.settings.wecom_corp_secret.get_secret_value(),
                },
            )
            data = self._checked_json(response)
            token = str(data.get("access_token") or "")
            if not token:
                raise WeComAPIError(-1, "未返回 access_token")
            expires_in = max(60, int(data.get("expires_in") or 7200))
            self._access_token = token
            self._token_expires_at = time.monotonic() + max(30, expires_in - 300)
            return token

    @staticmethod
    def _checked_json(response: httpx.Response) -> dict[str, Any]:
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise WeComAPIError(-1, "返回内容不是 JSON") from exc
        if not isinstance(data, dict):
            raise WeComAPIError(-1, "返回 JSON 结构无效")
        code = int(data.get("errcode") or 0)
        if code:
            raise WeComAPIError(code, str(data.get("errmsg") or "未知错误"))
        return data

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        retry_token: bool = True,
    ) -> dict[str, Any]:
        token = await self.get_access_token()
        response = await self._client.post(
            f"{self.base_url}{path}",
            params={"access_token": token},
            json=payload,
        )
        try:
            return self._checked_json(response)
        except WeComAPIError as exc:
            if retry_token and exc.code in self.TOKEN_ERRORS:
                await self.get_access_token(force_refresh=True)
                return await self._post(path, payload, retry_token=False)
            raise

    async def healthcheck(self) -> None:
        await self.get_access_token(force_refresh=True)
        await self.account_list()

    async def account_list(self) -> list[dict[str, Any]]:
        """Verify customer-service API permission and return configured accounts."""
        token = await self.get_access_token()
        response = await self._client.get(
            f"{self.base_url}/cgi-bin/kf/account/list",
            params={"access_token": token},
        )
        data = self._checked_json(response)
        rows = data.get("account_list")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    async def sync_page(
        self,
        *,
        open_kfid: str,
        cursor: str,
        callback_token: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "limit": 1000,
            "voice_format": 0,
            "open_kfid": open_kfid,
        }
        if cursor:
            payload["cursor"] = cursor
        if callback_token:
            payload["token"] = callback_token
        return await self._post("/cgi-bin/kf/sync_msg", payload)

    async def customer_names(self, external_userids: list[str]) -> dict[str, str]:
        if not external_userids:
            return {}
        unique_ids = list(dict.fromkeys(external_userids))
        result: dict[str, str] = {}
        for start in range(0, len(unique_ids), 100):
            data = await self._post(
                "/cgi-bin/kf/customer/batchget",
                {
                    "external_userid_list": unique_ids[start : start + 100],
                    "need_enter_session_context": 0,
                },
            )
            customers = data.get("customer_list")
            if not isinstance(customers, list):
                continue
            result.update(
                {
                    str(customer["external_userid"]): str(
                        customer.get("nickname") or "微信客户"
                    )
                    for customer in customers
                    if isinstance(customer, dict) and customer.get("external_userid")
                }
            )
        return result

    async def fetch_media(
        self,
        media: ChannelMedia,
        *,
        retry_token: bool = True,
    ) -> ChannelMediaContent:
        """Download one WeCom image by its ephemeral media id."""
        if media.locator_type != "wecom_media_id" or not media.locator:
            raise WeComAPIError(-1, "图片媒体引用无效")
        token = await self.get_access_token()
        response = await self._client.get(
            f"{self.base_url}/cgi-bin/media/get",
            params={"access_token": token, "media_id": media.locator},
        )
        content_type = (response.headers.get("content-type") or "").lower()
        if "json" in content_type:
            try:
                data = response.json()
            except ValueError as exc:
                raise WeComAPIError(-1, "图片接口返回内容无效") from exc
            code = int(data.get("errcode") or 0) if isinstance(data, dict) else -1
            if retry_token and code in self.TOKEN_ERRORS:
                await self.get_access_token(force_refresh=True)
                return await self.fetch_media(media, retry_token=False)
            raise WeComAPIError(code, str(data.get("errmsg") or "图片读取失败"))
        response.raise_for_status()
        if len(response.content) > 25 * 1024 * 1024:
            raise WeComAPIError(-1, "企业微信原图超过本地保存上限")
        return ChannelMediaContent(
            data=response.content,
            mime_type=response.headers.get("content-type"),
            original_name=media.original_name,
        )

    async def send_text(
        self,
        *,
        open_kfid: str,
        external_userid: str,
        text: str,
        message_id: str,
    ) -> str:
        data = await self._post(
            "/cgi-bin/kf/send_msg",
            {
                "touser": external_userid,
                "open_kfid": open_kfid,
                "msgid": _safe_message_id(message_id),
                "msgtype": "text",
                "text": {"content": _clip_utf8(text, 2048)},
            },
        )
        return str(data.get("msgid") or message_id)


class WeComSender:
    channel = "wechat"

    def __init__(self, client: WeComAPIClient) -> None:
        self.client = client

    async def send_message(
        self,
        conversation_id: str,
        receiver_id: str,
        text: str,
        client_message_id: str,
    ) -> None:
        parts = conversation_id.split(":", 2)
        if len(parts) != 3 or parts[0] != "wechat":
            raise WeComConfigurationError("该微信会话不是企业微信客服会话")
        open_kfid = parts[1]
        await self.client.send_text(
            open_kfid=open_kfid,
            external_userid=receiver_id,
            text=text,
            message_id=client_message_id,
        )
        logger.info(
            "企业微信人工确认消息已提交 open_kfid_suffix=%s content_length=%s",
            open_kfid[-6:],
            len(text),
        )


def _safe_message_id(value: str) -> str:
    allowed = "".join(char for char in value if char.isalnum() or char in "_-")
    if 1 <= len(allowed) <= 32:
        return allowed
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _clip_utf8(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", errors="ignore")
