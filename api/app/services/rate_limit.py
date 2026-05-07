"""Process-wide token-bucket rate limiters.

Each named bucket throttles its associated calls to a steady rate, regardless
of how many concurrent tasks try to call. This is what makes the pipeline
behave at scale: GitHub's 30 search/min ceiling is enforced *before* we
make the request, so we never burn rate budget on retries.

A token-bucket with `rate` tokens/second and capacity `burst` allows up to
`burst` calls in a window, then steady-state at `rate`. Calls block until
a token is available.
"""
from __future__ import annotations

import asyncio
import time


class TokenBucket:
    def __init__(self, rate_per_sec: float, burst: int) -> None:
        self.rate = rate_per_sec
        self.capacity = burst
        self.tokens = float(burst)
        self.last = time.monotonic()
        self._lock = asyncio.Lock()

    async def take(self, n: float = 1.0) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self.tokens = min(
                    self.capacity, self.tokens + (now - self.last) * self.rate
                )
                self.last = now
                if self.tokens >= n:
                    self.tokens -= n
                    return
                wait = (n - self.tokens) / self.rate
            # Sleep outside the lock so other callers can also wait.
            await asyncio.sleep(wait)


_buckets: dict[str, TokenBucket] = {}


def bucket(name: str, *, rate_per_sec: float, burst: int) -> TokenBucket:
    b = _buckets.get(name)
    if b is None:
        b = TokenBucket(rate_per_sec, burst)
        _buckets[name] = b
    return b


# Pre-registered buckets for known external services. Adjust rate/burst per
# the published limit, leaving headroom.
GITHUB_SEARCH = bucket(
    "github_search",
    # 30 searches per 60s authenticated. Use 25/60 = 0.42/s with burst 5
    # so a small burst of 5 is fine but steady-state stays under the limit.
    rate_per_sec=25 / 60,
    burst=5,
)
GITHUB_CORE = bucket(
    "github_core",
    # 5000/hr core endpoints. 5000/3600 = 1.39/s with burst 20.
    rate_per_sec=5000 / 3600,
    burst=20,
)
