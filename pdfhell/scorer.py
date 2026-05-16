"""Code-based scoring for pdfhell cases.

The Round-7 churned design partner's complaint was that "LLM-judges-LLM"
is circular assurance — the same complexity that fools the agent also
fools the QAG judge. pdfhell's primary correctness signal therefore does
*not* go through an LLM. The PDF was generated from code, so the answer
is exactly known and the scorer compares strings directly.

The QAG layer (multivon-eval's :class:`~multivon_eval.DocumentGrounding`)
is invoked separately as the *explanation* of why the model failed —
"the model claimed the visible amount was $18,900.25 but the answer it
returned was $19,900.25, matching the hidden-OCR layer" — not as the
score itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .case import HellCase


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

    - If the model output contains the ``expected_answer``: ``correct=True``.
      We use "contains" loosely because frontier models reliably wrap
      single-word answers in pleasantries ("The total due is $18,900.25.").
    - Otherwise, if the output contains any of the ``forbidden_answers``:
      ``correct=False``, ``fell_for_trap=True``. The trap caught a
      diagnosable failure mode.
    - Otherwise, if the output looks like a refusal: ``correct=False``,
      ``refused=True``.
    - Otherwise: ``correct=False``, none of the above flags — the model
      hallucinated some third value.
    """
    matched_expected = _contains_loose(model_output, case.expected_answer)
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "suite": self.suite,
            "n": self.n,
            "pass_rate": self.pass_rate,
            "per_trap_pass": self.per_trap_pass,
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
