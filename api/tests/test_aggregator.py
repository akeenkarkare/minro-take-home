"""Tests for the signal aggregator.

Pure-logic, no I/O. These pin the math behind confidence scoring.
"""
from __future__ import annotations

from app.schemas import FieldSignal, SourceResult
from app.services.aggregator import aggregate


def _result(name: str, **fields: tuple[str | None, float]) -> SourceResult:
    """Build a SourceResult shorthand: kwarg field=(value, confidence)."""
    return SourceResult(
        source=name,
        signals=[
            FieldSignal(field=f, value=v, confidence=c) for f, (v, c) in fields.items()
        ],
    )


def test_picks_highest_effective_confidence() -> None:
    weights = {"github": 0.95, "search": 0.4}
    results = [
        _result("github", title=("Co-Founder", 0.9), company=("Acme", 0.95)),
        _result("search", title=("Engineer", 0.95)),  # search * 0.95 = 0.38 < 0.85
    ]
    agg = aggregate(results, weights)
    assert agg.fields["title"] == "Co-Founder"
    assert agg.fields["company"] == "Acme"


def test_null_signal_does_not_pick_field() -> None:
    weights = {"src": 1.0}
    results = [_result("src", title=(None, 0.0))]
    agg = aggregate(results, weights)
    assert agg.fields["title"] is None
    assert agg.field_confidence["title"] == 0.0


def test_unknown_source_gets_default_weight() -> None:
    # Fall-back weight is 0.5 — a source not in the registry shouldn't crash.
    results = [_result("mystery", title=("X", 0.8))]
    agg = aggregate(results, {})
    assert agg.fields["title"] == "X"
    assert agg.field_confidence["title"] == 0.4  # 0.5 * 0.8


def test_overall_is_importance_weighted_mean_of_attempted() -> None:
    weights = {"src": 1.0}
    # Two strong fields, but only those two attempted.
    results = [_result("src", title=("CEO", 1.0), company=("Acme", 1.0))]
    agg = aggregate(results, weights)
    # Both fields max confidence -> overall confidence is 1.0.
    assert agg.overall_confidence == 1.0


def test_sources_only_include_contributors() -> None:
    weights = {"a": 1.0, "b": 1.0, "c": 1.0}
    results = [
        _result("a", title=("X", 0.9)),
        _result("b"),  # contributes nothing
        SourceResult(source="c", error="boom"),
    ]
    agg = aggregate(results, weights)
    assert agg.sources == ["a"]


def test_field_confidence_is_clamped() -> None:
    # Pathological input: weight 2.0 * confidence 0.9 = 1.8, must clamp to 1.0.
    weights = {"src": 2.0}
    results = [_result("src", title=("X", 0.9))]
    agg = aggregate(results, weights)
    assert agg.field_confidence["title"] == 1.0
