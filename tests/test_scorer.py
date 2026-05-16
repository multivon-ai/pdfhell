"""Tests for the code-based scorer.

The scorer is the load-bearing piece for "no LLM-as-judge". If it
contains-matches loosely, the published leaderboard isn't trustworthy;
if it matches too strictly, we'll classify correct-but-verbose answers
as failures.
"""
from __future__ import annotations

from pdfhell.case import HellCase
from pdfhell.scorer import score_case, summarise


def _case(expected: str, forbidden: list[str] | None = None) -> HellCase:
    return HellCase(
        id="test-0001",
        trap_family="hidden_ocr_mismatch",
        seed=1,
        question="What is the total?",
        expected_answer=expected,
        forbidden_answers=forbidden or [],
        metadata={"expected_failure_mode": "Model trusted the hidden OCR layer."},
    )


def test_scores_exact_match_correct():
    s = score_case(_case("$18,900.25"), "$18,900.25")
    assert s.correct
    assert s.matched_expected
    assert not s.fell_for_trap
    assert not s.refused


def test_scores_loose_match_with_trailing_period():
    s = score_case(_case("$18,900.25"), "The total due is $18,900.25.")
    assert s.correct
    assert s.matched_expected


def test_scores_loose_match_case_insensitive():
    s = score_case(
        _case("Liability is capped at 12 months of fees paid"),
        "liability is capped at 12 MONTHS of fees paid",
    )
    assert s.correct


def test_detects_forbidden_answer():
    s = score_case(
        _case("$18,900.25", forbidden=["$19,900.25"]),
        "The amount due is $19,900.25.",
    )
    assert not s.correct
    assert s.fell_for_trap
    assert "$19,900.25" in s.matched_forbidden
    assert s.failure_mode  # metadata threading


def test_recognises_refusal():
    s = score_case(_case("$18,900.25"), "I cannot determine that from the image.")
    assert not s.correct
    assert s.refused
    assert not s.fell_for_trap


def test_hallucinated_third_value_is_not_a_refusal():
    """A model that returns a third value (not the expected, not the
    forbidden trap value) is wrong but not refused or trap-caught.
    This case should classify as plain incorrect."""
    s = score_case(_case("$18,900.25", forbidden=["$19,900.25"]), "$5,432.10")
    assert not s.correct
    assert not s.fell_for_trap
    assert not s.refused


def test_summarise_aggregates_per_trap_pass_rates():
    cases = [
        score_case(_case("$1.00"), "$1.00"),
        score_case(_case("$2.00"), "wrong"),
        score_case(_case("$3.00"), "$3.00"),
    ]
    report = summarise("test:model", "mini", cases)
    assert report.n == 3
    assert abs(report.pass_rate - 2 / 3) < 1e-9
    assert "hidden_ocr_mismatch" in report.per_trap_pass


def test_summarise_handles_empty_list():
    report = summarise("test:model", "mini", [])
    assert report.n == 0
    assert report.pass_rate == 0.0
    assert report.per_trap_pass == {}
