"""Trap-family generators.

Each generator is a deterministic ``(seed) -> (pdf_bytes, HellCase)``
function. The mapping :data:`GENERATORS` powers ``pdfhell make --trap X``
and the suite builder. Adding a new trap family means registering it
here.

Why a registry and not subclasses? Each trap is fundamentally a *small*
parameterised generator. The registry keeps generators portable, makes
the CLI's ``--trap`` flag introspectable, and avoids the class-hierarchy
sprawl that a 50-trap eventual suite would otherwise turn into.
"""
from __future__ import annotations

from typing import Callable

from ..case import HellCase
from .hidden_ocr_mismatch import generate as _hidden_ocr_mismatch
from .footnote_override import generate as _footnote_override
from .split_table_across_pages import generate as _split_table_across_pages
from .composite_trap import generate as _composite_trap
from .scale_dependent_rendering import generate as _scale_dependent_rendering
from .cross_page_coreference import generate as _cross_page_coreference


# Signature: (seed: int) -> (pdf_bytes: bytes, case: HellCase).
# The case's pdf_path is set by the suite-builder after writing the bytes.
GeneratorFn = Callable[[int], tuple[bytes, HellCase]]

GENERATORS: dict[str, GeneratorFn] = {
    # mini-v1 (kept for back-compat with the published 2026-05 leaderboard)
    "hidden_ocr_mismatch": _hidden_ocr_mismatch,
    "footnote_override": _footnote_override,
    "split_table_across_pages": _split_table_across_pages,
    # mini-v2 (2026-05-23): adversarial against current SOTA. Each
    # combines / extends a v1 mechanism in a way that defeats the top
    # cluster (Sonnet 4-6, Gemini-Pro variants, GPT-5.4) which had
    # plateau'd at 90-97% on v1.
    "composite_trap": _composite_trap,
    "scale_dependent_rendering": _scale_dependent_rendering,
    "cross_page_coreference": _cross_page_coreference,
}

TRAP_FAMILIES: tuple[str, ...] = tuple(GENERATORS.keys())


def generate_case(trap_family: str, seed: int) -> tuple[bytes, HellCase]:
    """Generate one case from ``trap_family`` with the given ``seed``.

    Raises :class:`KeyError` for an unknown trap family — the CLI catches
    this and prints the list of available families.
    """
    if trap_family not in GENERATORS:
        raise KeyError(
            f"unknown trap family {trap_family!r}; available: {', '.join(TRAP_FAMILIES)}"
        )
    return GENERATORS[trap_family](seed)


__all__ = ["GENERATORS", "TRAP_FAMILIES", "generate_case", "GeneratorFn"]
