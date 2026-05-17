"""Tests for the statistical-rigor additions: Wilson CIs + suite versioning.

The professor-persona review of pdfhell flagged two methodology gaps:
single-point pass rates without confidence intervals, and unversioned
suites that mutate as we add trap families. These tests guard the
fixes.
"""
from __future__ import annotations

import pytest

from pdfhell.case import HellCase
from pdfhell.scorer import score_case, summarise, wilson_ci
from pdfhell.suite import SUITES, mini_suite, smoke_suite


# ─── Wilson CI math ────────────────────────────────────────────────────────


def test_wilson_ci_perfect_score_small_n():
    """10/10 passes — the CI lower bound is well below 1.0 (small-sample
    uncertainty). This is the case that motivated adding CIs in the
    first place — a per-trap 10/10 is not statistically distinguishable
    from a true rate of 75%."""
    lo, hi = wilson_ci(10, 10)
    assert 0.65 < lo < 0.80, f"unexpected lower bound: {lo}"
    assert hi == pytest.approx(1.0)


def test_wilson_ci_zero_score_small_n():
    """0/10 passes — symmetric to the 10/10 case. Upper bound is well
    above 0.0."""
    lo, hi = wilson_ci(0, 10)
    assert lo == pytest.approx(0.0)
    assert 0.20 < hi < 0.35


def test_wilson_ci_thirty_case_ci_width():
    """The mini-suite n=30 at 28/30 (93%) — Wilson CI width must be wide
    enough that 28/30 vs 29/30 is NOT clearly separable. This guards
    against accidentally tightening to a narrower interval (e.g. Wald)
    that would mislead users."""
    lo_28, hi_28 = wilson_ci(28, 30)
    lo_29, hi_29 = wilson_ci(29, 30)
    # The two intervals overlap substantially.
    assert lo_29 < hi_28, "97% vs 93% CIs should overlap at n=30"


def test_wilson_ci_empty_run_is_vacuous():
    """n=0 → CI is the full [0, 1]. Don't crash on empty runs."""
    lo, hi = wilson_ci(0, 0)
    assert lo == 0.0
    assert hi == 1.0


def test_wilson_ci_z_parameter():
    """99% CI is wider than 95% CI for the same data."""
    lo95, hi95 = wilson_ci(7, 10)
    lo99, hi99 = wilson_ci(7, 10, z=2.576)
    assert lo99 < lo95
    assert hi99 > hi95


# ─── Suite versioning ──────────────────────────────────────────────────────


def test_mini_suite_is_versioned():
    spec = mini_suite()
    assert spec.version == "mini-v1"
    assert spec.suite_hash, "suite_hash must be set"
    assert len(spec.suite_hash) == 8


def test_smoke_suite_is_versioned():
    spec = smoke_suite()
    assert spec.version == "smoke-v1"
    assert spec.suite_hash


def test_suite_hash_is_deterministic():
    """Same trap-seed contents → same hash."""
    a = mini_suite().suite_hash
    b = mini_suite().suite_hash
    assert a == b


def test_suite_hash_differs_with_different_seeds():
    """Mutating the seeds changes the hash. Adding a new trap family
    must not silently keep the same suite_hash."""
    a = mini_suite()
    b = mini_suite()
    b.traps["new_trap_family"] = [9001]
    assert a.suite_hash != b.suite_hash


def test_suites_registered():
    assert "mini" in SUITES
    assert "smoke" in SUITES
    assert SUITES["mini"].version == "mini-v1"


# ─── SuiteReport CI integration ────────────────────────────────────────────


def _make_case(expected: str) -> HellCase:
    return HellCase(
        id="t-0001",
        trap_family="hidden_ocr_mismatch",
        seed=1,
        question="x?",
        expected_answer=expected,
    )


def test_suite_report_carries_pass_rate_ci():
    cases = [score_case(_make_case("$1.00"), "$1.00") for _ in range(10)]
    cases += [score_case(_make_case("$2.00"), "wrong") for _ in range(5)]
    report = summarise("test:model", "mini", cases)
    lo, hi = report.pass_rate_ci
    assert 0.0 <= lo <= report.pass_rate <= hi <= 1.0


def test_suite_report_to_dict_includes_cis_and_version():
    cases = [score_case(_make_case("$1.00"), "$1.00") for _ in range(3)]
    report = summarise("test:model", "mini", cases)
    report.suite_version = "mini-v1"
    report.suite_hash = "deadbeef"
    d = report.to_dict()
    assert "pass_rate_ci" in d
    assert "per_trap_pass_ci" in d
    assert d["suite_version"] == "mini-v1"
    assert d["suite_hash"] == "deadbeef"
    # CIs are lists not tuples (JSON-friendly).
    assert isinstance(d["pass_rate_ci"], list)
    assert len(d["pass_rate_ci"]) == 2


def test_per_trap_ci_uses_actual_case_counts():
    """Per-trap CI must reflect the number of cases in that family.
    Mixing families with different N counts shouldn't collapse to one
    aggregate."""
    cases = [
        # 10 hidden_ocr passes
        *[score_case(_make_case("$1.00"), "$1.00") for _ in range(10)],
    ]
    report = summarise("test:model", "mini", cases)
    cis = report.per_trap_pass_ci
    assert "hidden_ocr_mismatch" in cis
    lo, hi = cis["hidden_ocr_mismatch"]
    # 10/10 at n=10 → lower bound ~0.72
    assert 0.65 < lo < 0.80
