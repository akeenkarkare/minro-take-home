"""Company-domain enrichment source.

For work emails, fetch the company's homepage and extract:
- company name from <title>, og:site_name, or JSON-LD Organization
- company description from meta description / og:description / JSON-LD
- company logo from og:image, apple-touch-icon, or JSON-LD logo
- the apex domain (free — already in EmailInfo)

Also probes Clearbit Logo API (free, unauthenticated, no per-lookup cost) for
a clean square logo URL.

This source produces NO `name`/`bio`/`title` for the *person* — it's strictly
about company-side fields. Person-side enrichment from the company website
(e.g. /team/ or /about/ pages mentioning the user) is intentionally out of
scope here; the LLM normalizer can do that later if we feed it the raw HTML.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.schemas import FieldSignal, SourceResult
from app.services import http as http_svc
from app.services.email_domain import classify


log = logging.getLogger(__name__)


def _clean_title(title: str) -> str:
    """Strip common boilerplate suffixes from <title> tags."""
    if not title:
        return title
    for sep in (" | ", " — ", " - ", " • ", " :: "):
        if sep in title:
            # The first segment is usually the brand; the rest is filler.
            first, _, rest = title.partition(sep)
            if len(first) >= 3 and len(first) <= 80:
                return first.strip()
    return title.strip()


def _extract_meta(tree: HTMLParser, name: str) -> str | None:
    for sel in (
        f'meta[name="{name}"]',
        f'meta[property="{name}"]',
        f'meta[property="og:{name}"]',
    ):
        node = tree.css_first(sel)
        if node:
            content = node.attributes.get("content")
            if content:
                return content.strip()
    return None


def _extract_jsonld_organization(tree: HTMLParser) -> dict[str, Any] | None:
    import json as _json

    for node in tree.css('script[type="application/ld+json"]'):
        text = node.text(strip=True)
        if not text:
            continue
        try:
            data = _json.loads(text)
        except Exception:
            continue
        # JSON-LD can be a list, a single dict, or wrapped in @graph.
        candidates: list[dict] = []
        if isinstance(data, list):
            candidates = [d for d in data if isinstance(d, dict)]
        elif isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                candidates.extend(d for d in graph if isinstance(d, dict))
            else:
                candidates.append(data)
        for c in candidates:
            t = c.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(
                str(x).lower() in ("organization", "corporation", "localbusiness")
                for x in types
            ):
                return c
    return None


async def _fetch_homepage(domain: str) -> tuple[str, str] | None:
    """Try https://{domain} and https://www.{domain}; return (url, html) or None."""
    urls = [f"https://{domain}", f"https://www.{domain}"]

    async def _try(url: str) -> tuple[str, str] | None:
        try:
            resp = await http_svc.get(url, host_concurrency=10)
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype.lower():
            return None
        return (str(resp.url), resp.text)

    # Race them; take the first one to succeed.
    tasks = [asyncio.create_task(_try(u)) for u in urls]
    try:
        for finished in asyncio.as_completed(tasks):
            res = await finished
            if res:
                # Cancel the other.
                for t in tasks:
                    if not t.done():
                        t.cancel()
                return res
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
    return None


async def _clearbit_logo(domain: str) -> str | None:
    """Free, unauthenticated. 200 → URL is a valid logo."""
    url = f"https://logo.clearbit.com/{domain}"
    try:
        resp = await http_svc.request("HEAD", url, host_concurrency=8, attempts=2)
    except Exception:
        return None
    if resp.status_code == 200:
        return url
    return None


