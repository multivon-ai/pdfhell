"""Karpathy-style outer loop for pdfhell-research.

  propose → validate → probe (2 models) → full (8 models) → keep/revert

The loop is intentionally short (~250 lines). All the complexity sits
in the support modules (validate, eval, researcher, registry, budget).

Run with::

    python -m pdfhell.research.loop --budget 50 --max-candidates 200

The loop is interruptible: SIGINT cleanly finalises the current
candidate, writes the log row, and exits. A file at
``pdfhell/research/STOP`` will also halt the loop between candidates.
"""
from __future__ import annotations

import argparse
import builtins
import functools
import json
import os
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


# Force unbuffered prints so a long-running loop is observable in real
# time even when stdout is captured (e.g. background process, log
# redirection, CI). We monkey-patch print rather than running with -u
# because the loop is also imported as a library.
print = functools.partial(builtins.print, flush=True)  # noqa: A001

from .budget import Budget, estimate_proposal_cost
from .eval import (
    PanelResult,
    full as eval_full,
    novelty_score,
    probe as eval_probe,
    write_results_row,
)
from .researcher import propose, rotation
from .registry import materialise_candidate, revert_candidate, temporary_register
from .validate import run_all_gates


REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DIR = REPO_ROOT / "pdfhell" / "research"
RESULTS_TSV = RESEARCH_DIR / "results.tsv"
BUDGET_LOG = RESEARCH_DIR / "budget.jsonl"
KEEP_DIR = RESEARCH_DIR / "keep"
STOP_FILE = RESEARCH_DIR / "STOP"

PROGRAM_MD = RESEARCH_DIR / "program.md"
COMMON_PY = REPO_ROOT / "pdfhell" / "generators" / "_common.py"
REFERENCE_PY = REPO_ROOT / "pdfhell" / "generators" / "scale_dependent_rendering.py"


_running = True


