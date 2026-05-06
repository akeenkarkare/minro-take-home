"""Gravatar enrichment source.

Gravatar is keyed on md5(lowercase(email)). For users who have a Gravatar
profile attached to that email it returns a structured JSON profile with
display name, location, bio, profile URL, avatar, and a list of linked
"verified accounts" (Twitter/X, GitHub, etc.).

The avatar URL alone is high signal — it's the photo the user has
explicitly chosen to associate with that email, anywhere on the web that
uses Gravatar (most of the dev-tools ecosystem).

Endpoints used:
- GET https://gravatar.com/{md5}.json     -> profile JSON (404 if not set)
- GET https://gravatar.com/avatar/{md5}?d=404  -> 404 if no custom avatar

We hit the JSON endpoint first; if that 404s but the avatar endpoint returns
200, we still emit the avatar (the user has a photo but no profile).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.schemas import FieldSignal, SourceResult
from app.services import http as http_svc


log = logging.getLogger(__name__)


def _hash(email: str) -> str:
    return hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()


def _twitter_url_from_account(account: dict[str, Any]) -> str | None:
    if account.get("shortname") in ("twitter", "x"):
        url = account.get("url")
        if url:
            return url
        username = account.get("username")
        if username:
            return f"https://x.com/{username.lstrip('@')}"
    return None


def _github_url_from_account(account: dict[str, Any]) -> str | None:
    if account.get("shortname") == "github":
        url = account.get("url")
        if url:
            return url
        username = account.get("username")
        if username:
            return f"https://github.com/{username}"
    return None


class GravatarSource:
    name = "gravatar"
    weight = 0.85

    async def fetch(self, email: str, name: str) -> SourceResult:
        h = _hash(email)
        profile_url = f"https://gravatar.com/{h}.json"

        signals: list[FieldSignal] = []
        raw: dict[str, Any] = {}

        try:
            resp = await http_svc.get(profile_url, host_concurrency=8)
        except Exception as e:
            return SourceResult(source=self.name, error=str(e))

        if resp.status_code == 404:
            # No profile JSON. Check if there's at least a custom avatar.
            avatar_url = f"https://gravatar.com/avatar/{h}?d=404&s=256"
            try:
                avatar_resp = await http_svc.get(avatar_url, host_concurrency=8)
                if avatar_resp.status_code == 200:
                    signals.append(
                        FieldSignal(
                            field="avatar_url",
                            value=f"https://gravatar.com/avatar/{h}?s=256",
                            confidence=0.95,
                            evidence={"matched": "avatar_only"},
                        )
                    )
            except Exception:
                pass
            return SourceResult(source=self.name, signals=signals, raw={"matched": bool(signals)})

        if resp.status_code != 200:
            return SourceResult(source=self.name, raw={"http_status": resp.status_code})

        try:
            payload = resp.json()
        except Exception:
            return SourceResult(source=self.name, raw={"parse_error": True})

        # Newer Gravatar API returns the profile object directly; older API
        # nests it under entry: [{...}]. Handle both.
        profile: dict[str, Any] | None = None
        if isinstance(payload, dict):
            entries = payload.get("entry")
            if isinstance(entries, list) and entries:
                profile = entries[0]
            else:
                profile = payload
        if not profile:
            return SourceResult(source=self.name, raw={"empty": True})

        raw = profile

        # avatar_url
        avatar = profile.get("avatar_url") or (
            profile.get("thumbnailUrl")
            or (profile.get("photos") or [{}])[0].get("value")
        )
        if avatar:
            signals.append(
                FieldSignal(field="avatar_url", value=avatar, confidence=0.95)
            )

        # bio (Gravatar calls this `description` or `aboutMe`).
        bio = profile.get("description") or profile.get("aboutMe")
        if bio:
            signals.append(FieldSignal(field="bio", value=bio, confidence=0.85))

        # location
        location = profile.get("location") or profile.get("currentLocation")
        if location:
            signals.append(
                FieldSignal(field="location", value=location, confidence=0.8)
            )

        # job / company are sometimes structured under `job_title` / `company`.
        job_title = profile.get("job_title")
        if job_title:
            signals.append(FieldSignal(field="title", value=job_title, confidence=0.85))

        company = profile.get("company")
        if company:
            signals.append(FieldSignal(field="company", value=company, confidence=0.8))

        # Linked accounts (verified accounts in old API; "verified_accounts" in new).
        accounts = (
            profile.get("verified_accounts")
            or profile.get("accounts")
            or []
        )
        for acct in accounts:
            t = _twitter_url_from_account(acct)
            if t:
                signals.append(FieldSignal(field="twitter_url", value=t, confidence=0.9))
            g = _github_url_from_account(acct)
            if g:
                signals.append(FieldSignal(field="github_url", value=g, confidence=0.9))

        return SourceResult(source=self.name, signals=signals, raw=raw)
