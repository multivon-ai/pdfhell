"""Code-based scoring for pdfhell cases.

LLM-as-judge is circular: the same complexity that fools the agent
often fools the judge. pdfhell's primary correctness signal therefore
does *not* go through an LLM. The PDF was generated from code, so the
answer is exactly known and the scorer compares strings directly.

QAG (multivon-eval's :class:`~multivon_eval.DocumentGrounding`) is
available separately as the *explanation* of why a model failed — "the
model returned $19,900.25, matching the hidden-OCR layer rather than
the visible $18,900.25" — but it never affects pass/fail.

Every reported pass rate is paired with a 95% Wilson confidence
interval. A 10-case trap-family run at 100% pass has Wilson 95% CI
[0.72, 1.00] — meaning the *true* per-trap pass rate could plausibly
be as low as 72%. Differences of <~10pp at n=30 are not statistically
distinguishable. We surface the CI everywhere we surface the rate so
nobody draws ordinal conclusions from indistinguishable runs.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from .case import HellCase


# ─── Statistical-rigor utility ─────────────────────────────────────────────

def wilson_ci(passes: int, n: int, *, z: float = 1.959963984540054) -> tuple[float, float]:
    """Return the (lower, upper) Wilson 95% confidence interval for a
    binomial proportion of ``passes`` successes out of ``n`` trials.

    Defaults to z = 1.96 (95% CI). Pass z=2.576 for 99% CI. Returns
    (0.0, 1.0) when ``n == 0`` — vacuous CI for an empty run.

    Why Wilson over the Wald / normal-approximation interval? At our
    sample sizes (n=10 per trap, n=30 per suite) the Wald interval is
    *wrong* near 0 and 1 (it can return negative lower bounds or
    upper bounds > 1, both nonsensical for a probability). Wilson is
    well-behaved across the entire [0, 1] domain and is the standard
    interval for small-sample proportion estimates.
    """
    if n <= 0:
        return (0.0, 1.0)
    p = passes / n
    denom = 1.0 + (z * z) / n
    centre = (p + (z * z) / (2.0 * n)) / denom
    half = (z / denom) * math.sqrt((p * (1.0 - p) + (z * z) / (4.0 * n)) / n)
    lo = max(0.0, centre - half)
    hi = min(1.0, centre + half)
    return (lo, hi)


_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_NORMALIZE_RE = re.compile(r"[.,;:]+\s*$")


def _normalize(s: str) -> str:
    """Loose normalisation for free-text matching: collapse whitespace,
    strip trailing punctuation, lower-case. Money strings stay
    case-irrelevant; trailing periods get stripped so "The answer is
    $18,900.25." matches "$18,900.25"."""
    s = _WHITESPACE_RE.sub(" ", s.strip().lower())
    s = _PUNCT_NORMALIZE_RE.sub("", s)
    return s


def _contains_loose(haystack: str, needle: str) -> bool:
    return _normalize(needle) in _normalize(haystack)


@dataclass(slots=True)
class CaseScore:
    """Score for one (case, model_output) pair.

    ``correct`` is the headline binary signal pdfhell publishes. The
    other fields disambiguate *how* the model got it wrong, which is
    what makes pdfhell useful as a diagnostic tool — not just a number.
    """

    case_id: str
    trap_family: str
    correct: bool
    fell_for_trap: bool
    refused: bool
    matched_expected: bool
    matched_forbidden: list[str] = field(default_factory=list)
    model_output: str = ""
    expected: str = ""
    failure_mode: str = ""  # human-readable, drawn from the case metadata when relevant

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "trap_family": self.trap_family,
            "correct": self.correct,
            "fell_for_trap": self.fell_for_trap,
            "refused": self.refused,
            "matched_expected": self.matched_expected,
            "matched_forbidden": self.matched_forbidden,
            "model_output": self.model_output,
            "expected": self.expected,
            "failure_mode": self.failure_mode,
        }


_REFUSAL_PATTERNS = (
    "i cannot",
    "i can't",
    "unable to",
    "i do not have access",
    "i don't have access",
    "no information",
    "not visible",
    "cannot determine",
    "can't determine",
)


def _looks_like_refusal(output: str) -> bool:
    low = output.strip().lower()
    if len(low) < 4:
        return True
    return any(p in low for p in _REFUSAL_PATTERNS)


