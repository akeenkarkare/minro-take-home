"""Tests for email-domain classification."""
from __future__ import annotations

from app.services.email_domain import classify


def test_gmail_is_consumer() -> None:
    info = classify("akeenkarkare@gmail.com")
    assert info.kind == "consumer"
    assert info.is_consumer is True
    assert info.likely_company_domain is None


def test_work_email_extracts_apex() -> None:
    info = classify("sid@clodo.ai")
    assert info.kind == "work"
    assert info.apex_domain == "clodo.ai"
    assert info.likely_company_domain == "clodo.ai"


def test_edu_email() -> None:
    info = classify("darsheel.s.sanghavi.th@dartmouth.edu")
    assert info.kind == "edu"
    assert info.is_edu is True
    assert info.apex_domain == "dartmouth.edu"


def test_subdomain_work_email_apex() -> None:
    # learn.deepgram.com -> apex deepgram.com
    info = classify("marketing@learn.deepgram.com")
    # local part `marketing` is a role address; that wins over work.
    assert info.kind == "role"
    assert info.apex_domain == "deepgram.com"


def test_role_local_part() -> None:
    info = classify("info@example.com")
    assert info.kind == "role"
    assert info.is_role is True


def test_invalid_email() -> None:
    info = classify("not-an-email")
    assert info.kind == "invalid"
    assert info.likely_company_domain is None


def test_capitalization_normalized() -> None:
    info = classify("Foo@GMAIL.com")
    assert info.kind == "consumer"
    assert info.email == "foo@gmail.com"