def _handle_sigint(signum, frame):
    global _running
    print("\n[loop] SIGINT received — finishing current candidate then exiting")
    _running = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short_id() -> str:
    """Compact ID for a candidate row: YYYYMMDD-HHMMSS-mmm."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d-%H%M%S-") + f"{now.microsecond // 1000:03d}"


def _load_tried_names() -> list[str]:
    """Read every trap_family name ever attempted (from results.tsv).

    Seeds the session-level dedupe set so a new loop run doesn't
    re-propose names that were already evaluated in prior runs.
    """
    if not RESULTS_TSV.exists():
        return []
    names: list[str] = []
    with RESULTS_TSV.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == 0:  # header
                continue
            parts = line.split("\t")
            if len(parts) >= 4 and parts[3]:
                names.append(parts[3])
    return names


def _load_keep_history() -> list[PanelResult]:
    """Load prior kept candidates so novelty can score against them."""
    history: list[PanelResult] = []
    if not KEEP_DIR.exists():
        return history
    for f in sorted(KEEP_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            full = d.get("full_result", {})
            pr = PanelResult(
                trap_family=full.get("trap_family", ""),
                n_cases=full.get("n_cases", 0),
                panel=tuple(full.get("panel", [])),
            )
            pr.per_model_pass = dict(full.get("per_model_pass", {}))
            history.append(pr)
        except Exception:
            continue
    return history


def _persist_kept(
    *,
    candidate_id: str,
    proposal,
    probe_result: PanelResult,
    full_result: PanelResult,
    score: float,
    novelty: float,
    generator_path: Path | None = None,
) -> None:
    """Snapshot a successful candidate to keep/<id>.json + the .py.

    The generator file is *moved* from pdfhell/generators/ to keep/.
    This is the "agent does not get to merge its own work" rule
    enforced in code: the live runtime never sees a candidate until
    a human curator copies it back to pdfhell/generators/ and
    registers it in __init__.py.
    """
    KEEP_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "candidate_id": candidate_id,
        "trap_family": proposal.trap_family,
        "researcher_model": proposal.researcher_model,
        "rationale": proposal.rationale,
        "action": proposal.action,
        "score": round(score, 4),
        "novelty": round(novelty, 4),
        "probe_result": probe_result.to_dict(),
        "full_result": full_result.to_dict(),
        "code": proposal.code,
        "timestamp": _now_iso(),
    }
    out = KEEP_DIR / f"{candidate_id}.json"
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")

    # Move the source file out of the runtime generators directory.
    if generator_path is not None and generator_path.exists():
        staging = KEEP_DIR / f"{proposal.trap_family}.py"
        try:
            generator_path.replace(staging)
        except OSError:
            # Fall back to copy + unlink if rename across filesystems fails.
            staging.write_bytes(generator_path.read_bytes())
            generator_path.unlink(missing_ok=True)


def _candidate_collides(trap_family: str) -> bool:
    """Return True if the agent picked an existing trap_family name."""
    from pdfhell.generators import GENERATORS
    return trap_family in GENERATORS


def run(
    *,
    budget_cap: float,
    max_candidates: int,
    probe_cases: int = 10,
    full_cases: int = 30,
    probe_threshold: float = 0.3,
    convergence_streak: int = 50,
    parallel_models: int = 4,
) -> int:
    """The main loop. Returns process exit code (0 = clean stop)."""
    signal.signal(signal.SIGINT, _handle_sigint)

    budget = Budget(cap_usd=budget_cap, log_path=BUDGET_LOG)
    rotator = rotation()
    history = _load_keep_history()
    best_score_for_family: dict[str, float] = {
        # Anything kept previously sets a floor for that family. v1/v2
        # traps don't appear here — they aren't in keep/ — so the loop
        # is free to discover new mechanics that compete with them.
    }
    consecutive_reverts = 0
    candidate_seed = 100_000  # large to avoid collision with mini-v1/v2 seeds

    print(f"[loop] starting | budget=${budget_cap:.2f} | max={max_candidates} candidates")
    print(f"[loop] research dir: {RESEARCH_DIR}")
    print(f"[loop] keep dir: {KEEP_DIR} ({len(history)} prior survivors)")

    # Track every trap_family name attempted this session so the
    # researcher doesn't burn API spend re-proposing duplicates.
    # Seeded with whatever's already in results.tsv from prior runs.
    tried_names: list[str] = _load_tried_names()

    for i in range(1, max_candidates + 1):
        if not _running:
            break
        if STOP_FILE.exists():
            print("[loop] STOP file detected — exiting cleanly")
            STOP_FILE.unlink(missing_ok=True)
            break
        if budget.remaining < 0.5:  # one cheap probe round costs ~$0.05
            print(f"[loop] budget exhausted (${budget.spent_usd:.2f} spent of ${budget.cap_usd:.2f}); stopping")
            break
        if consecutive_reverts >= convergence_streak:
            print(f"[loop] {convergence_streak} consecutive reverts — design space saturated; stopping")
            break

        candidate_id = _short_id()
        seed_start = candidate_seed
        candidate_seed += 200  # leave headroom: probe + full uses ~40 seeds

        print(f"\n[{i}/{max_candidates}] {candidate_id}  | budget remaining ${budget.remaining:.2f}")

        # ─── PROPOSE ────────────────────────────────────────────────
        try:
            proposal = propose(
                rotator,
                program_md_path=PROGRAM_MD,
                common_py_path=COMMON_PY,
                reference_py_path=REFERENCE_PY,
                results_tsv_path=RESULTS_TSV,
                tried_names=tried_names,
                keep_dir=KEEP_DIR,
            )
        except Exception as exc:
            print(f"  [propose] crashed: {exc}")
            write_results_row(
                RESULTS_TSV,
                timestamp=_now_iso(),
                candidate_id=candidate_id,
                researcher_model="(none)",
                trap_family="",
                status="crash",
                score=0.0, spread=0.0, solvable=False, cost_usd=0.0,
                per_model_pass={},
                rationale=f"propose() raised: {type(exc).__name__}: {exc}",
            )
            consecutive_reverts += 1
            continue

        if proposal is None:
            print("  [propose] no valid proposal from any researcher in rotation")
            write_results_row(
                RESULTS_TSV,
                timestamp=_now_iso(),
                candidate_id=candidate_id,
                researcher_model="(rotation_exhausted)",
                trap_family="",
                status="crash",
                score=0.0, spread=0.0, solvable=False, cost_usd=0.0,
                per_model_pass={},
                rationale="all researchers in rotation returned malformed JSON",
            )
            consecutive_reverts += 1
            continue

        # Account for the proposal cost up front. Doesn't block —
        # researcher calls are cheap relative to evaluation.
        prop_cost = estimate_proposal_cost(proposal.researcher_model)
        budget.commit(f"propose:{proposal.researcher_model}", prop_cost)

        print(f"  [propose] {proposal.researcher_model} → {proposal.trap_family}")
        print(f"  [rationale] {proposal.rationale[:140]}")
        tried_names.append(proposal.trap_family)

        if _candidate_collides(proposal.trap_family):
            # Don't overwrite a v1/v2 trap. Force a rename so the
            # candidate evaluates as a sibling.
            renamed = f"{proposal.trap_family}_alt_{candidate_id[-3:]}"
            print(f"  [rename] {proposal.trap_family} collides; using {renamed}")
            proposal.trap_family = renamed
            proposal.target_path = f"pdfhell/generators/{renamed}.py"
            tried_names.append(renamed)

        # ─── MATERIALISE ────────────────────────────────────────────
        gen_path = materialise_candidate(proposal.code, proposal.trap_family)
        print(f"  [write] {gen_path.relative_to(REPO_ROOT)}")

        try:
            # ─── REGISTER + GATES + EVAL all inside one context ─────
            # The gates inspect generate() through GENERATORS, so they
            # must run inside the temporary_register window. The probe
            # and full rounds materialise PDFs via the suite builder
            # which also reads GENERATORS — same window.
            with temporary_register(proposal.trap_family, gen_path):
                gates = run_all_gates(gen_path, proposal.trap_family, seed_start)
                failed = [g for g in gates if not g.passed]
                if failed:
                    print(f"  [gate FAIL] {failed[0].gate}: {failed[0].reason[:120]}")
                    write_results_row(
                        RESULTS_TSV,
                        timestamp=_now_iso(),
                        candidate_id=candidate_id,
                        researcher_model=proposal.researcher_model,
                        trap_family=proposal.trap_family,
                        status=f"gate_fail:{failed[0].gate}",
                        score=0.0, spread=0.0, solvable=False,
                        cost_usd=prop_cost,
                        per_model_pass={},
                        rationale=proposal.rationale + f" | FAIL: {failed[0].reason[:200]}",
                    )
                    revert_candidate(gen_path)
                    consecutive_reverts += 1
                    continue

                print(f"  [gates] {len(gates)} passed")

                # ─── PROBE ──────────────────────────────────────────────
                probe_result = eval_probe(
                    proposal.trap_family,
                    seed_start=seed_start,
                    n_cases=probe_cases,
                    budget=budget,
                )
                print(
                    f"  [probe] spread={probe_result.spread:.2f}  "
                    f"solvable={probe_result.solvable}  cost=${probe_result.cost_usd:.3f}"
                )

                if probe_result.spread < probe_threshold or not probe_result.solvable:
                    write_results_row(
                        RESULTS_TSV,
                        timestamp=_now_iso(),
                        candidate_id=candidate_id,
                        researcher_model=proposal.researcher_model,
                        trap_family=proposal.trap_family,
                        status="revert_probe",
                        score=0.0,
                        spread=probe_result.spread,
                        solvable=probe_result.solvable,
                        cost_usd=prop_cost + probe_result.cost_usd,
                        per_model_pass=probe_result.per_model_pass,
                        rationale=proposal.rationale,
                    )
                    revert_candidate(gen_path)
                    consecutive_reverts += 1
                    continue

                # ─── FULL ───────────────────────────────────────────
                full_result = eval_full(
                    proposal.trap_family,
                    seed_start=seed_start + probe_cases + 10,  # disjoint seeds
                    n_cases=full_cases,
                    budget=budget,
                )
                novelty = novelty_score(full_result, history)
                final_score = full_result.score(novelty=novelty)
                print(
                    f"  [full] spread={full_result.spread:.2f}  "
                    f"novelty={novelty:.2f}  score={final_score:.2f}  "
                    f"cost=${full_result.cost_usd:.3f}"
                )

                prior_best = best_score_for_family.get(proposal.trap_family, 0.0)
                if final_score > prior_best and final_score > 0:
                    print(f"  [KEEP] {proposal.trap_family} score {final_score:.2f} > prior {prior_best:.2f}")
                    _persist_kept(
                        candidate_id=candidate_id,
                        proposal=proposal,
                        probe_result=probe_result,
                        full_result=full_result,
                        score=final_score,
                        novelty=novelty,
                        generator_path=gen_path,
                    )
                    best_score_for_family[proposal.trap_family] = final_score
                    history.append(full_result)
                    consecutive_reverts = 0
                    status = "keep"
                else:
                    print(f"  [revert] score {final_score:.2f} ≤ prior {prior_best:.2f}")
                    revert_candidate(gen_path)
                    consecutive_reverts += 1
                    status = "revert_full"

                write_results_row(
                    RESULTS_TSV,
                    timestamp=_now_iso(),
                    candidate_id=candidate_id,
                    researcher_model=proposal.researcher_model,
                    trap_family=proposal.trap_family,
                    status=status,
                    score=final_score,
                    spread=full_result.spread,
                    solvable=full_result.solvable,
                    cost_usd=prop_cost + probe_result.cost_usd + full_result.cost_usd,
                    per_model_pass=full_result.per_model_pass,
                    rationale=proposal.rationale,
                )

        except Exception as exc:
            print(f"  [crash] {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=3)
            try:
                write_results_row(
                    RESULTS_TSV,
                    timestamp=_now_iso(),
                    candidate_id=candidate_id,
                    researcher_model=proposal.researcher_model,
                    trap_family=proposal.trap_family,
                    status="crash",
                    score=0.0, spread=0.0, solvable=False,
                    cost_usd=prop_cost,
                    per_model_pass={},
                    rationale=f"{proposal.rationale} | CRASH: {type(exc).__name__}: {exc}",
                )
            finally:
                revert_candidate(gen_path)
                consecutive_reverts += 1

    # ─── Summary ────────────────────────────────────────────────────
    kept = list(KEEP_DIR.glob("*.json")) if KEEP_DIR.exists() else []
    print(f"\n[loop] done | spent ${budget.spent_usd:.2f} of ${budget_cap:.2f}")
    print(f"[loop] keep/: {len(kept)} surviving candidates")
    if RESULTS_TSV.exists():
        n_rows = sum(1 for _ in RESULTS_TSV.open("r", encoding="utf-8")) - 1
        print(f"[loop] results.tsv: {n_rows} candidate attempts")

    # Inline mini-report so the operator doesn't need a second command
    # to see what was discovered. We import lazily so loop.py stays
    # importable in environments that don't need the report stack.
    try:
        from .report import build_summary
        summary = build_summary()
        print(f"\n[loop] ─── session summary ───")
        if summary["theme_convergence"]:
            print("[loop] convergent themes (≥2 researchers, same direction):")
            for theme, info in summary["theme_convergence"].items():
                print(f"  {theme:22s} {info['attempts']:>2d} attempts by {info['distinct_researchers']} researchers")
        if summary["keepers"]:
            print(f"\n[loop] top keepers (ranked by score):")
            for k in summary["keepers"][:5]:
                print(f"  {k['trap_family']:36s} score={k['score']:.2f}  by {k['researcher_model']}")
        print(f"\n[loop] for full breakdown: python -m pdfhell.research.report")
        print(f"[loop] for promotion plan: python -m pdfhell.research.curate --promotion-plan")
    except Exception as exc:
        # Don't let the summary code crash the loop's exit path.
        print(f"[loop] (summary unavailable: {exc})")

    return 0


# ─── CLI ────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="pdfhell-research outer loop. Discover discriminative trap families.",
    )
    parser.add_argument(
        "--budget", type=float, default=50.0,
        help="USD spending cap before the loop forces an exit (default $50).",
    )
    parser.add_argument(
        "--max-candidates", type=int, default=200,
        help="Hard cap on number of proposals to evaluate (default 200).",
    )
    parser.add_argument(
        "--probe-cases", type=int, default=10,
        help="Cases per model in the probe round (default 10).",
    )
    parser.add_argument(
        "--full-cases", type=int, default=30,
        help="Cases per model in the full round (default 30).",
    )
    parser.add_argument(
        "--probe-threshold", type=float, default=0.3,
        help="Minimum probe-round spread to promote a candidate (default 0.3).",
    )
    args = parser.parse_args()
    return run(
        budget_cap=args.budget,
        max_candidates=args.max_candidates,
        probe_cases=args.probe_cases,
        full_cases=args.full_cases,
        probe_threshold=args.probe_threshold,
    )


if __name__ == "__main__":
    sys.exit(main())
