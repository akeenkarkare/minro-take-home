"""Email-domain classification.

Decides whether an email is a personal/consumer address, a school address,
a role address, or a work address — and extracts the apex company domain
when it's a work email. The downstream company-website source uses this to
decide whether to even try fetching the user's domain.

Tiny, deterministic, and very useful: most "I have no idea who this person is"
cases hinge on a correct call here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import tldextract


# Curated consumer-email domains. Keep tight — when in doubt, classify as
# "work" so the company-domain source at least tries. False negatives (work
# email mis-classified as consumer) are worse than false positives.
_CONSUMER_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.uk",
        "yahoo.co.in",
        "yahoo.ca",
        "ymail.com",
        "rocketmail.com",
        "hotmail.com",
        "hotmail.co.uk",
        "outlook.com",
        "outlook.in",
        "live.com",
        "msn.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "aol.com",
        "protonmail.com",
        "proton.me",
        "pm.me",
        "fastmail.com",
        "fastmail.fm",
        "zoho.com",
        "tutanota.com",
        "gmx.com",
        "gmx.net",
        "mail.com",
        "yandex.com",
        "yandex.ru",
        "qq.com",
        "163.com",
        "126.com",
        "duck.com",
    }
)


_ROLE_LOCAL_PARTS = frozenset(
    {
        "info",
        "hello",
        "contact",
        "team",
        "support",
        "help",
        "admin",
        "sales",
        "marketing",
        "press",
        "media",
        "careers",
        "jobs",
        "billing",
        "noreply",
        "no-reply",
        "do-not-reply",
        "office",
        "hi",
        "hey",
    }
)


EmailKind = Literal["consumer", "edu", "work", "role", "invalid"]


@dataclass(frozen=True)
class EmailInfo:
    """Structured breakdown of an email address."""

    email: str
    local_part: str
    domain: str          # full host portion ("foo.bar.com")
    apex_domain: str     # "bar.com" — registrable domain via PSL
    is_consumer: bool
    is_edu: bool
    is_role: bool
    kind: EmailKind

    @property
    def likely_company_domain(self) -> str | None:
        """The domain to treat as the user's company website, if any."""
        if self.kind == "work":
            return self.apex_domain
        return None


def classify(email: str) -> EmailInfo:
    e = email.strip().lower()
    if "@" not in e:
        return EmailInfo(
            email=e,
            local_part="",
            domain="",
            apex_domain="",
            is_consumer=False,
            is_edu=False,
            is_role=False,
            kind="invalid",
        )

    local_part, _, domain = e.rpartition("@")

    # tldextract gives us suffix-aware parsing without us shipping a TLD list.
    parts = tldextract.extract(domain)
    apex = ".".join(p for p in (parts.domain, parts.suffix) if p)

    is_consumer = domain in _CONSUMER_DOMAINS or apex in _CONSUMER_DOMAINS
    is_edu = apex.endswith(".edu") or domain.endswith(".edu") or domain.endswith(".ac.uk") or domain.endswith(".edu.in")
    is_role = local_part in _ROLE_LOCAL_PARTS

    if is_consumer:
        kind: EmailKind = "consumer"
    elif is_edu:
        kind = "edu"
    elif is_role:
        kind = "role"
    elif not apex:
        kind = "invalid"
    else:
        kind = "work"

    return EmailInfo(
        email=e,
        local_part=local_part,
        domain=domain,
        apex_domain=apex,
        is_consumer=is_consumer,
        is_edu=is_edu,
        is_role=is_role,
        kind=kind,
    )
