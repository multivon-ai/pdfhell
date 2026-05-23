"""Aggregate confirm-all output into a comparison table.

After running ``python -m pdfhell.research.curate --confirm-all``, the
stdout is verbose. This helper re-runs evaluate against the kept code
WITHOUT API calls (just reads the stored results from the per-keeper
JSON written during confirm) and produces a single Markdown comparison
table per trap, plus a one-screen summary.

Usage::

    python -m pdfhell.research.aggregate_confirm /tmp/pdfhell-confirm.log

Parses the log file (which contains both original and confirmation
per-model pass rates) and emits Markdown.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class _TrapBlock:
    trap_family: str
    candidate_id: str
    researcher: str
    rationale: str
    original_n: int = 0
    original_per_model: dict[str, float] = field(default_factory=dict)
    confirm_n: int = 0
    confirm_per_model: dict[str, float] = field(default_factory=dict)
    deltas: dict[str, float] = field(default_factory=dict)
    max_delta: float = 0.0
    original_spread: float = 0.0
    confirm_spread: float = 0.0
    spread_holds: bool = False
    robust: bool = False
    verdict: str = "?"


_RE_HEADER = re.compile(r"=== (\S+)\s+\(candidate_id=([\S]+)\)\s*===")
_RE_PROPOSED = re.compile(r"\s*proposed by:\s*(\S+)")
_RE_RATIONALE = re.compile(r"\s*rationale:\s*(.+)")
_RE_ORIG_N = re.compile(r"\s*per-model \(n=(\d+)\):")
_RE_CONFIRM_N = re.compile(r"\s*CONFIRMATION RUN \(n=(\d+)\):")
_RE_PER_MODEL = re.compile(r"\s*(\S+:\S+)\s+([\d.]+)%")
_RE_ORIG_SPREAD = re.compile(r"\s*original spread:\s*([\d.]+)")
_RE_CONF_SPREAD = re.compile(r"\s*confirmation spread:\s*([\d.]+)")
_RE_MAX_DELTA = re.compile(r"\s*max per-model delta:\s*([\d.]+)%\s+(\S+)")
_RE_DELTA = re.compile(r"\s*(\S+:\S+)\s+\+?\s*([+-]?[\d.]+)%")
_RE_PROMOTE = re.compile(r"\s*→ PROMOTE:\s*(.+)")


def parse(log_path: Path) -> list[_TrapBlock]:
    """Parse the confirm-all log into one block per trap."""
    blocks: list[_TrapBlock] = []
    cur: _TrapBlock | None = None
    section = ""  # "original" or "confirmation"

    lines = log_path.read_text(encoding="utf-8").splitlines()

    for line in lines:
        m = _RE_HEADER.match(line)
        if m:
            if cur is not None:
                blocks.append(cur)
            cur = _TrapBlock(
                trap_family=m.group(1),
                candidate_id=m.group(2),
                researcher="",
                rationale="",
            )
            section = ""
            continue
        if cur is None:
            continue

        m = _RE_PROPOSED.match(line)
        if m:
            cur.researcher = m.group(1)
            continue

        m = _RE_RATIONALE.match(line)
        if m:
            cur.rationale = m.group(1).strip()[:300]
            continue

        m = _RE_ORIG_N.match(line)
        if m:
            cur.original_n = int(m.group(1))
            section = "original"
            continue

        m = _RE_CONFIRM_N.match(line)
        if m:
            cur.confirm_n = int(m.group(1))
            section = "confirmation"
            continue

        m = _RE_ORIG_SPREAD.match(line)
        if m:
            cur.original_spread = float(m.group(1))
            continue

        m = _RE_CONF_SPREAD.match(line)
        if m:
            cur.confirm_spread = float(m.group(1))
            cur.spread_holds = abs(cur.confirm_spread - cur.original_spread) <= 0.15
            continue

        m = _RE_MAX_DELTA.match(line)
        if m:
            cur.max_delta = float(m.group(1)) / 100
            cur.robust = "ROBUST" in m.group(2)
            continue

        m = _RE_PROMOTE.match(line)
        if m:
            cur.verdict = m.group(1).strip()
            continue

        # Per-model pass rates show up in "original" and "confirmation"
        # sections both. Delta rows show + or - signs.
        m = _RE_PER_MODEL.match(line)
        if m and section in ("original", "confirmation"):
            model = m.group(1)
            pct = float(m.group(2)) / 100
            if section == "original":
                cur.original_per_model[model] = pct
            else:
                cur.confirm_per_model[model] = pct

        # Delta lines look like "  anthropic:opus +5.0%" or " -10.0%"
        m = _RE_DELTA.match(line)
        if m and "deltas:" not in line:
            model = m.group(1)
            try:
                d = float(m.group(2)) / 100
            except ValueError:
                continue
            # Only stash if it's clearly a signed delta (has + or -)
            if line.lstrip().startswith(model) and ("+" in line or line.lstrip().split()[1].startswith("-")):
                cur.deltas[model] = d

    if cur is not None:
        blocks.append(cur)

    # Post-process: confirmation per-model is computed from original +
    # deltas because the curate output prints deltas not absolutes.
    for b in blocks:
        if not b.confirm_per_model and b.original_per_model and b.deltas:
            for model, orig in b.original_per_model.items():
                d = b.deltas.get(model, 0.0)
                b.confirm_per_model[model] = max(0.0, min(1.0, orig + d))

    return blocks


def render_markdown(blocks: list[_TrapBlock]) -> str:
    """Produce the comparison Markdown."""
    out: list[str] = []
    out.append("# Per-trap confirmation results\n")
    out.append(f"| Trap | Researcher | Original spread | Confirm spread | Max model Δ | Verdict |")
    out.append(f"|---|---|---:|---:|---:|---|")
    for b in blocks:
        delta_pct = f"{b.max_delta*100:.0f}%"
        verdict_marker = "✅ ROBUST" if b.robust and b.spread_holds else "⚠ INVESTIGATE"
        out.append(
            f"| `{b.trap_family}` | {b.researcher} | "
            f"{b.original_spread:.2f} | {b.confirm_spread:.2f} | "
            f"{delta_pct} | {verdict_marker} |"
        )
    out.append("\n")

    for b in blocks:
        out.append(f"\n## `{b.trap_family}`\n")
        out.append(f"- **Proposed by:** {b.researcher}")
        out.append(f"- **Rationale:** {b.rationale}")
        out.append(f"- **Original n:** {b.original_n}, **Confirmation n:** {b.confirm_n}")
        out.append(f"- **Original spread:** {b.original_spread:.2f}  →  **Confirmation spread:** {b.confirm_spread:.2f} ({'holds' if b.spread_holds else 'DRIFTED'})")
        out.append(f"- **Max per-model delta:** {b.max_delta*100:.0f}% ({'ROBUST' if b.robust else 'FRAGILE'})")
        out.append("")
        # Side-by-side per-model
        if b.original_per_model and b.confirm_per_model:
            out.append("| Model | Original | Confirm | Δ |")
            out.append("|---|---:|---:|---:|")
            all_models = sorted(set(b.original_per_model) | set(b.confirm_per_model))
            for m in all_models:
                o = b.original_per_model.get(m, float("nan"))
                c = b.confirm_per_model.get(m, float("nan"))
                d = c - o
                flag = " ⚠" if abs(d) > 0.20 else ""
                sign = "+" if d >= 0 else ""
                out.append(f"| `{m}` | {o*100:.0f}% | {c*100:.0f}% | {sign}{d*100:+.0f}%{flag} |")
            out.append("")

    return "\n".join(out)


def opus_summary(blocks: list[_TrapBlock]) -> str:
    """The headline: did Opus 4-7 stay at 0% across the v4 traps?"""
    out: list[str] = ["\n# Opus 4-7 across the v4 traps\n"]
    out.append("| Trap | Original Opus pass | Confirm Opus pass |")
    out.append("|---|---:|---:|")
    v4 = {
        "em_dash_minus_sign",
        "upside_down_amount",
        "checksum_validation_rule",
        "mirror_image_glyphs",
        "boldface_binding_rule",
        "shaded_box_binding_rule",
        "color_grounding_trap",
    }
    for b in blocks:
        if b.trap_family not in v4:
            continue
        orig = b.original_per_model.get("anthropic:claude-opus-4-7", float("nan"))
        conf = b.confirm_per_model.get("anthropic:claude-opus-4-7", float("nan"))
        out.append(f"| `{b.trap_family}` | {orig*100:.0f}% | {conf*100:.0f}% |")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate confirm-all log into Markdown.")
    parser.add_argument("log", type=Path, help="Path to confirm-all stdout log")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write Markdown here (default: stdout)")
    args = parser.parse_args()

    blocks = parse(args.log)
    if not blocks:
        print(f"no trap blocks parsed from {args.log}", file=sys.stderr)
        return 1

    md = render_markdown(blocks) + opus_summary(blocks)
    if args.out:
        args.out.write_text(md, encoding="utf-8")
        print(f"wrote {args.out} ({len(blocks)} traps)")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
