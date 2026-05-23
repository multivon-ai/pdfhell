"""``python -m pdfhell.research.curate`` — promote keepers into mini-vN.

The research loop discovers candidates but doesn't merge them. This
CLI is the human curator's tool. For each ``keep/<id>.json``:

1. **Confirmation re-run.** Materialise the generator from the kept
   `code` field, run a fresh evaluation with disjoint seeds against
   the full panel. If the spread holds up (within 0.15 of the
   original), the trap is *robust* — random seeds didn't game the
   number. If the spread collapses, the trap is *fragile* — likely
   over-fit to specific seed values, do not promote.

2. **Write a promotion report.** A markdown summary the curator can
   paste into a CHANGELOG entry, plus a generator-merge plan
   (target path, suggested seed range for mini-vN).

This tool does NOT auto-merge into ``pdfhell/generators/__init__.py``
— the final merge is a human commit. We surface the decision; you
make the call.

Run with::

    python -m pdfhell.research.curate                       # report all
    python -m pdfhell.research.curate --keeper <id>         # one keeper
    python -m pdfhell.research.curate --confirm <id>        # re-run eval
    python -m pdfhell.research.curate --promotion-plan      # mini-vN plan
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Iterable

from .budget import Budget, estimate_run_cost
from .eval import FULL_PANEL, PanelResult, evaluate_candidate
from .registry import temporary_register


RESEARCH_DIR = Path(__file__).resolve().parent
KEEP_DIR = RESEARCH_DIR / "keep"


def _load_keeper(candidate_id: str) -> dict | None:
    path = KEEP_DIR / f"{candidate_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _iter_keepers() -> Iterable[dict]:
    for f in sorted(KEEP_DIR.glob("*.json")):
        try:
            yield json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue


def _confirmation_run(
    keeper: dict,
    *,
    n_cases: int = 20,
    budget_cap: float = 5.0,
) -> PanelResult | None:
    """Re-evaluate a keeper with fresh seeds against the full panel.

    Uses the keeper's stored ``code`` to rematerialise the generator
    in a temp location (not pdfhell/generators/, so the v1/v2 runtime
    never sees it). Disjoint seeds: start at 9_000_000 + keeper's
    original seed range, so this run can never re-test the same case.
    """
    trap_family = keeper["trap_family"]
    code = keeper["code"]

    # Write the generator to a temporary place under pdfhell/generators/
    # because the suite-builder imports from that package path. Restore
    # any prior file at that location on exit.
    target = Path(__file__).resolve().parents[1] / "generators" / f"{trap_family}.py"
    existing = target.read_bytes() if target.exists() else None
    target.write_text(code, encoding="utf-8")

    budget = Budget(cap_usd=budget_cap)
    try:
        with temporary_register(trap_family, target):
            result = evaluate_candidate(
                trap_family,
                panel=FULL_PANEL,
                n_cases=n_cases,
                seed_start=9_000_000,  # disjoint from research loop's seed range
                budget=budget,
            )
        return result
    finally:
        # Restore filesystem state.
        if existing is not None:
            target.write_bytes(existing)
        else:
            target.unlink(missing_ok=True)


def _diff_panel(original: dict, confirmation: PanelResult) -> dict:
    """Per-model pass-rate delta between original and confirmation.

    A robust trap has small deltas across the panel. A fragile trap
    has one or more models flip by >30% between runs — that's a sign
    the trap was over-fit to the original seeds.
    """
    orig_panel = original.get("full_result", {}).get("per_model_pass", {})
    deltas: dict[str, float] = {}
    for model in set(orig_panel) | set(confirmation.per_model_pass):
        a = orig_panel.get(model, 0.0)
        b = confirmation.per_model_pass.get(model, 0.0)
        deltas[model] = b - a
    return deltas


def _print_keeper(keeper: dict) -> None:
    print(f"\n=== {keeper['trap_family']}  (candidate_id={keeper['candidate_id']}) ===")
    print(f"  proposed by: {keeper['researcher_model']}")
    print(f"  score: {keeper['score']:.2f}  novelty: {keeper.get('novelty', 0):.2f}  spread: {keeper['full_result']['spread']:.2f}")
    print(f"  rationale: {keeper['rationale'][:300]}")
    print(f"  per-model (n={keeper['full_result']['n_cases']}):")
    sorted_models = sorted(keeper['full_result']['per_model_pass'].items(), key=lambda x: -x[1])
    for m, p in sorted_models:
        print(f"    {m:38s} {p*100:>5.1f}%")


def _print_confirmation(keeper: dict, confirmation: PanelResult) -> None:
    deltas = _diff_panel(keeper, confirmation)
    max_abs_delta = max(abs(d) for d in deltas.values()) if deltas else 0
    robust = max_abs_delta <= 0.20  # 20% per-model swing tolerated
    spread_a = keeper["full_result"]["spread"]
    spread_b = confirmation.spread
    spread_holds = abs(spread_a - spread_b) <= 0.15

    print(f"\n  CONFIRMATION RUN (n={confirmation.n_cases}):")
    print(f"  original spread: {spread_a:.2f}")
    print(f"  confirmation spread: {spread_b:.2f}  {'OK' if spread_holds else 'DRIFT'}")
    print(f"  max per-model delta: {max_abs_delta*100:>4.1f}%  {'ROBUST' if robust else 'FRAGILE'}")
    print(f"  per-model deltas:")
    for m, d in sorted(deltas.items(), key=lambda x: -abs(x[1])):
        sign = "+" if d >= 0 else ""
        flag = "" if abs(d) <= 0.20 else "  ⚠ swing"
        print(f"    {m:38s} {sign}{d*100:>+5.1f}%{flag}")
    print(f"  → PROMOTE: {'yes' if (robust and spread_holds) else 'no — investigate before merging'}")


def _promotion_plan(keepers: list[dict]) -> str:
    """Markdown summary suitable for a CHANGELOG / release-notes section."""
    out: list[str] = ["## Candidate traps for mini-v3 (curator review)\n"]
    for k in keepers:
        out.append(f"### `{k['trap_family']}`  (score {k['score']:.2f}, by {k['researcher_model']})\n")
        out.append(k.get("rationale", "(no rationale)") + "\n")
        out.append("| Model | Pass |")
        out.append("|---|---:|")
        for m, p in sorted(k['full_result']['per_model_pass'].items(), key=lambda x: -x[1]):
            out.append(f"| `{m}` | {p*100:.0f}% |")
        out.append("")
        out.append(f"- Source: `pdfhell/research/keep/{k['trap_family']}.py` (from `keep/{k['candidate_id']}.json`)")
        out.append(f"- Suggested seed range for mini-v3: `range(7001, 7031)`")
        out.append(f"- Action: `cp pdfhell/research/keep/{k['trap_family']}.py pdfhell/generators/` then register in `__init__.py`")
        out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Curate research-discovered traps into mini-vN.",
    )
    parser.add_argument("--keeper", help="One candidate_id (filename minus .json) to focus on.")
    parser.add_argument("--confirm", help="Run a confirmation eval for the given candidate_id (costs ~$3).")
    parser.add_argument("--confirm-all", action="store_true",
                        help="Confirmation eval for every keeper (costs ~$3 each).")
    parser.add_argument("--promotion-plan", action="store_true",
                        help="Emit a markdown promotion plan for all keepers.")
    parser.add_argument("--budget-cap", type=float, default=15.0,
                        help="USD cap across all confirmation runs (default $15).")
    parser.add_argument("--cases", type=int, default=20,
                        help="Cases per confirmation eval (default 20).")
    args = parser.parse_args()

    if args.promotion_plan:
        print(_promotion_plan(list(_iter_keepers())))
        return 0

    if args.confirm:
        keeper = _load_keeper(args.confirm)
        if keeper is None:
            print(f"no such keeper: {args.confirm}", file=sys.stderr)
            return 1
        _print_keeper(keeper)
        print("\n  running confirmation eval (this costs API spend)...")
        result = _confirmation_run(keeper, n_cases=args.cases, budget_cap=args.budget_cap)
        if result is None:
            print("  CONFIRMATION FAILED — generator could not be evaluated")
            return 2
        _print_confirmation(keeper, result)
        return 0

    if args.confirm_all:
        keepers = list(_iter_keepers())
        budget_remaining = args.budget_cap
        for keeper in keepers:
            est = estimate_run_cost("openai:gpt-5", args.cases) * len(FULL_PANEL)
            if budget_remaining < est:
                print(f"\n  budget cap (${args.budget_cap:.2f}) hit before {keeper['trap_family']} — skipping rest")
                break
            _print_keeper(keeper)
            print("\n  running confirmation eval...")
            result = _confirmation_run(keeper, n_cases=args.cases, budget_cap=budget_remaining)
            if result is not None:
                _print_confirmation(keeper, result)
                budget_remaining -= result.cost_usd
            else:
                print("  CONFIRMATION FAILED")
        return 0

    # Default: dump every keeper as a printout
    keepers = list(_iter_keepers())
    if args.keeper:
        keepers = [k for k in keepers if k.get("candidate_id") == args.keeper]
    print(f"=== {len(keepers)} keepers in {KEEP_DIR} ===")
    for k in keepers:
        _print_keeper(k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
