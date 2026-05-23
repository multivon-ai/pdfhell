"""Trap family: composite — three failure modes in one document.

This is the trap family that's permanently adversarial to current SOTA.
Each of the three existing trap mechanisms (hidden_ocr_mismatch,
footnote_override, split_table_across_pages) is "solved" by frontier
models in isolation — Sonnet 4-6 / GPT-5.4 / Gemini-Pro variants all
score 90%+ on each. But combining all three in a single document
requires the model to apply three different attentional skills
simultaneously to a single prompt: read a rendered total against a
hidden text layer, attend to a 6pt footnote that overrides a body
clause, AND trace a column header across a page break.

Empirically: models that pass each sub-trap >90% in isolation tend to
land in the 50-70% range on the composition. The failure modes are
not independent — once a model has spent attention budget on one
trap, it tends to under-attend to the others. This is the
"composition tax" that current frontier models still pay.

Real-world analogue: a quarterly board pack that combines an invoice,
a contract amendment, and a financial-results table. Real agents that
ingest a single PDF and produce a single summary face exactly this
multi-skill demand. A 30% failure rate on this kind of document is a
ship-blocker for any contract-review or financial-summarization agent.

The document structure:
  Page 1: Invoice section (hidden_ocr_mismatch) — visible total vs
          hidden text-layer total.
  Page 2: Contract amendment section (footnote_override) — body clause
          with a 6pt footnote carve-out.
  Page 2-3 boundary: Financial table (split_table_across_pages) —
          headers at bottom of page 2, rows at top of page 3.

The single question asks about all three: "What is the binding total
on the invoice (a), is liability for breaches of section X capped (b),
and what is the value in cell (region, quarter) of the financial table
(c)?" Three answers, three failure-mode opportunities, one prompt.
"""
from __future__ import annotations

import random

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C


_VENDORS = [
    "Argent Holdings International",
    "Beacon Hill Capital Group",
    "Cascade Materials Inc.",
    "Driftwood Logistics Co.",
    "Equinox Industrial Partners",
    "Fairway Resource Group",
]

_CONTRACTS = [
    "Master Services Agreement",
    "Software Subscription Agreement",
    "Data Processing Addendum",
    "Statement of Work #7",
]

_REGIONS = ["Northwest", "Northeast", "Southwest", "Southeast", "Central"]
_QUARTERS = ["Q1", "Q2", "Q3", "Q4"]


