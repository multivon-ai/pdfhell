"""Suite builder.

Suites are sets of (PDF, case-JSON) pairs on disk. A suite is fully
described by ``SuiteSpec`` — a deterministic recipe — so anyone with
the suite name and ``pdfhell`` can re-derive byte-identical PDFs and
answer keys.

This is part of the "code-based ground truth" promise: the suite isn't
a static blob, it's a recipe + a verifiable hash.
"""
from __future__ import annotations

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
    """

    name: str
    traps: dict[str, list[int]] = field(default_factory=dict)

    @property
    def total_cases(self) -> int:
        return sum(len(s) for s in self.traps.values())


def mini_suite() -> SuiteSpec:
    """The canonical ``mini`` suite: 30 cases, 10 per trap family.

    Seeds are arbitrary but fixed. The published leaderboard at
    ``multivon.ai/leaderboard`` runs this exact spec — re-running it on
    any machine produces identical PDFs.
    """
    return SuiteSpec(
        name="mini",
        traps={
            "hidden_ocr_mismatch":     list(range(1001, 1011)),
            "footnote_override":       list(range(2001, 2011)),
            "split_table_across_pages": list(range(3001, 3011)),
        },
    )


SUITES: dict[str, SuiteSpec] = {
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
