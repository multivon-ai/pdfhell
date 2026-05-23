"""Discrimination scoring for trap-family candidates.

A candidate generator is *valuable* iff it makes models disagree. We
measure that disagreement directly:

    spread     = pass_rate_max - pass_rate_min   across the eval panel
    solvable   = pass_rate_max >= 0.7            some model must succeed
    score      = spread if solvable else 0

Plus a **novelty** bonus computed against the panel-pass-rate vector of
the existing v1/v2 traps — a candidate that splits the panel along a
new axis beats one that re-splits along an existing axis.

The expensive bit is the model panel runs themselves. This module just
orchestrates them; the actual vision calls go through ``pdfhell.runner``.
"""
from __future__ import annotations

import json
import math
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from pdfhell.runner import run_suite
from pdfhell.suite import build_suite, SuiteSpec
from pdfhell.scorer import SuiteReport

from .budget import Budget, estimate_run_cost


# ─── Panels ─────────────────────────────────────────────────────────────

# Probe round: 2 cheap models. Discriminative signal here is enough to
# decide whether to spend on the full round.
PROBE_PANEL: tuple[str, ...] = (
    "anthropic:claude-haiku-4-5",
    "google:gemini-2.5-flash",
)

# Full round: 8 models. Spans cheap→frontier and the three providers
# whose vision pipelines are known to differ in rasterization behaviour.
FULL_PANEL: tuple[str, ...] = (
    "anthropic:claude-haiku-4-5",
    "anthropic:claude-sonnet-4-6",
    "anthropic:claude-opus-4-7",
    "openai:gpt-4o",
    "openai:gpt-5",
    "google:gemini-flash-lite-latest",
    "google:gemini-2.5-flash",
    "google:gemini-2.5-pro",
)


# ─── Data types ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class PanelResult:
    """One trap family run against one panel.

    ``per_model_pass`` is the per-model pass rate, keyed by model spec.
    Everything else is derived from that vector.
    """

    trap_family: str
    n_cases: int
    panel: tuple[str, ...]
    per_model_pass: dict[str, float] = field(default_factory=dict)
    refused: dict[str, float] = field(default_factory=dict)
    cost_usd: float = 0.0
    crashed_models: list[str] = field(default_factory=list)

    @property
    def pass_max(self) -> float:
        if not self.per_model_pass:
            return 0.0
        return max(self.per_model_pass.values())

    @property
    def pass_min(self) -> float:
        if not self.per_model_pass:
            return 0.0
        return min(self.per_model_pass.values())

    @property
    def spread(self) -> float:
        return self.pass_max - self.pass_min

    @property
    def solvable(self) -> bool:
        # Demand >=70% from the best model. Anything lower means the
        # trap is ambiguous or the question is unfairly hard.
        return self.pass_max >= 0.70

    def score(self, *, novelty: float = 1.0) -> float:
        """Discrimination score, gated by solvability and weighted by novelty."""
        if not self.solvable:
            return 0.0
        return self.spread * novelty

    def to_dict(self) -> dict:
        return {
            "trap_family": self.trap_family,
            "n_cases": self.n_cases,
            "panel": list(self.panel),
            "per_model_pass": dict(self.per_model_pass),
            "refused": dict(self.refused),
            "cost_usd": round(self.cost_usd, 4),
            "crashed_models": list(self.crashed_models),
            "pass_max": round(self.pass_max, 3),
            "pass_min": round(self.pass_min, 3),
            "spread": round(self.spread, 3),
            "solvable": self.solvable,
        }


# ─── Building cases for a candidate ────────────────────────────────────


