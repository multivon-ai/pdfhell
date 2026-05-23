"""``python -m pdfhell.research.report`` — summarise a research run.

Reads ``pdfhell/research/results.tsv`` and the ``keep/*.json``
snapshots; prints:
  - Total candidates attempted, kept, reverted, gate-failed
  - Spend breakdown by researcher and by phase
  - Gate-fail histogram (which gate caught the most attempts)
  - The keepers, ranked by score, with per-model pass rates
  - Convergence signal (which trap mechanisms multiple researchers
    independently proposed)

Used to:
  - Decide which keepers to curate into the next ``mini-vN``
  - Audit the cost/effort of a research session
  - Generate the "what happened overnight" share-card

Run with::

    python -m pdfhell.research.report             # text summary
    python -m pdfhell.research.report --json      # machine-readable
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


RESEARCH_DIR = Path(__file__).resolve().parent
RESULTS_TSV = RESEARCH_DIR / "results.tsv"
KEEP_DIR = RESEARCH_DIR / "keep"
BUDGET_LOG = RESEARCH_DIR / "budget.jsonl"


@dataclass(slots=True)
class _Row:
    """One row from results.tsv."""

    timestamp: str
    candidate_id: str
    researcher_model: str
    trap_family: str
    status: str
    score: float
    spread: float
    solvable: bool
    cost_usd: float
    per_model_pass: dict[str, float]
    rationale: str


def _load_rows(tsv_path: Path) -> list[_Row]:
    """Parse results.tsv. Missing or malformed file → empty list."""
    if not tsv_path.exists():
        return []
    rows: list[_Row] = []
    with tsv_path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == 0:  # header
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 11:
                continue
            try:
                per_model = json.loads(parts[9]) if parts[9] else {}
            except json.JSONDecodeError:
                per_model = {}
            rows.append(_Row(
                timestamp=parts[0],
                candidate_id=parts[1],
                researcher_model=parts[2],
                trap_family=parts[3],
                status=parts[4],
                score=float(parts[5] or 0),
                spread=float(parts[6] or 0),
                solvable=parts[7] == "1",
                cost_usd=float(parts[8] or 0),
                per_model_pass=per_model,
                rationale=parts[10],
            ))
    return rows


def _load_keeps(keep_dir: Path) -> list[dict]:
    if not keep_dir.exists():
        return []
    out: list[dict] = []
    for f in sorted(keep_dir.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def _budget_total(log_path: Path) -> float:
    """Sum of committed amounts in budget.jsonl."""
    if not log_path.exists():
        return 0.0
    total = 0.0
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("action") == "commit":
                total += float(rec.get("amount", 0))
    return total


_THEME_KEYWORDS = {
    "unicode": ("unicode", "confusable", "cyrillic", "homoglyph", "look-alike"),
    "mirrored/rotated": ("mirror", "rotated", "rotation", "flipped"),
    "annotation": ("annotation", "sticky", "comment", "/annot"),
    "watermark/stamp": ("watermark", "stamp", "voided", "draft"),
    "redaction": ("redact", "blacked", "overlay"),
    "footnote/small": ("footnote", "fine print", "small print", "small text"),
    "currency/fx": ("currency", "fx", "exchange", "eur", "usd"),
    "multi-column": ("column", "two-column", "left-right"),
    "table-split": ("split", "across pages", "header"),
    "ocr-mismatch": ("ocr", "invisible", "text layer"),
}


def _classify_theme(rationale: str) -> str:
    """Best-effort cluster a rationale string into a theme keyword."""
    low = rationale.lower()
    for theme, keys in _THEME_KEYWORDS.items():
        if any(k in low for k in keys):
            return theme
    return "(other)"


def build_summary(
    *,
    tsv_path: Path = RESULTS_TSV,
    keep_dir: Path = KEEP_DIR,
    budget_log: Path = BUDGET_LOG,
) -> dict:
    """Produce a JSON-serialisable summary of the run state."""
    rows = _load_rows(tsv_path)
    keeps = _load_keeps(keep_dir)

    by_status = collections.Counter(r.status for r in rows)
    by_gate = collections.Counter(
        r.status.split(":", 1)[1] for r in rows if r.status.startswith("gate_fail:")
    )
    by_researcher = collections.Counter(r.researcher_model for r in rows)
    spend_by_researcher = collections.defaultdict(float)
    spend_by_phase = collections.Counter()
    for r in rows:
        spend_by_researcher[r.researcher_model] += r.cost_usd
        # Crude phase categorization — gate_fail rows cost only the
        # propose + cheap gates; revert_probe cost propose + probe;
        # keep / revert_full cost propose + probe + full.
        if r.status.startswith("gate_fail"):
            spend_by_phase["propose+gate"] += r.cost_usd
        elif r.status == "revert_probe":
            spend_by_phase["propose+probe"] += r.cost_usd
        elif r.status in ("keep", "revert_full"):
            spend_by_phase["propose+probe+full"] += r.cost_usd
        else:
            spend_by_phase["other"] += r.cost_usd

    # Theme convergence: how often do independent researchers propose
    # the same mechanism theme?
    theme_attempts = collections.Counter()
    theme_researchers: dict[str, set[str]] = collections.defaultdict(set)
    for r in rows:
        theme = _classify_theme(r.rationale)
        theme_attempts[theme] += 1
        theme_researchers[theme].add(r.researcher_model)

    keepers = sorted(
        keeps,
        key=lambda d: d.get("score", 0),
        reverse=True,
    )

    return {
        "total_attempts": len(rows),
        "by_status": dict(by_status),
        "gate_fail_breakdown": dict(by_gate),
        "by_researcher": dict(by_researcher),
        "spend_total_estimate": round(sum(r.cost_usd for r in rows), 4),
        "spend_total_audited": round(_budget_total(budget_log), 4),
        "spend_by_researcher": {k: round(v, 4) for k, v in spend_by_researcher.items()},
        "spend_by_phase": {k: round(v, 4) for k, v in spend_by_phase.items()},
        "theme_attempts": dict(theme_attempts.most_common()),
        "theme_convergence": {
            theme: {
                "attempts": theme_attempts[theme],
                "distinct_researchers": len(theme_researchers[theme]),
                "researchers": sorted(theme_researchers[theme]),
            }
            for theme in theme_attempts
            if len(theme_researchers[theme]) >= 2
        },
        "keepers": [
            {
                "candidate_id": k.get("candidate_id"),
                "trap_family": k.get("trap_family"),
                "researcher_model": k.get("researcher_model"),
                "score": k.get("score"),
                "novelty": k.get("novelty"),
                "spread": k.get("full_result", {}).get("spread"),
                "per_model_pass": k.get("full_result", {}).get("per_model_pass", {}),
                "rationale": k.get("rationale", ""),
            }
            for k in keepers
        ],
    }


# ─── Text rendering ─────────────────────────────────────────────────────


def _print_text(summary: dict) -> None:
    print(f"=== research run summary ===")
    print(f"total attempts:    {summary['total_attempts']}")
    print(f"spend (audited):   ${summary['spend_total_audited']:.2f}")
    print()
    print("by status:")
    for k, v in summary["by_status"].items():
        print(f"  {k:22s} {v:>4d}")
    if summary["gate_fail_breakdown"]:
        print()
        print("gate-fail breakdown (which gate caught the most):")
        for gate, n in sorted(summary["gate_fail_breakdown"].items(), key=lambda x: -x[1]):
            print(f"  {gate:22s} {n:>4d}")
    print()
    print("by researcher:")
    for model, n in summary["by_researcher"].items():
        spend = summary["spend_by_researcher"].get(model, 0)
        print(f"  {model:38s} attempts={n:<3d}  spent=${spend:.2f}")
    print()
    print("spend by phase:")
    for phase, amt in summary["spend_by_phase"].items():
        print(f"  {phase:24s} ${amt:.2f}")
    print()
    print("theme attempts (rationale clustering):")
    for theme, n in summary["theme_attempts"].items():
        print(f"  {theme:22s} {n:>3d}")
    if summary["theme_convergence"]:
        print()
        print("CONVERGENT signals (≥2 researchers independently picked the same theme):")
        for theme, info in summary["theme_convergence"].items():
            print(f"  {theme:22s} {info['attempts']:>2d} attempts by {info['distinct_researchers']} researchers ({', '.join(info['researchers'])})")
    print()
    print(f"=== keepers (ranked by score) — {len(summary['keepers'])} total ===")
    for k in summary["keepers"]:
        print(f"\n  {k['trap_family']}  (score={k['score']:.2f}  novelty={k.get('novelty', 0):.2f}  spread={k.get('spread', 0):.2f})")
        print(f"    by {k['researcher_model']}")
        print(f"    rationale: {k['rationale'][:180]}")
        if k['per_model_pass']:
            print(f"    per-model pass:")
            sorted_models = sorted(k['per_model_pass'].items(), key=lambda x: -x[1])
            for m, p in sorted_models:
                bar = "█" * int(p * 20)
                print(f"      {m:38s} {p*100:>5.1f}%  {bar}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarise a pdfhell.research run.",
    )
    parser.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON (default: human text).")
    parser.add_argument("--tsv", type=Path, default=RESULTS_TSV,
                        help="Path to results.tsv (default: pdfhell/research/results.tsv)")
    parser.add_argument("--keep", type=Path, default=KEEP_DIR,
                        help="Path to keep/ dir (default: pdfhell/research/keep/)")
    parser.add_argument("--budget-log", type=Path, default=BUDGET_LOG,
                        help="Path to budget.jsonl (default: pdfhell/research/budget.jsonl)")
    args = parser.parse_args()

    summary = build_summary(
        tsv_path=args.tsv,
        keep_dir=args.keep,
        budget_log=args.budget_log,
    )

    if args.json:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_text(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
