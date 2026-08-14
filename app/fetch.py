"""HTTP helpers: fetch with caching, retries, custom UA and timeouts.

Stdlib only (urllib). All scrapers go through here so we can:
  - cache responses per-URL with TTL
  - retry transient failures
  - avoid hammering the target sites
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.request
import urllib.parse
import threading
import zlib

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 25


class FetchError(Exception):
    """Raised when a remote fetch ultimately fails."""


# --------------------------------------------------------------------------
# TTL cache
# --------------------------------------------------------------------------
class TTLCache:
    def __init__(self):
        self._data: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float) -> object | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            inserted, value = item
            if time.time() - inserted > ttl:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: object) -> None:
        with self._lock:
            self._data[key] = (time.time(), value)


_cache = TTLCache()


# --------------------------------------------------------------------------
# low-level fetch
# --------------------------------------------------------------------------
def _open(url: str, headers: dict | None, timeout: float, data: bytes | None = None):
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
        **(headers or {}),
    })
    return urllib.request.urlopen(req, timeout=timeout)


def _decompress(raw: bytes, content_encoding: str | None) -> bytes:
    if not content_encoding:
        return raw
    enc = content_encoding.lower().strip()
    if "gzip" in enc:
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    if "deflate" in enc:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            try:
                return zlib.decompress(raw, -15)
            except zlib.error:
                return raw
    return raw


def fetch_bytes(
    url: str,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
    data: bytes | None = None,
) -> bytes:
    """Fetch a URL, retrying transient failures. Raises FetchError on failure."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with _open(url, headers, timeout, data) as resp:
                raw = resp.read()
                return _decompress(raw, resp.headers.get("Content-Encoding"))
        except Exception as exc:  # noqa: BLE001 — network errors come in many flavours
            last = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    raise FetchError(f"{url}: {last}")


def fetch_text(
    url: str,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
    data: bytes | None = None,
    encoding: str | None = None,
) -> str:
    raw = fetch_bytes(url, headers=headers, timeout=timeout, retries=retries, data=data)
    if encoding:
        return raw.decode(encoding, errors="replace")
    # sniff charset from headers / meta
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return raw.decode("latin-1", errors="replace")


def fetch_json(
    url: str,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
    data: bytes | None = None,
):
    text = fetch_text(url, headers=headers, timeout=timeout, retries=retries, data=data)
    return json.loads(text)


# --------------------------------------------------------------------------
# cached variants
# --------------------------------------------------------------------------
def cached_fetch_text(url: str, ttl: float, **kw) -> str:
    cached = _cache.get("text:" + url, ttl)
    if cached is not None:
        return cached
    text = fetch_text(url, **kw)
    _cache.set("text:" + url, text)
    return text


def cached_fetch_json(url: str, ttl: float, **kw):
    cached = _cache.get("json:" + url, ttl)
    if cached is not None:
        return cached
    data = fetch_json(url, **kw)
    _cache.set("json:" + url, data)
    return data


def urljoin(base: str, path: str) -> str:
    return urllib.parse.urljoin(base, path)
