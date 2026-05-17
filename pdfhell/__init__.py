"""PDF Hell — adversarial PDFs that break AI document readers.

Procedural ground truth, not LLM-as-judge. Each trap family generates PDFs
*from code*, so the answer key is exact and reproducible — no circular
assurance.

Quickstart::

    uvx pdfhell make --trap hidden_ocr_mismatch --seed 42
    uvx pdfhell run --model anthropic:claude-sonnet-4-6 --suite mini
    uvx pdfhell report runs/claude.json --share-card

Build on top of ``multivon-eval`` (the QAG engine, provider adapters, audit
packaging, cost tracking). pdfhell is *only* the adversarial generation
layer; the runtime, scoring, and reporting come from multivon-eval.
"""
from __future__ import annotations

__version__ = "0.1.3"

from .case import HellCase
from .generators import (
    GENERATORS,
    TRAP_FAMILIES,
    generate_case,
)

__all__ = [
    "__version__",
    "HellCase",
    "GENERATORS",
    "TRAP_FAMILIES",
    "generate_case",
]
