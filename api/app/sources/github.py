"""GitHub enrichment source.

Strategy:
1. Try to find the user's GitHub login by:
   a. /search/users?q={email}+in:email   (direct, when profile email is public)
   b. /search/commits?q=author-email:{email}  (commits expose private emails)
   c. /search/users?q={name}+type:user  (name fallback; lower confidence)
2. Once we have a login, /users/{login} gives the canonical fields.
3. /users/{login}/orgs gives extra company hints.

Confidence calibration:
- email/commit-corroborated login: 0.95 effective for fields we read directly.
- name-only match: clamped to 0.6 effective per signal so the orchestrator
  treats it as "best guess".

API rate limits:
- Authenticated: 5,000 req/hr core, 30 req/min search.
- We're conservative: per-source semaphore (set in the orchestrator) caps us.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.schemas import FieldSignal, SourceResult
from app.services import http as http_svc


log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def _headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = settings().github_token
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _commits_headers() -> dict[str, str]:
    # Commit search needs an explicit Accept (cloak preview is now GA but the
    # docs still show this Accept; the standard JSON accept also works for
    # commit search now, so we just use the standard headers).
    return _headers()


async def _gh_get(path: str, params: dict[str, Any] | None = None) -> httpx.Response:
    return await http_svc.get(
        f"{GITHUB_API}{path}", params=params, headers=_headers(), host_concurrency=5
    )


def _name_tokens(name: str) -> list[str]:
    return [t.lower() for t in re.split(r"\s+", name.strip()) if t]


def _name_matches(candidate: str | None, target: str) -> bool:
    """Loose match: every token of target appears in candidate (case-insensitive)."""
    if not candidate:
        return False
    cand = candidate.lower()
    return all(t in cand for t in _name_tokens(target))


async def _find_login_by_email(email: str) -> tuple[str, str] | None:
    """Return (login, how_found) or None."""
    # 1) profile-email search
    try:
        resp = await _gh_get("/search/users", params={"q": f"{email} in:email"})
        if resp.status_code == 200:
            items = resp.json().get("items") or []
            if items:
                return items[0]["login"], "profile_email"
    except Exception:
        log.exception("github email search failed")

    # 2) commits search — finds users whose commits used this email even if
    # their profile email is private.
    try:
        resp = await http_svc.get(
            f"{GITHUB_API}/search/commits",
            params={"q": f"author-email:{email}", "per_page": 5},
            headers=_commits_headers(),
            host_concurrency=5,
        )
        if resp.status_code == 200:
            items = resp.json().get("items") or []
            for item in items:
                author = (item.get("author") or {})
                login = author.get("login")
                if login:
                    return login, "commits_email"
    except Exception:
        log.exception("github commits search failed")

    return None


async def _find_login_by_name(name: str) -> str | None:
    """Best-effort name search. Returns a login only if the top hit's name
    actually contains all of the target's tokens."""
    try:
        resp = await _gh_get(
            "/search/users", params={"q": f'"{name}" type:user', "per_page": 5}
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("items") or []
        for item in items:
            login = item.get("login")
            if not login:
                continue
            # We need the user's full name to compare — search results don't
            # include `name`, so we have to read /users/{login}.
            try:
                user_resp = await _gh_get(f"/users/{login}")
            except Exception:
                continue
            if user_resp.status_code != 200:
                continue
            full_name = (user_resp.json() or {}).get("name") or ""
            if _name_matches(full_name, name):
                return login
    except Exception:
        log.exception("github name search failed")
    return None


async def _read_user(login: str) -> dict[str, Any] | None:
    try:
        resp = await _gh_get(f"/users/{login}")
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


async def _read_orgs(login: str) -> list[dict[str, Any]]:
    try:
        resp = await _gh_get(f"/users/{login}/orgs")
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    return resp.json() or []


def _signals_from_user(
    user: dict[str, Any], orgs: list[dict[str, Any]], how_found: str
) -> list[FieldSignal]:
    """Map a GitHub user payload to FieldSignals.

    `how_found` controls the confidence floor.
    """
    # When the login was found via email or commits, we trust that the user
    # is the right person. A name-only match gets a confidence cap.
    high_trust = how_found in ("profile_email", "commits_email")
    cap = 1.0 if high_trust else 0.6

    sigs: list[FieldSignal] = []
    evidence_base = {"login": user.get("login"), "matched_via": how_found}

    def add(field, value, conf):
        if value is None or value == "":
            return
        sigs.append(
            FieldSignal(
                field=field,
                value=value,
                confidence=min(conf, cap),
                evidence=evidence_base,
            )
        )

    # github_url is essentially canonical given a login.
    if user.get("html_url"):
        add("github_url", user["html_url"], 0.99)
    if user.get("avatar_url"):
        add("avatar_url", user["avatar_url"], 0.99)
    if user.get("bio"):
        add("bio", user["bio"], 0.9)
    if user.get("location"):
        add("location", user["location"], 0.85)

    # GitHub `company` field is conventionally "@orgname" or freeform text,
    # but people sometimes paste URLs in there. Skip URL-like values; let
    # downstream sources or the LLM normalizer recover the actual company.
    company = user.get("company")
    if company:
        cleaned = company.strip().lstrip("@")
        looks_like_url = bool(re.match(r"https?://|www\.", cleaned))
        if not looks_like_url:
            looks_like_handle = bool(re.fullmatch(r"[A-Za-z0-9-]+", cleaned))
            add("company", cleaned, 0.9 if looks_like_handle else 0.7)

    twitter = user.get("twitter_username")
    if twitter:
        add("twitter_url", f"https://x.com/{twitter}", 0.9)

    # We cannot reliably infer `title` from a GitHub profile — bio sometimes
    # contains it but it's noisy. Skip; let the LLM normalizer derive it from
    # the raw signal we hand it.

    # Orgs: if the user has exactly one public org, use its login as a soft
    # company hint *only if* the profile didn't already supply company.
    # Org `description` is freeform and often a URL or tagline, so we use
    # the org slug — at least it's stable and identifiable.
    if not user.get("company") and len(orgs) == 1:
        org_login = orgs[0].get("login")
        if org_login:
            add("company", org_login, 0.6)

    return sigs


class GitHubSource:
    name = "github"
    weight = 0.95

    async def fetch(self, email: str, name: str) -> SourceResult:
        # 1) login lookup
        login_result = await _find_login_by_email(email)
        if login_result:
            login, how = login_result
        else:
            login = await _find_login_by_name(name) if name else None
            how = "name_match" if login else "not_found"

        if not login:
            return SourceResult(source=self.name, raw={"matched": False})

        user = await _read_user(login)
        if not user:
            return SourceResult(
                source=self.name, raw={"matched": False, "login_attempted": login}
            )

        orgs = await _read_orgs(login)
        # If the matched user's `name` field is present and incompatible with
        # the target name, the email/commit match is still the source of
        # truth — but a name-only match should be discarded.
        if how == "name_match" and not _name_matches(user.get("name"), name):
            return SourceResult(
                source=self.name,
                raw={"matched": False, "rejected_login": login, "reason": "name_mismatch"},
            )

        signals = _signals_from_user(user, orgs, how)
        return SourceResult(
            source=self.name,
            signals=signals,
            raw={
                "matched": True,
                "matched_via": how,
                "login": login,
                "user": user,
                "orgs": [{"login": o.get("login"), "url": o.get("url")} for o in orgs],
            },
        )