class CompanyDomainSource:
    name = "company_domain"
    weight = 0.85

    async def fetch(self, email: str, name: str) -> SourceResult:
        info = classify(email)
        domain = info.likely_company_domain
        if not domain:
            return SourceResult(source=self.name, raw={"reason": f"non-work email ({info.kind})"})

        signals: list[FieldSignal] = []
        raw: dict[str, Any] = {"domain": domain, "kind": info.kind}

        # The domain itself is high-confidence — it came from the email.
        signals.append(
            FieldSignal(
                field="company_domain",
                value=domain,
                confidence=0.95,
                evidence={"reason": "email_apex"},
            )
        )

        # Clearbit logo and homepage HTML in parallel.
        logo_task = asyncio.create_task(_clearbit_logo(domain))
        page_task = asyncio.create_task(_fetch_homepage(domain))
        logo_url, page = await asyncio.gather(logo_task, page_task)

        if logo_url:
            signals.append(
                FieldSignal(
                    field="company_logo_url",
                    value=logo_url,
                    confidence=0.95,
                    evidence={"source": "clearbit_logo"},
                )
            )
            raw["clearbit_logo"] = logo_url

        if page:
            page_url, html = page
            tree = HTMLParser(html)
            raw["page_url"] = page_url

            # JSON-LD Organization is the highest-quality structured signal.
            jsonld = _extract_jsonld_organization(tree)
            if jsonld:
                raw["jsonld_organization"] = {
                    k: v
                    for k, v in jsonld.items()
                    if k in ("name", "description", "logo", "url", "sameAs")
                }
                if isinstance(jsonld.get("name"), str):
                    signals.append(
                        FieldSignal(
                            field="company",
                            value=jsonld["name"],
                            confidence=0.95,
                            evidence={"source": "jsonld_organization"},
                        )
                    )
                desc = jsonld.get("description")
                if isinstance(desc, str) and desc.strip():
                    signals.append(
                        FieldSignal(
                            field="company_description",
                            value=desc.strip(),
                            confidence=0.95,
                            evidence={"source": "jsonld_organization"},
                        )
                    )
                logo = jsonld.get("logo")
                logo_url_jsonld: str | None = None
                if isinstance(logo, str):
                    logo_url_jsonld = logo
                elif isinstance(logo, dict):
                    logo_url_jsonld = logo.get("url") or logo.get("@id")
                if logo_url_jsonld:
                    if logo_url_jsonld.startswith("/"):
                        logo_url_jsonld = urljoin(page_url, logo_url_jsonld)
                    signals.append(
                        FieldSignal(
                            field="company_logo_url",
                            value=logo_url_jsonld,
                            confidence=0.97,
                            evidence={"source": "jsonld_organization"},
                        )
                    )

            # Fall back to <title> + <meta> if JSON-LD didn't supply a field.
            title_node = tree.css_first("title")
            site_title = title_node.text(strip=True) if title_node else None
            cleaned_title = _clean_title(site_title) if site_title else None
            if cleaned_title and not any(s.field == "company" for s in signals):
                signals.append(
                    FieldSignal(
                        field="company",
                        value=cleaned_title,
                        confidence=0.8,
                        evidence={"source": "<title>"},
                    )
                )

            og_site_name = _extract_meta(tree, "og:site_name")
            if og_site_name and not any(s.field == "company" for s in signals):
                signals.append(
                    FieldSignal(
                        field="company",
                        value=og_site_name,
                        confidence=0.85,
                        evidence={"source": "og:site_name"},
                    )
                )

            description = _extract_meta(tree, "description") or _extract_meta(
                tree, "og:description"
            )
            if (
                description
                and len(description) > 20
                and not any(s.field == "company_description" for s in signals)
            ):
                signals.append(
                    FieldSignal(
                        field="company_description",
                        value=description,
                        confidence=0.85,
                        evidence={"source": "meta:description"},
                    )
                )

            og_image = _extract_meta(tree, "og:image")
            if og_image:
                if og_image.startswith("/"):
                    og_image = urljoin(page_url, og_image)
                # Only emit if we don't already have a higher-confidence logo
                # — og:image is sometimes a hero shot, not a logo.
                if not any(s.field == "company_logo_url" for s in signals):
                    signals.append(
                        FieldSignal(
                            field="company_logo_url",
                            value=og_image,
                            confidence=0.7,
                            evidence={"source": "og:image"},
                        )
                    )

        return SourceResult(source=self.name, signals=signals, raw=raw)