def score_case(case: HellCase, model_output: str) -> CaseScore:
    """Score a single (case, model_output) pair using code-based ground truth.

    Decision tree:

    - If the case has :attr:`HellCase.expected_tokens`, the output is
      correct iff *every* token appears (whitespace-/case-tolerant).
      Used for prose-style traps where the right answer can be phrased
      multiple equally-valid ways but the *facts* are fixed (clause
      numbers, dollar amounts, region codes).
    - Otherwise, the output is correct iff it contains
      :attr:`HellCase.expected_answer`. Used for single-value traps
      (dollar amounts, dates, citations).
    - Forbidden-answer detection runs regardless — if the model produces
      a known wrong value, we record the diagnostic. A correct answer
      that *also* contains a forbidden string is still wrong (it means
      the model returned both, which is incoherent and should be flagged).
    - Refusal detection runs last, only on otherwise-wrong outputs.
    """
    if case.expected_tokens:
        matched_expected = all(_contains_loose(model_output, t) for t in case.expected_tokens)
    else:
        matched_expected = _contains_loose(model_output, case.expected_answer)
    # When a case uses ``expected_tokens`` (prose answers), the
    # ``forbidden_answer`` is often a literal substring of any complete
    # correct answer (e.g. the body-only phrase is contained inside a
    # full body+footnote summary). If all tokens matched, the model
    # demonstrably captured the right facts; ignore the substring
    # signal. For single-value traps (hidden OCR amount, table cell),
    # expected and forbidden are mutually exclusive by construction, so
    # the check stays active.
    if case.expected_tokens and matched_expected:
        matched_forbidden: list[str] = []
    else:
        matched_forbidden = [
            f for f in case.forbidden_answers if _contains_loose(model_output, f)
        ]
    correct = matched_expected and not matched_forbidden
    refused = (not matched_expected) and (not matched_forbidden) and _looks_like_refusal(model_output)
    fell_for_trap = bool(matched_forbidden) and not matched_expected
    failure_mode = ""
    if fell_for_trap:
        failure_mode = case.metadata.get("expected_failure_mode", "")
    return CaseScore(
        case_id=case.id,
        trap_family=case.trap_family,
        correct=correct,
        fell_for_trap=fell_for_trap,
        refused=refused,
        matched_expected=matched_expected,
        matched_forbidden=matched_forbidden,
        model_output=model_output,
        expected=case.expected_answer,
        failure_mode=failure_mode,
    )


@dataclass(slots=True)
class SuiteReport:
    """Aggregate scoring summary for a run.

    Designed to serialise to the leaderboard JSON multivon.ai already
    consumes (one entry per (suite, model, judge) tuple).
    """

    model: str
    suite: str
    n: int
    pass_rate: float
    per_trap_pass: dict[str, float]
    per_trap_fell_for_trap: dict[str, float]
    refused_rate: float
    cases: list[CaseScore] = field(default_factory=list)
    suite_version: str = ""  # e.g. "mini-v1" — see pdfhell.suite.SuiteSpec.version
    suite_hash: str = ""  # 8-char SHA-256 prefix of the sorted (trap, seed) pairs

    # ─── Confidence intervals ──────────────────────────────────────────────

    @property
    def pass_rate_ci(self) -> tuple[float, float]:
        """95% Wilson confidence interval on the overall pass rate."""
        return wilson_ci(int(round(self.pass_rate * self.n)), self.n)

    @property
    def per_trap_pass_ci(self) -> dict[str, tuple[float, float]]:
        """Per-trap-family Wilson 95% CIs.

        Uses the actual case counts (typically 10 per family in the mini
        suite). Surfaced on the leaderboard so 100% pass on n=10 isn't
        confused with "the model never fails."
        """
        if not self.cases:
            return {}
        # Count cases per family rather than guessing.
        by_family: dict[str, list[CaseScore]] = {}
        for c in self.cases:
            by_family.setdefault(c.trap_family, []).append(c)
        out: dict[str, tuple[float, float]] = {}
        for family, scores in by_family.items():
            passes = sum(1 for s in scores if s.correct)
            out[family] = wilson_ci(passes, len(scores))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "suite": self.suite,
            "suite_version": self.suite_version,
            "suite_hash": self.suite_hash,
            "n": self.n,
            "pass_rate": self.pass_rate,
            "pass_rate_ci": list(self.pass_rate_ci),
            "per_trap_pass": self.per_trap_pass,
            "per_trap_pass_ci": {k: list(v) for k, v in self.per_trap_pass_ci.items()},
            "per_trap_fell_for_trap": self.per_trap_fell_for_trap,
            "refused_rate": self.refused_rate,
            "cases": [c.to_dict() for c in self.cases],
        }

    def worst_failures(self, k: int = 5) -> list[CaseScore]:
        """Return up to ``k`` cases that fell into the designed trap.

        Useful for the launch share-card: "Worst failures: hidden-OCR
        mismatch caught the model 8/10 times."
        """
        return [c for c in self.cases if c.fell_for_trap][:k]


def summarise(model: str, suite: str, scores: list[CaseScore]) -> SuiteReport:
    if not scores:
        return SuiteReport(model=model, suite=suite, n=0, pass_rate=0.0,
                           per_trap_pass={}, per_trap_fell_for_trap={}, refused_rate=0.0, cases=[])
    by_trap: dict[str, list[CaseScore]] = {}
    for s in scores:
        by_trap.setdefault(s.trap_family, []).append(s)
    per_trap_pass = {
        trap: sum(c.correct for c in cs) / len(cs)
        for trap, cs in by_trap.items()
    }
    per_trap_fell = {
        trap: sum(c.fell_for_trap for c in cs) / len(cs)
        for trap, cs in by_trap.items()
    }
    return SuiteReport(
        model=model,
        suite=suite,
        n=len(scores),
        pass_rate=sum(c.correct for c in scores) / len(scores),
        per_trap_pass=per_trap_pass,
        per_trap_fell_for_trap=per_trap_fell,
        refused_rate=sum(c.refused for c in scores) / len(scores),
        cases=scores,
    )
