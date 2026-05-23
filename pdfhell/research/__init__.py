"""pdfhell-research — autoresearch-style discovery loop for adversarial traps.

Inspired by Andrej Karpathy's ``autoresearch`` (single-file optimization
loop over an ML training program). We adapt the same pattern:

  propose → validate → evaluate → keep/revert → log

Differences from upstream:
  - Multi-modal: candidates are PDF generators, evaluated against the
    vision panel via :mod:`pdfhell.runner`.
  - Discrimination as metric: we don't minimise a loss, we maximise
    disagreement *across* models gated by solvability.
  - Multi-researcher: a rotation of strong reasoning models proposes
    candidates so the search doesn't collapse into one model's biases.

The brief lives in :file:`program.md`. Read that first.

CLI: ``python -m pdfhell.research.loop --budget 50``.
"""
from __future__ import annotations

from .budget import Budget, PER_CASE_USD, estimate_run_cost
from .eval import FULL_PANEL, PROBE_PANEL, PanelResult, evaluate_candidate
from .researcher import RESEARCHER_ROTATION, Proposal


__all__ = [
    "Budget",
    "FULL_PANEL",
    "PROBE_PANEL",
    "PanelResult",
    "PER_CASE_USD",
    "Proposal",
    "RESEARCHER_ROTATION",
    "estimate_run_cost",
    "evaluate_candidate",
]
