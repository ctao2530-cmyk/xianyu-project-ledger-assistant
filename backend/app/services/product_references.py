from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qs, urljoin, urlparse

import httpx


class ProductReferenceResolutionError(RuntimeError):
    pass


URL_PATTERN = re.compile(r"https?://[^\s<>\"'，。；、]+", re.IGNORECASE)
ITEM_ID_PATTERN = re.compile(
    r"(?:itemId|item_id|[?&]id)[=/]([A-Za-z0-9_-]{5,128})",
    re.IGNORECASE,
)
TRUSTED_HOSTS = {"m.tb.cn", "tb.cn"}
TRUSTED_SUFFIXES = (".goofish.com", ".taobao.com", ".tmall.com")


def _trusted_https_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https":
        raise ProductReferenceResolutionError("仅支持 HTTPS 闲鱼分享链接")
    host = (parsed.hostname or "").strip(".").lower()
    if not host:
        raise ProductReferenceResolutionError("分享链接缺少有效域名")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ProductReferenceResolutionError("不接受 IP 或本机地址形式的分享链接")
    if host == "localhost" or host.endswith(".localhost"):
        raise ProductReferenceResolutionError("不接受本机地址形式的分享链接")
    if host not in TRUSTED_HOSTS and not any(host.endswith(suffix) for suffix in TRUSTED_SUFFIXES):
        raise ProductReferenceResolutionError("只接受闲鱼、淘宝官方分享链接")
    return value


def _candidate_from_url(value: str) -> str | None:
    parsed = urlparse(value)
    queries = parse_qs(parsed.query)
    candidate = (
        queries.get("itemId", [None])[0]
        or queries.get("item_id", [None])[0]
        or queries.get("id", [None])[0]
    )
    if candidate is None:
        match = ITEM_ID_PATTERN.search(value)
        candidate = match.group(1) if match else None
    candidate = str(candidate or "").strip()
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{5,128}", candidate) else None


def direct_product_id(reference: str) -> str | None:
    value = reference.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{5,128}", value):
        return value
    ids: set[str] = set()
    for raw_url in URL_PATTERN.findall(value):
        url = raw_url.rstrip(")]】）.,;!?，。；！？」'\"")
        _trusted_https_url(url)
        candidate = _candidate_from_url(url)
        if candidate:
            ids.add(candidate)
    for match in ITEM_ID_PATTERN.finditer(value):
        ids.add(match.group(1))
    if len(ids) > 1:
        raise ProductReferenceResolutionError("分享内容中识别到多个商品，请一次只粘贴一个")
    return next(iter(ids), None)


async def resolve_product_reference(
    reference: str,
    *,
    client: httpx.AsyncClient | None = None,
    max_redirects: int = 3,
) -> str:
    direct = direct_product_id(reference)
    if direct:
        return direct

    urls = [
        raw.rstrip(")]】）.,;!?，。；！？」'\"")
        for raw in URL_PATTERN.findall(reference)
    ]
    if not urls:
        raise ProductReferenceResolutionError("没有识别到商品 ID 或官方分享链接")
    if len(urls) > 1:
        raise ProductReferenceResolutionError("分享内容中包含多个链接，请一次只粘贴一个")
    current = _trusted_https_url(urls[0])
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(7.0),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        for _ in range(max_redirects + 1):
            response = await active_client.get(current, headers={"Cookie": ""})
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise ProductReferenceResolutionError("官方短链接没有返回跳转地址")
                current = _trusted_https_url(urljoin(current, location))
                candidate = _candidate_from_url(current)
                if candidate:
                    return candidate
                continue
            response.raise_for_status()
            candidates: set[str] = set()
            candidate = _candidate_from_url(str(response.url))
            if candidate:
                candidates.add(candidate)
            text = response.text[:500_000]
            for match in ITEM_ID_PATTERN.finditer(text):
                candidates.add(match.group(1))
            for raw_url in URL_PATTERN.findall(text):
                try:
                    embedded = _candidate_from_url(_trusted_https_url(raw_url))
                except ProductReferenceResolutionError:
                    continue
                if embedded:
                    candidates.add(embedded)
            if len(candidates) == 1:
                return next(iter(candidates))
            if len(candidates) > 1:
                raise ProductReferenceResolutionError("分享页面包含多个商品，无法安全判断目标商品")
            break
    except httpx.TimeoutException:
        raise ProductReferenceResolutionError("官方分享链接解析超时，请稍后重试或直接输入商品 ID") from None
    except httpx.HTTPError:
        raise ProductReferenceResolutionError("官方分享链接暂时无法读取，请稍后重试") from None
    finally:
        if owns_client:
            await active_client.aclose()
    raise ProductReferenceResolutionError("没有从分享内容中识别到有效商品 ID")
