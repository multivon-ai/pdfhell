"""Trap family: split table across pages.

A 6-column financial / inventory / pricing table is drawn so that the
column *header* row appears at the bottom of page 1 and the *body* rows
appear at the top of page 2. The visual continuity is obvious to a
human flipping pages but breaks every document-pipeline that processes
pages independently (most RAG loaders, most OCR pipelines).

The trap question asks the model about a specific cell — e.g. "What is
the Q3 Net Revenue for the Northwest region?". A model that loses the
header context on page 2 will either confuse columns (returning Gross
Revenue or Operating Income instead) or refuse to answer. Procedural
ground truth means we know exactly which column the answer is in.
"""
from __future__ import annotations

import random

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C


_REGIONS = ["Northwest", "Northeast", "Southwest", "Southeast", "Central"]
_QUARTERS = ["Q1", "Q2", "Q3", "Q4"]
_COLUMNS = [
    ("Region", "region"),
    ("Quarter", "quarter"),
    ("Gross Revenue", "gross"),
    ("Cost of Goods", "cogs"),
    ("Operating Income", "op_income"),
    ("Net Revenue", "net"),
]


def _generate_row(rng: random.Random) -> dict:
    region = rng.choice(_REGIONS)
    quarter = rng.choice(_QUARTERS)
    gross = round(rng.uniform(800_000, 5_000_000), 2)
    cogs = round(gross * rng.uniform(0.35, 0.55), 2)
    op_income = round(gross * rng.uniform(0.15, 0.30), 2)
    net = round(op_income - rng.uniform(20_000, 80_000), 2)
    return {
        "region": region,
        "quarter": quarter,
        "gross": gross,
        "cogs": cogs,
        "op_income": op_income,
        "net": net,
    }


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    # Build 8 unique (region, quarter) rows.
    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    while len(rows) < 8:
        row = _generate_row(rng)
        key = (row["region"], row["quarter"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)

    # The case asks about ONE specific row and ONE specific column.
    target_row = rng.choice(rows)
    target_column_label, target_column_key = rng.choice(_COLUMNS[2:])  # skip region/quarter
    expected_value = target_row[target_column_key]
    expected_str = C.fmt_money(expected_value)

    # The most plausible *wrong* answer is the value from an adjacent
    # column in the same row (the "column-confusion" failure mode that
    # page-split tables specifically elicit).
    other_money_cols = [k for _, k in _COLUMNS[2:] if k != target_column_key]
    wrong_col = rng.choice(other_money_cols)
    wrong_str = C.fmt_money(target_row[wrong_col])

    case_id = f"split_table_across_pages-{seed:04d}"
    question = (
        f"The attached PDF contains a financial-results table. "
        f"What was the {target_column_label} for the {target_row['region']} region in "
        f"{target_row['quarter']} of 2026? Respond with only the dollar amount, no other text."
    )

    def draw(c: canvas.Canvas) -> None:
        # Page 1 — intro + header row at the bottom (the trap)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, 720, "FY2026 REGIONAL FINANCIAL SUMMARY")
        c.setFont("Helvetica", 10)
        C.draw_paragraph(
            c,
            "The following table summarises gross and net revenue, cost of goods sold, and operating "
            "income by region and quarter for fiscal year 2026. All amounts are reported in USD "
            "and exclude inter-regional transfers. See Appendix B for the methodology used to allocate "
            "shared infrastructure costs across regions.",
            72, 690,
            font=C.FontSpec(size=10),
        )

        # Drop some filler so the header naturally ends up near the bottom
        C.draw_paragraph(
            c,
            "Note that Q3 results reflect the regional reorganisation announced in our Q2 earnings "
            "call. Comparisons to prior years should account for the boundary shift between the "
            "Northwest and Central regions effective 2026-07-01.",
            72, 620,
            font=C.FontSpec(size=10),
        )

        # Header row at the bottom of page 1
        col_widths = [80, 60, 100, 100, 100, 100]
        x_start = 72
        header_y = 130
        c.setFont("Helvetica-Bold", 10)
        cx = x_start
        for (label, _), w in zip(_COLUMNS, col_widths):
            c.drawString(cx, header_y, label)
            cx += w

        # Page footer
        c.setFont("Helvetica", 9)
        c.drawCentredString(C.PAGE_WIDTH / 2, 60, "Page 1 of 2")

        # Page break — body rows go on page 2 with no repeated header
        C.page_break(c)

        # Page 2 — the body rows, headerless
        y = 720
        c.setFont("Helvetica", 10)
        for row in rows:
            cx = x_start
            cells = [
                row["region"],
                row["quarter"],
                C.fmt_money(row["gross"]),
                C.fmt_money(row["cogs"]),
                C.fmt_money(row["op_income"]),
                C.fmt_money(row["net"]),
            ]
            for cell, w in zip(cells, col_widths):
                c.drawString(cx, y, cell)
                cx += w
            y -= 22

        # Page footer
        c.setFont("Helvetica", 9)
        c.drawCentredString(C.PAGE_WIDTH / 2, 60, "Page 2 of 2")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="split_table_across_pages",
        seed=seed,
        question=question,
        expected_answer=expected_str,
        forbidden_answers=[wrong_str],
        metadata={
            "target_region": target_row["region"],
            "target_quarter": target_row["quarter"],
            "target_column": target_column_label,
            "target_column_key": target_column_key,
            "expected_value": expected_value,
            "row_count": len(rows),
            "expected_failure_mode": (
                "Model loses column-header context when reading page 2 in isolation; "
                "returns a value from an adjacent column in the same row."
            ),
        },
    )
    return pdf_bytes, case
