"""Public web-search enrichment source.

Goal: for people we couldn't identify via GitHub/Gravatar/company-domain,
do a name-based public search and extract candidate URLs (Twitter / GitHub /
personal sites). Each found URL is emitted as a low-confidence signal; the
LLM normalizer is what ultimately decides whether to trust them.

Backend: DuckDuckGo HTML (https://html.duckduckgo.com/html/), unauthenticated,
no API key required. We parse the result page with selectolax and pull
href links from the result anchors.

Limitations:
- DDG is rate-limited per IP; we add a small delay and a global concurrency
  cap to stay polite.
- Result parsing is fragile to DDG markup changes — kept defensive.
- Free, but we don't aggressively retry — a missed search just means no signals.
"""
from __future__ import annotations

import logging
import re
import urllib.parse as urlparse
from typing import Any

from selectolax.parser import HTMLParser

from app.schemas import FieldSignal, SourceResult
from app.services import http as http_svc
from app.services.email_domain import classify


log = logging.getLogger(__name__)

DDG_HTML = "https://html.duckduckgo.com/html/"


def _decode_ddg_url(href: str) -> str:
    """DDG wraps real URLs as /l/?uddg=<urlencoded>. Unwrap them."""
    if href.startswith("/l/"):
        parsed = urlparse.urlparse(href)
        qs = urlparse.parse_qs(parsed.query)
        target = qs.get("uddg") or qs.get("u")
        if target:
            return urlparse.unquote(target[0])
    return href


def _classify_url(url: str) -> str | None:
    """Return the FieldSignal field name for a URL, or None to skip."""
    u = url.lower()
    if "linkedin.com/in/" in u:
        # Hard constraint: never store LinkedIn URLs we found via search.
        # The OA explicitly disallows fetching LinkedIn pages but allows
        # storing publicly-known URLs. We choose to skip these entirely so
        # we never look complicit in any LinkedIn workflow.
        return None
    if "github.com/" in u and "/gist" not in u and "/orgs" not in u:
        return "github_url"
    if "twitter.com/" in u or "x.com/" in u:
        # Skip status/post links and shared media; only profiles.
        m = re.match(r"https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]+)/?$", url)
        if m:
            return "twitter_url"
    return None


def _extract_urls(html: str) -> list[str]:
    tree = HTMLParser(html)
    out: list[str] = []
    for a in tree.css("a.result__a"):
        href = a.attributes.get("href") or ""
        if not href:
            continue
        url = _decode_ddg_url(href)
        if url.startswith("http"):
            out.append(url)
    # Fallback selectors for slightly different layouts.
    if not out:
        for a in tree.css("a"):
            href = a.attributes.get("href") or ""
            if href.startswith("/l/"):
                out.append(_decode_ddg_url(href))
    return out


class WebSearchSource:
    name = "web_search"
    weight = 0.55  # discovery-only; LLM is what validates

    async def fetch(self, email: str, name: str) -> SourceResult:
        if not name:
            return SourceResult(source=self.name, raw={"reason": "no_name"})

        info = classify(email)
        # Build a query: for work emails, anchor to the company; for consumer
        # emails, just the name.
        if info.kind == "work" and info.apex_domain:
            query = f'"{name}" "{info.apex_domain}"'
        elif info.kind == "edu" and info.apex_domain:
            query = f'"{name}" "{info.apex_domain}"'
        else:
            query = f'"{name}"'

        try:
            resp = await http_svc.request(
                "POST",
                DDG_HTML,
                data={"q": query, "kl": "us-en"},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"
                    ),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                host_concurrency=2,
                attempts=2,
            )
        except Exception as e:
            log.warning("web_search ddg failed: %s", e)
            return SourceResult(source=self.name, error=str(e))

        if resp.status_code != 200:
            # DDG aggressively challenges scraping — 202 / 403 / 5xx all mean
            # "no usable result." Treat as a clean miss, not an error, so the
            # rest of the pipeline runs unimpeded.
            return SourceResult(
                source=self.name,
                raw={
                    "status": resp.status_code,
                    "query": query,
                    "note": "ddg likely rate-limited / challenged",
                },
            )

        urls = _extract_urls(resp.text)

        signals: list[FieldSignal] = []
        seen_field: dict[str, str] = {}
        snippets: list[str] = []
        for u in urls[:20]:
            field = _classify_url(u)
            if not field or field in seen_field:
                continue
            # Confidence is intentionally low — we haven't verified the URL
            # is for the right person yet. The LLM normalizer cross-checks.
            signals.append(FieldSignal(field=field, value=u, confidence=0.55))
            seen_field[field] = u
            snippets.append(u)

        return SourceResult(
            source=self.name,
            signals=signals,
            raw={
                "query": query,
                "matched_urls": snippets,
                "urls_total": len(urls),
            },
        )