def build_candidate_cases(
    trap_family: str,
    seed_start: int,
    n_cases: int,
    out_dir: Path,
) -> int:
    """Materialise ``n_cases`` PDFs for ``trap_family`` into ``out_dir``.

    Uses ``pdfhell.suite.build_suite`` so the on-disk layout exactly
    matches what the runner expects. Returns the number of cases
    actually written (a generator that raises on some seeds may
    silently drop them — that's OK for research, the loop logs it).
    """
    seeds = list(range(seed_start, seed_start + n_cases))
    spec = SuiteSpec(
        name=f"research-{trap_family}",
        version=f"research-{trap_family}",
        traps={trap_family: seeds},
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = build_suite(spec, out_dir)
    return len(cases)


# ─── Running one model against a candidate ──────────────────────────────


def _run_one_model(
    cases_dir: Path,
    model_spec: str,
) -> tuple[str, SuiteReport | None, Exception | None]:
    try:
        # progress=False is critical — the runner's per-case print
        # output spams logs when we're running many candidates.
        report = run_suite(
            cases_dir,
            model_spec,
            workers=4,
            progress=False,
            suite_name="research",
        )
        return model_spec, report, None
    except Exception as exc:  # provider errors, rate limits, etc.
        return model_spec, None, exc


def evaluate_candidate(
    trap_family: str,
    *,
    panel: Sequence[str],
    n_cases: int,
    seed_start: int,
    budget: Budget,
    parallel_models: int = 4,
) -> PanelResult:
    """Run a candidate trap-family through ``panel``.

    ``trap_family`` must already be registered in
    ``pdfhell.generators.GENERATORS`` — call ``registry.register_candidate``
    first.

    Budget is consulted *before* each model is dispatched. If the
    estimated cost would push us over the daily cap, the model is
    skipped and recorded as ``crashed_models`` with reason='budget'.
    The candidate is still scored on whichever models did complete —
    sometimes the discrimination signal is obvious from a 2-model
    probe, so a partial run is more useful than no run at all.
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"pdfhell-research-{trap_family}-"))
    try:
        n_written = build_candidate_cases(trap_family, seed_start, n_cases, tmp)
        if n_written == 0:
            return PanelResult(
                trap_family=trap_family,
                n_cases=0,
                panel=tuple(panel),
                crashed_models=list(panel),
            )

        result = PanelResult(
            trap_family=trap_family,
            n_cases=n_written,
            panel=tuple(panel),
        )

        # Pre-flight budget check per model. Crude but effective.
        dispatched: list[str] = []
        for model in panel:
            est = estimate_run_cost(model, n_written)
            if not budget.can_spend(est):
                result.crashed_models.append(model)
                continue
            dispatched.append(model)
            budget.reserve(est)

        # Parallelise across models — each is independent.
        with ThreadPoolExecutor(max_workers=parallel_models) as pool:
            futures = {
                pool.submit(_run_one_model, tmp, m): m for m in dispatched
            }
            for fut in as_completed(futures):
                model, report, exc = fut.result()
                if exc is not None or report is None:
                    result.crashed_models.append(model)
                    continue
                result.per_model_pass[model] = report.pass_rate
                result.refused[model] = report.refused_rate
                actual = estimate_run_cost(model, n_written)
                result.cost_usd += actual
                budget.commit(model, actual)

        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─── Novelty against existing traps ─────────────────────────────────────


def novelty_score(
    candidate: PanelResult,
    history: list[PanelResult],
) -> float:
    """1.0 = orthogonal to every prior trap; 0.0 = redundant.

    Implementation: cosine distance between this candidate's
    per-model-pass vector and the nearest prior trap's vector. Two
    traps that defeat the *same* model on the panel get high cosine
    similarity → low novelty. A trap that defeats a model nobody else
    defeats gets low similarity → high novelty.

    Why cosine and not, say, euclidean: we care about the *pattern* of
    discrimination, not the absolute pass rates. A trap with [0.9,
    0.1, 0.9, 0.1, 0.9] and one with [0.7, 0.0, 0.8, 0.0, 0.7]
    discriminate the *same models*; novelty between them should be
    low even though their euclidean distance is non-trivial.
    """
    if not history:
        return 1.0
    if not candidate.per_model_pass:
        return 0.0
    # Build a stable model ordering across all priors + candidate so
    # vectors are comparable.
    models = sorted({m for p in history for m in p.per_model_pass} |
                    set(candidate.per_model_pass.keys()))

    def vec(p: PanelResult) -> list[float]:
        return [p.per_model_pass.get(m, 0.5) for m in models]  # 0.5 = missing data

    cand_v = vec(candidate)
    cand_norm = math.sqrt(sum(x * x for x in cand_v)) or 1.0

    min_distance = 1.0
    for prior in history:
        prior_v = vec(prior)
        prior_norm = math.sqrt(sum(x * x for x in prior_v)) or 1.0
        dot = sum(a * b for a, b in zip(cand_v, prior_v))
        sim = dot / (cand_norm * prior_norm)
        dist = 1.0 - sim  # 0 (identical) .. 2 (opposite). We clamp.
        min_distance = min(min_distance, dist)
    return max(0.0, min(1.0, min_distance))


# ─── Convenience: probe + full ──────────────────────────────────────────


def probe(
    trap_family: str,
    *,
    seed_start: int,
    n_cases: int,
    budget: Budget,
) -> PanelResult:
    """Cheap 2-model probe. Discrimination must clear 0.3 to promote."""
    return evaluate_candidate(
        trap_family,
        panel=PROBE_PANEL,
        n_cases=n_cases,
        seed_start=seed_start,
        budget=budget,
    )


def full(
    trap_family: str,
    *,
    seed_start: int,
    n_cases: int,
    budget: Budget,
) -> PanelResult:
    """Full 8-model run. Only run after the probe round promotes."""
    return evaluate_candidate(
        trap_family,
        panel=FULL_PANEL,
        n_cases=n_cases,
        seed_start=seed_start,
        budget=budget,
    )


def write_results_row(
    tsv_path: Path,
    *,
    timestamp: str,
    candidate_id: str,
    researcher_model: str,
    trap_family: str,
    status: str,
    score: float,
    spread: float,
    solvable: bool,
    cost_usd: float,
    per_model_pass: dict[str, float],
    rationale: str,
) -> None:
    """Append one row to results.tsv. Creates the file with a header if
    it doesn't exist yet. The file is the research trail — never
    rewrite past rows."""
    header = [
        "timestamp", "candidate_id", "researcher_model", "trap_family",
        "status", "score", "spread", "solvable", "cost_usd",
        "per_model_pass", "rationale",
    ]
    write_header = not tsv_path.exists()
    tsv_path.parent.mkdir(parents=True, exist_ok=True)
    with tsv_path.open("a", encoding="utf-8") as f:
        if write_header:
            f.write("\t".join(header) + "\n")
        # Sanitise rationale so a stray tab/newline doesn't corrupt the TSV.
        clean_rationale = rationale.replace("\t", " ").replace("\n", " ").strip()
        row = [
            timestamp,
            candidate_id,
            researcher_model,
            trap_family,
            status,
            f"{score:.4f}",
            f"{spread:.4f}",
            "1" if solvable else "0",
            f"{cost_usd:.4f}",
            json.dumps(per_model_pass, separators=(",", ":"), sort_keys=True),
            clean_rationale[:500],
        ]
        f.write("\t".join(row) + "\n")
