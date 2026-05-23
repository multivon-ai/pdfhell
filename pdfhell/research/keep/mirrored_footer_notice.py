from __future__ import annotations

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C

_VENDORS = [
    "Arcadia Process Solutions LLC",
    "Northwind Commodities Inc.",
    "Sable Ridge Instruments Co.",
    "Blue Fathom Analytics Ltd.",
    "Ironwood Fabrication Group",
    "Cascade Clinical Systems",
    "Helios Maritime Services",
    "Pioneer Orchard Foods Co.",
]


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    vendor = C.pick_from(rng, _VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"
    issue_date = f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"

    # Choose a clean headline amount; no competing dollar figures appear elsewhere.
    amount = round(rng.uniform(1200, 125000), 2)
    amount_str = C.fmt_money(amount)

    case_id = f"mirrored_footer_notice-{seed:04d}"
    question = (
        "You are an accounts-payable assistant. According to the mirrored binding "
        "notice at the bottom of the page, how much is owed on this invoice? "
        "Respond with only the amount including the currency symbol."
    )

    def draw(c: canvas.Canvas) -> None:
        # Header and basic invoice scaffolding (no other monetary numbers shown).
        c.setFont("Helvetica-Bold", 22)
        c.drawString(72, 720, "INVOICE")

        c.setFont("Helvetica", 11)
        c.drawString(72, 700, vendor)
        c.drawString(72, 685, f"Invoice #: {invoice_no}")
        c.drawString(72, 670, f"Issue date: {issue_date}")
        c.drawString(72, 655, "Payment terms: Net 30")

        C.draw_paragraph(
            c,
            "Please review the binding notice before remitting payment. "
            "All remittances must comply with the notice terms.",
            72,
            620,
            font=C.FontSpec(size=11),
        )

        # Non-mirrored helper note so a human knows to read the mirrored text.
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(72, 120, "Binding notice below is mirrored (read carefully).")
        c.line(72, 115, C.PAGE_WIDTH - 72, 115)

        # The trap: horizontally mirrored binding notice carrying the ONLY dollar amount.
        # We flip the X axis around the page width so text is mirrored but still vector text.
        c.saveState()
        c.translate(C.PAGE_WIDTH, 0)
        c.scale(-1, 1)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(
            72,
            95,
            f"BINDING NOTICE: The amount owed by the customer is {amount_str}.",
        )
        c.restoreState()

        # Footer page marker
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="mirrored_footer_notice",
        seed=seed,
        question=question,
        expected_answer=amount_str,
        forbidden_answers=[],
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "issue_date": issue_date,
            "mirrored_clause_y": 95,
            "expected_failure_mode": (
                "Vision models fail to read horizontally mirrored text and either skip it "
                "or guess from context; text extractors and attentive humans read it fine."
            ),
            "diagnostic": (
                "The only dollar figure appears in mirrored vector text. PDF text extraction "
                "still surfaces the literal codepoints; a pure-vision pipeline struggles."
            ),
        },
    )

    return pdf_bytes, case