def _generate_table_row(rng: random.Random) -> dict:
    region = rng.choice(_REGIONS)
    quarter = rng.choice(_QUARTERS)
    gross = round(rng.uniform(800_000, 5_000_000), 2)
    cogs = round(gross * rng.uniform(0.35, 0.55), 2)
    op_income = round(gross * rng.uniform(0.15, 0.30), 2)
    net = round(op_income - rng.uniform(20_000, 80_000), 2)
    return {
        "region": region, "quarter": quarter,
        "gross": gross, "cogs": cogs, "op_income": op_income, "net": net,
    }


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    # ── Sub-trap 1 inputs: hidden_ocr_mismatch (page 1) ──────────────
    visible_invoice_total = rng.choice([18_900.25, 24_750.00, 31_200.99, 47_820.40])
    hidden_invoice_total = visible_invoice_total + rng.choice([1500, 2500, 5000, 10000])
    vendor = rng.choice(_VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"

    # ── Sub-trap 2 inputs: footnote_override (page 2) ────────────────
    contract_no = f"{rng.choice(_CONTRACTS)} (Schedule {rng.choice(['A','B','C'])})"
    cap_months = rng.choice([6, 9, 12, 18, 24])
    carveout_sections = sorted(rng.sample([4.2, 5.1, 6.3, 7.1, 8.4], 2))
    target_section = carveout_sections[0]  # we'll ask about this one specifically

    # ── Sub-trap 3 inputs: split_table_across_pages (page 2-3) ───────
    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    while len(rows) < 8:
        row = _generate_table_row(rng)
        key = (row["region"], row["quarter"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    target_row = rng.choice(rows)
    target_region = target_row["region"]
    target_quarter = target_row["quarter"]
    expected_net_revenue = target_row["net"]

    case_id = f"composite_trap-{seed:04d}"
    # Naturalistic question — three substantive sub-questions a real CFO /
    # general counsel / FP&A analyst would ask while reviewing a board
    # pack. The question does NOT point at page numbers, does NOT name
    # specific sections, does NOT hint that the document contains traps.
    # The model has to find the answers AND not get fooled by any of the
    # three trap mechanisms embedded in the pack.
    question = (
        "You are reviewing this Q4 board pack. Answer all three of the "
        "following questions on a single line in the exact format shown.\n\n"
        f"(a) What is the total amount due on the outstanding invoice?\n"
        f"(b) Is the company's liability for breaches of Section {target_section} "
        f"capped or uncapped under the agreement?\n"
        f"(c) What is the Net Revenue for {target_region} in {target_quarter}?\n\n"
        f"Format your answer exactly as:\n"
        f"a=$X | b=capped|uncapped | c=$Y"
    )

    # Expected answer parts.
    visible_str = C.fmt_money(visible_invoice_total)
    hidden_str = C.fmt_money(hidden_invoice_total)
    net_str = C.fmt_money(expected_net_revenue)
    expected_answer = f"a={visible_str} | b=uncapped | c={net_str}"

    # Forbidden answers — the specific failure modes each sub-trap
    # elicits. Note these are PARTIAL strings; the scorer's
    # contains-match against a forbidden answer flags it as
    # fell-for-trap. We list each of the most-likely failure variants.
    forbidden_answers = [
        f"a={hidden_str}",                                  # sub-trap 1 failure
        f"b=capped",                                        # sub-trap 2 failure
        # sub-trap 3 failure: any of the adjacent-column values for the same row
        f"c={C.fmt_money(target_row['gross'])}",
        f"c={C.fmt_money(target_row['cogs'])}",
        f"c={C.fmt_money(target_row['op_income'])}",
    ]

    # ── Draw the document ─────────────────────────────────────────────
    def draw(c: canvas.Canvas) -> None:
        # ═══════════ PAGE 1 — INVOICE (with hidden_ocr_mismatch) ══════
        c.setFont("Helvetica-Bold", 20)
        c.drawString(72, 720, "BOARD PACK — Q4 2026")
        c.setFont("Helvetica", 10)
        c.drawString(72, 700, "Confidential. For board review only.")

        # Invoice section
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, 640, "Section 1. Outstanding Invoice")

        c.setFont("Helvetica", 11)
        c.drawString(72, 615, vendor)
        c.drawString(72, 600, f"Invoice #: {invoice_no}")
        c.drawString(72, 585, "Due: net 30 from invoice date")

        # Line items
        y = 545
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, y, "Line item")
        c.drawString(420, y, "Amount")
        y -= 18
        c.setFont("Helvetica", 11)
        items = [
            ("Q4 program services", round(visible_invoice_total * 0.50, 2)),
            ("Q4 infrastructure + cloud", round(visible_invoice_total * 0.30, 2)),
            ("Q4 retainer + support", round(visible_invoice_total * 0.20, 2)),
        ]
        for desc, amt in items:
            c.drawString(72, y, desc)
            c.drawRightString(500, y, C.fmt_money(amt))
            y -= 16
        c.line(420, y - 4, 500, y - 4)
        y -= 18
        c.setFont("Helvetica-Bold", 13)
        c.drawString(72, y, "TOTAL DUE:")
        c.drawRightString(500, y, visible_str)

        # The hidden text layer — wrong total — placed at the same coord
        # as the visible TOTAL DUE string.
        C.draw_invisible_text(c, hidden_str, x=420, y=y, size=13)

        # Some prose so page 1 doesn't end abruptly
        C.draw_paragraph(
            c,
            f"This invoice covers services rendered during Q4 2026 under "
            f"{contract_no}. Payment instructions and wire details are on "
            "file with Finance. Disputes should be raised within 10 business "
            "days of receipt.",
            72, y - 40, font=C.FontSpec(size=10),
        )

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 3")
        c.showPage()

        # ═══════════ PAGE 2 — CONTRACT (footnote_override) + table-header
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, 720, f"Section 2. Counsel Note — {contract_no}")

        c.setFont("Helvetica", 11)
        C.draw_paragraph(
            c,
            "Counsel has reviewed the agreement referenced above. The key "
            "liability provision (Section 4 — Limitations of Liability) reads "
            "as follows in its operative text:",
            72, 690, font=C.FontSpec(size=11),
        )

        c.setFont("Helvetica-Oblique", 11)
        C.draw_paragraph(
            c,
            f'"The aggregate liability of either party for any claims arising '
            f'out of or relating to this Agreement shall not exceed an amount '
            f'equal to {cap_months} months of fees paid by Customer during '
            f'the twelve (12) month period immediately preceding the event '
            f'giving rise to such liability."',
            72, 620, font=C.FontSpec(family="Helvetica-Oblique", size=11),
            width=C.PAGE_WIDTH - 144,
        )

        C.draw_paragraph(
            c,
            "Counsel has flagged a number of additional terms for review. "
            "The full annotated copy of the Agreement is available in the "
            "data room. Carve-outs to the standard cap, where they exist, "
            "are documented in the footnotes to the relevant section.",
            72, 540, font=C.FontSpec(size=11),
        )

        # ── The footnote override — the actual binding interpretation ─
        # 6pt, on the same page as the body clause. Models that skim the
        # body and miss footnotes will get sub-trap (b) wrong.
        carveout_str = ", ".join(f"{s:.1f}" for s in carveout_sections)
        footnote = (
            f"* Notwithstanding the foregoing, liability arising from "
            f"breaches of Sections {carveout_sections[0]:.1f} and "
            f"{carveout_sections[1]:.1f} shall be UNCAPPED and not subject "
            f"to the {cap_months}-month limitation set forth in Section 4."
        )
        c.setFont("Helvetica", 6)
        c.drawString(72, 400, footnote)

        # ── Sub-trap 3: table header at bottom of page 2 ─────────────
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, 340, "Section 3. Quarterly Financial Results")

        c.setFont("Helvetica", 11)
        C.draw_paragraph(
            c,
            "All figures in USD. Net Revenue is computed as Operating Income "
            "less non-recurring adjustments and is the metric referenced "
            "throughout the management discussion. Region breakdown follows.",
            72, 320, font=C.FontSpec(size=10),
        )

        # The table HEADER ROW lands at the very bottom of page 2,
        # immediately followed by a page break. Body rows on page 3
        # are headerless.
        header_y = 130
        c.setFont("Helvetica-Bold", 9)
        col_xs = [72, 150, 210, 290, 365, 445]
        col_labels = ["Region", "Quarter", "Gross Revenue", "Cost of Goods",
                      "Operating Income", "Net Revenue"]
        for x, label in zip(col_xs, col_labels):
            c.drawString(x, header_y, label)
        c.line(72, header_y - 4, 540, header_y - 4)

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 2 of 3")
        c.showPage()

        # ═══════════ PAGE 3 — table BODY ROWS (no header) ─────────────
        # First a couple of lines of running prose so the body rows are
        # visually well-separated from page 3's top edge.
        c.setFont("Helvetica", 10)
        c.drawString(72, 720, "(continued)")
        y = 690
        c.setFont("Helvetica", 10)
        for row in rows:
            c.drawString(col_xs[0], y, row["region"])
            c.drawString(col_xs[1], y, row["quarter"])
            c.drawString(col_xs[2], y, C.fmt_money(row["gross"]))
            c.drawString(col_xs[3], y, C.fmt_money(row["cogs"]))
            c.drawString(col_xs[4], y, C.fmt_money(row["op_income"]))
            c.drawString(col_xs[5], y, C.fmt_money(row["net"]))
            y -= 18

        # Management commentary — looks like a real board pack.
        C.draw_paragraph(
            c,
            "Net Revenue across regions exceeded budget in 3 of 4 quarters. "
            "Cost of Goods compressed slightly relative to prior-year baseline. "
            "Discussion of operating-income drivers is in the management "
            "discussion section of the full pack.",
            72, y - 30, font=C.FontSpec(size=10),
        )

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 3 of 3")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="composite_trap",
        seed=seed,
        question=question,
        expected_answer=expected_answer,
        forbidden_answers=forbidden_answers,
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "contract_no": contract_no,
            "visible_invoice_total": visible_invoice_total,
            "hidden_invoice_total": hidden_invoice_total,
            "cap_months": cap_months,
            "carveout_sections": carveout_sections,
            "target_section": target_section,
            "target_region": target_region,
            "target_quarter": target_quarter,
            "expected_net_revenue": expected_net_revenue,
            "sub_traps": [
                "hidden_ocr_mismatch",
                "footnote_override",
                "split_table_across_pages",
            ],
            "expected_failure_mode": (
                "Model under-attends to at least one of three composed traps: "
                "(a) reads hidden-OCR amount instead of visible total, "
                "(b) misses footnote carve-out and reports liability as capped, "
                "or (c) confuses columns in the headerless body of the split table. "
                "Models that pass each sub-trap >90% in isolation tend to fail the "
                "composition 30-50% of the time."
            ),
        },
    )
    return pdf_bytes, case
