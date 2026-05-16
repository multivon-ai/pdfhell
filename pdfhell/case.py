"""Canonical case representation for a generated pdfhell trap.

A ``HellCase`` is the serialisable artifact that every trap-family generator
returns. The runner consumes these; the scoring layer treats
``expected_answer`` as code-based ground truth and grades the model's
free-text output against it. QAG (multivon-eval's
:class:`~multivon_eval.DocumentGrounding`) is layered on as the
*explanation* of why a particular answer scored a particular way — not as
the score itself. This is the architectural fix the Round-7 churned design
partner demanded: no LLM-judges-LLM circular assurance for the primary
correctness signal.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class HellCase:
    """One adversarial PDF + its ground truth.

    Attributes
    ----------
    id: stable, deterministic, e.g. ``"hidden_ocr_mismatch-0042"``.
    trap_family: one of :data:`pdfhell.generators.TRAP_FAMILIES`.
    seed: integer seed used to generate the case. Regenerating with the
        same seed produces a byte-identical PDF and identical answer key.
    question: the user-facing question the model must answer.
    expected_answer: a human-readable form of the correct answer used in
        reports + JUnit output. For single-value traps this is also the
        substring the scorer looks for; for prose-style traps (e.g.
        :mod:`pdfhell.generators.footnote_override`) the scorer instead
        uses :attr:`expected_tokens` (see below).
    expected_tokens: optional list of substrings that ALL must appear in
        the model's output for the case to count as correct. Used by
        traps where the right answer can be expressed multiple
        equally-valid ways (e.g. a list of clause carve-outs in any
        order). When empty, the scorer falls back to a contains-match
        against ``expected_answer``.
    forbidden_answers: optional list of plausible-but-wrong answers the
        trap aims to elicit (e.g. the hidden-OCR amount). Used by the
        scorer to detect the specific failure mode the trap was designed
        for.
    pdf_path: location of the generated PDF (relative to the suite root).
    metadata: extra fields — number of pages, font size of footnotes,
        the literal hidden-OCR string, etc. Useful for diagnostics and
        for trap-family-specific scorers.
    """

    id: str
    trap_family: str
    seed: int
    question: str
    expected_answer: str
    forbidden_answers: list[str] = field(default_factory=list)
    expected_tokens: list[str] = field(default_factory=list)
    pdf_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # ─── serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HellCase":
        return cls(
            id=raw["id"],
            trap_family=raw["trap_family"],
            seed=int(raw["seed"]),
            question=raw["question"],
            expected_answer=raw["expected_answer"],
            forbidden_answers=list(raw.get("forbidden_answers", [])),
            expected_tokens=list(raw.get("expected_tokens", [])),
            pdf_path=raw.get("pdf_path", ""),
            metadata=dict(raw.get("metadata", {})),
        )

    def dump_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load_json(cls, path: str | Path) -> "HellCase":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
