"""Trap family: hidden OCR mismatch.

The PDF *looks* like an invoice with an amount of ``$X``. But beneath
that visible glyph is an invisible text layer that says ``$Y`` instead
(rendered with PDF text render mode 3 — placed in the text content
stream but never rasterised).

A vision-only model reads the rendered pixels and answers ``$X``. A
text-extraction pipeline (pdfminer, PyMuPDF, pdfplumber, most RAG
loaders) reads the invisible layer and answers ``$Y``. An agent that
combines both — without resolving the conflict — answers whichever the
final stage trusted.

This is the most common silent failure mode for "PDF understanding" in
production: a scanned-then-OCR'd document where the OCR layer disagrees
with the rendered page. We procedurally fabricate it so we know exactly
which answer is correct (the visible one) and which answer is the
specific failure mode the trap was designed to catch (the hidden one).
"""
from __future__ import annotations

import random

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C


# Visible amounts are sampled from a realistic invoice distribution.
# The hidden amount is *not* a small perturbation — it's a meaningfully
# different value, because if the agent's downstream user processes it,
# the dollar gap should be visible.
_VENDORS = [
    "Acme Industrial Supplies LLC",
    "Northwind Logistics Inc.",
    "Globex Manufacturing Co.",
    "Initech Software Solutions",
    "Hooli Cloud Services, Inc.",
    "Soylent Foods Corp.",
    "Wayne Enterprises LP",
    "Stark Industries Inc.",
    "Tyrell Robotics Group",
    "Cyberdyne Systems Inc.",
]


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    # Two distinct amounts; the visible one is the ground truth.
    visible_amount = rng.choice([1234.56, 2750.00, 4980.40, 7820.99, 12345.67, 18900.25])
    hidden_amount = visible_amount + rng.choice([1000, 2000, 5000, 10000])
    vendor = rng.choice(_VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"
    due_day = rng.randint(1, 28)

    visible_str = C.fmt_money(visible_amount)
    hidden_str = C.fmt_money(hidden_amount)

    case_id = f"hidden_ocr_mismatch-{seed:04d}"
    question = (
        f"You are an accounts-payable assistant. The attached PDF is invoice "
        f"{invoice_no} from {vendor}. What is the TOTAL AMOUNT DUE? "
        "Respond with only the amount including currency symbol, no other text."
    )

    def draw(c: canvas.Canvas) -> None:
        # Header
        c.setFont("Helvetica-Bold", 18)
        c.drawString(72, 720, "INVOICE")
        c.setFont("Helvetica", 11)
        c.drawString(72, 700, vendor)
        c.drawString(72, 685, f"Invoice #: {invoice_no}")
        c.drawString(72, 670, f"Due: 2026-08-{due_day:02d}")

        # Line items (3-4 plausible rows so the doc doesn't look skeletal)
        C.draw_paragraph(
            c,
            "ITEM                                                   QTY    UNIT      LINE TOTAL",
            72, 620,
            font=C.FontSpec(size=10, bold=True),
        )
        items = [
            ("Configuration consulting          ", 4, 250.00, 1000.00),
            ("On-site implementation            ", 1, 1200.00, 1200.00),
            ("Annual support (Tier 2)           ", 1, visible_amount - 2200, visible_amount - 2200),
        ]
        y = 600
        for desc, qty, unit, total in items:
            c.drawString(72, y, f"{desc} {qty:>4}   {C.fmt_money(unit):>10}    {C.fmt_money(total):>12}")
            y -= 16

        # The "TOTAL DUE" line is what we're asking the model about.
        c.setFont("Helvetica-Bold", 13)
        c.drawString(72, y - 30, "TOTAL DUE:")
        c.drawString(220, y - 30, visible_str)

        # The trap: place the *wrong* amount in an invisible text layer.
        # It lands at the same coordinate as the visible total, so a
        # text-extraction pipeline that reads the underlying text stream
        # by position would see the hidden value, not the visible one.
        C.draw_invisible_text(c, hidden_str, x=220, y=y - 30, size=13)

        # Footer
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(72, 90, "Thank you for your business. Net 30 from invoice date.")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="hidden_ocr_mismatch",
        seed=seed,
        question=question,
        expected_answer=visible_str,
        forbidden_answers=[hidden_str],
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "visible_amount": visible_amount,
            "hidden_amount": hidden_amount,
            "expected_failure_mode": (
                "Model answers the hidden-OCR amount when it should answer the visible amount; "
                "indicates the model trusted a text-extraction layer over the rendered page."
            ),
        },
    )
    return pdf_bytes, case
