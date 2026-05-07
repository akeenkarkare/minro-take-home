"""Shared async HTTP client.

One httpx.AsyncClient is reused across the whole worker process for connection
pooling. Per-host rate limiting and retries are layered on top.
"""
from __future__ import annotations

import asyncio
import random
from collections import defaultdict
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import settings


_client: httpx.AsyncClient | None = None
_host_locks: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(4))


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings().http_timeout, connect=5.0),
            follow_redirects=True,
            headers={
                # Identify the bot honestly. Some sites (HN, GitHub) prefer this.
                "User-Agent": "minro-enrichment/0.1 (+https://github.com/akeenkarkare/minro-take-home)",
            },
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# Errors we retry. 429 / 5xx / network blips. NOT 4xx (those are real errors).
_RETRYABLE = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


async def request(
    method: str,
    url: str,
    *,
    host_concurrency: int = 4,
    attempts: int = 3,
    expect_json: bool = False,
    **kwargs: Any,
) -> httpx.Response:
    """HTTP request with per-host concurrency cap and exponential backoff.

    Raises the final exception or returns a Response. The caller decides what
    to do with non-2xx responses; we don't raise on 404/403 because some
    sources (Gravatar, GitHub user lookup) use 404 as a meaningful "not found".
    """
    host = httpx.URL(url).host or "_"
    sem = _host_locks[host]
    if sem._value > host_concurrency:
        # Resize down if a later caller wants tighter limits.
        _host_locks[host] = asyncio.Semaphore(host_concurrency)
        sem = _host_locks[host]

    async with sem:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential_jitter(initial=0.5, max=8.0),
            retry=retry_if_exception_type(_RETRYABLE),
            reraise=True,
        ):
            with attempt:
                resp = await client().request(method, url, **kwargs)
                # Retry on 429 / 5xx as well by raising a retryable error.
                # Also retry on 403 when github tells us we're rate-limited
                # (which they signal with x-ratelimit-remaining: 0).
                gh_rate_limited = (
                    resp.status_code == 403
                    and resp.headers.get("x-ratelimit-remaining") == "0"
                )
                if resp.status_code == 429 or resp.status_code >= 500 or gh_rate_limited:
                    # Honor whichever wait signal is most specific.
                    retry_after = resp.headers.get("Retry-After")
                    rl_reset = resp.headers.get("x-ratelimit-reset")
                    sleep_for: float | None = None
                    if retry_after:
                        try:
                            sleep_for = min(float(retry_after), 65)
                        except ValueError:
                            pass
                    if sleep_for is None and rl_reset:
                        try:
                            import time
                            sleep_for = max(0.0, float(rl_reset) - time.time()) + 1
                            sleep_for = min(sleep_for, 65)
                        except ValueError:
                            pass
                    if sleep_for is None:
                        sleep_for = 1 + random.random()
                    await asyncio.sleep(sleep_for)
                    raise httpx.NetworkError(
                        f"{resp.status_code} from {host}"
                    )
                return resp
        # AsyncRetrying always either yields and returns, or reraises.
        raise RuntimeError("unreachable")


async def get(url: str, **kwargs: Any) -> httpx.Response:
    return await request("GET", url, **kwargs)
