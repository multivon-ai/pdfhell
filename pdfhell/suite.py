"""Suite builder.

Suites are sets of (PDF, case-JSON) pairs on disk. A suite is fully
described by ``SuiteSpec`` — a deterministic recipe — so anyone with
the suite name and ``pdfhell`` can re-derive byte-identical PDFs and
answer keys.

This is part of the "code-based ground truth" promise: the suite isn't
a static blob, it's a recipe + a verifiable hash.

# Versioning

Suites are versioned (e.g. ``mini-v1``) so adding a new trap family
doesn't silently invalidate published leaderboard numbers. Each suite
also carries a :attr:`SuiteSpec.suite_hash` — an 8-char SHA-256 prefix
of the sorted ``(trap_family, seed)`` pairs. Two runs with the same
``suite_hash`` measured the *exact* same cases; runs with different
hashes are not directly comparable. The hash is included in every
``SuiteReport`` and the audit pack ``manifest.json``.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .case import HellCase
from .generators import generate_case


@dataclass(slots=True)
class SuiteSpec:
    """Recipe for a reproducible suite.

    ``traps`` maps a trap family name to a list of seeds — those exact
    seeds produce those exact PDFs. Run ``pdfhell build-suite --suite
    mini`` to materialise to disk.

    ``version`` is the human-readable label that gets published in
    leaderboard rows (e.g. ``mini-v1``). Bump the version (and the name)
    when adding trap families so historical comparisons stay valid.
    """

    name: str
    traps: dict[str, list[int]] = field(default_factory=dict)
    version: str = ""

    @property
    def total_cases(self) -> int:
        return sum(len(s) for s in self.traps.values())

    @property
    def suite_hash(self) -> str:
        """8-char SHA-256 prefix of the sorted ``(trap, seed)`` pairs.

        Two suites with the same ``suite_hash`` evaluated the EXACT same
        cases; runs across different hashes are not directly comparable.
        Surfaced in every SuiteReport + the audit-pack manifest.
        """
        items = sorted(
            (trap, seed)
            for trap, seeds in self.traps.items()
            for seed in seeds
        )
        payload = "\n".join(f"{trap}\t{seed}" for trap, seed in items).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:8]


def mini_suite() -> SuiteSpec:
    """The canonical ``mini-v1`` suite: 30 cases, 10 per trap family.

    Seeds are arbitrary but fixed. The published leaderboard at
    ``multivon.ai/leaderboard`` runs this exact spec — re-running it on
    any machine produces identical PDFs.

    Versioning: adding a new trap family to the mini suite produces a
    new spec (``mini-v2``, etc.). Older leaderboard rows tagged
    ``mini-v1`` remain directly comparable across machines, dates, and
    judge versions; rows tagged different versions are not.
    """
    return SuiteSpec(
        name="mini",
        version="mini-v1",
        traps={
            "hidden_ocr_mismatch":      list(range(1001, 1011)),
            "footnote_override":        list(range(2001, 2011)),
            "split_table_across_pages": list(range(3001, 3011)),
        },
    )


def smoke_suite() -> SuiteSpec:
    """3-case quick-run for first-time users — one case per trap family.

    Useful for ``uvx pdfhell run --suite smoke`` — runs in ~10 seconds
    on Gemini Flash, costs fractions of a cent, and exercises every
    trap family so a new user can see all three failure modes without
    waiting for the full 30-case mini suite. Same seeds as the first
    case in each mini-suite family, so smoke results are a strict
    subset of mini results.
    """
    return SuiteSpec(
        name="smoke",
        version="smoke-v1",
        traps={
            "hidden_ocr_mismatch":      [1001],
            "footnote_override":        [2001],
            "split_table_across_pages": [3001],
        },
    )


SUITES: dict[str, SuiteSpec] = {
    "smoke": smoke_suite(),
    "mini": mini_suite(),
}


def build_suite(spec: SuiteSpec, out_dir: Path) -> list[HellCase]:
    """Materialise a suite to ``out_dir``.

    Writes ``<case_id>.pdf`` and ``<case_id>.json`` pairs. Returns the
    list of generated cases (with ``pdf_path`` set so callers can
    serialise an index).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cases: list[HellCase] = []
    for trap_family, seeds in spec.traps.items():
        for seed in seeds:
            pdf_bytes, case = generate_case(trap_family, seed)
            pdf_path = out_dir / f"{case.id}.pdf"
            pdf_path.write_bytes(pdf_bytes)
            case.pdf_path = pdf_path.name  # relative — runners join with cases_dir
            case.dump_json(out_dir / f"{case.id}.json")
            cases.append(case)
    return cases


def iter_cases(cases_dir: Path) -> Iterable[HellCase]:
    """Read every case from a materialised suite directory."""
    for json_path in sorted(cases_dir.glob("*.json")):
        yield HellCase.load_json(json_path)
