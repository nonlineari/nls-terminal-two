"""HTTP fetch with retries. 404 is final. 429 and 5xx are retried."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

from src.config import USER_AGENT

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


@dataclass
class FetchResult:
    ok: bool
    url: str
    status: int | None
    body: bytes | None
    error: str | None
    content_type: str | None = None
    truncated: bool = False


def fetch(
    url: str,
    *,
    params: dict | None = None,
    timeout: float = 60,
    max_attempts: int = 3,
    accept: str | None = None,
) -> FetchResult:
    headers = {}
    if accept:
        headers["Accept"] = accept
    last_error = "no attempt"
    last_status: int | None = None
    last_url = url
    for attempt in range(1, max_attempts + 1):
        try:
            response = _SESSION.get(url, params=params, timeout=timeout, headers=headers or None)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            last_status = None
            logger.info("retry %s/%s %s (%s)", attempt, max_attempts, url, last_error)
            time.sleep(min(2 ** attempt, 12))
            continue
        last_url = response.url
        last_status = response.status_code
        if response.status_code in {429, 500, 502, 503, 504}:
            last_error = f"HTTP {response.status_code}"
            logger.info("retry %s/%s %s (%s)", attempt, max_attempts, last_url, last_error)
            time.sleep(min(2 ** attempt, 12))
            continue
        if response.status_code >= 400:
            snippet = response.content[:300].decode("utf-8", "replace")
            return FetchResult(
                ok=False,
                url=last_url,
                status=response.status_code,
                body=response.content[:2000],
                error=f"HTTP {response.status_code}: {snippet}",
                content_type=response.headers.get("Content-Type"),
            )
        return FetchResult(
            ok=True,
            url=last_url,
            status=response.status_code,
            body=response.content,
            error=None,
            content_type=response.headers.get("Content-Type"),
        )
    return FetchResult(ok=False, url=last_url, status=last_status, body=None, error=last_error)


def fetch_limited(url: str, *, max_bytes: int = 250_000, timeout: float = 30) -> FetchResult:
    """GET up to max_bytes. Used for HTML probes so a surprise PDF cannot fill the disk."""
    try:
        response = _SESSION.get(
            url,
            timeout=timeout,
            stream=True,
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
    except requests.RequestException as exc:
        return FetchResult(ok=False, url=url, status=None, body=None, error=f"{type(exc).__name__}: {exc}")
    chunks: list[bytes] = []
    size = 0
    truncated = False
    try:
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            chunks.append(chunk)
            size += len(chunk)
            if size >= max_bytes:
                truncated = True
                break
    finally:
        response.close()
    body = b"".join(chunks)[:max_bytes]
    if response.status_code >= 400:
        snippet = body[:300].decode("utf-8", "replace")
        return FetchResult(
            ok=False,
            url=response.url,
            status=response.status_code,
            body=body,
            error=f"HTTP {response.status_code}: {snippet}",
            content_type=response.headers.get("Content-Type"),
            truncated=truncated,
        )
    return FetchResult(
        ok=True,
        url=response.url,
        status=response.status_code,
        body=body,
        error=None,
        content_type=response.headers.get("Content-Type"),
        truncated=truncated,
    )
