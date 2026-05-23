"""Trap family: em-dash vs minus-sign in signed amounts.

The invoice shows a single line with a CREDIT ADJUSTMENT whose amount
is prefixed by what looks like a minus sign but is actually a Unicode
em-dash (U+2014) or en-dash (U+2013). The clause states that only
amounts prefixed by an ASCII hyphen-minus (U+002D) are deductions;
other dash-like characters are typographic separators and the value is
added.

A careful human reading the vector text (or copying it) can see the
codepoint difference. Vision models see a horizontal stroke before a
number and treat it as negation.
"""
from __future__ import annotations

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C

_VENDORS = [
    "Tidewater Logistics Co.",
    "Granite Peak Consulting LLC",
    "Solstice Imaging Inc.",
    "Harborline Freight Partners",
    "Quillmark Publishing Group",
    "Ferncliff Analytics Ltd.",
]

EM_DASH = "\u2014"
EN_DASH = "\u2013"
HYPHEN_MINUS = "-"


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)
    vendor = rng.choice(_VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"

    base = round(rng.uniform(8000, 22000), 2)
    adjustment = round(rng.uniform(1500, 4500), 2)

    # The adjustment row uses an em-dash (not a minus). Per the clause,
    # that means it's ADDED, not deducted.
    fake_minus = rng.choice([EM_DASH, EN_DASH])

    binding_total = round(base + adjustment, 2)
    decoy_total = round(base - adjustment, 2)

    binding_str = C.fmt_money(binding_total)
    decoy_str = C.fmt_money(decoy_total)
    base_str = C.fmt_money(base)
    adj_str = C.fmt_money(adjustment)

    case_id = f"em_dash_minus_sign-{seed:04d}"
    question = (
        f"You are processing invoice {invoice_no} from {vendor}. "
        "Following the sign-convention clause printed on the invoice exactly, "
        "what is the FINAL AMOUNT DUE? Respond with only the amount including "
        "the currency symbol, no other text."
    )

    def draw(c: canvas.Canvas) -> None:
        c.setFont("Helvetica-Bold", 22)
        c.drawString(72, 720, "INVOICE")

        c.setFont("Helvetica", 11)
        c.drawString(72, 700, vendor)
        c.drawString(72, 685, f"Invoice #: {invoice_no}")
        c.drawString(72, 670, "Terms: Net 30")

        # Sign-convention clause (the rule).
        C.draw_paragraph(
            c,
            "Sign convention: amounts whose prefix is the ASCII hyphen-minus "
            "character (U+002D) are deductions and reduce the running balance. "
            "Amounts whose prefix is any other dash-like glyph (em-dash U+2014 "
            "or en-dash U+2013) are typographic separators only; the numeric "
            "value is ADDED to the running balance. Apply this rule strictly "
            "when computing the FINAL AMOUNT DUE.",
            72, 635,
            font=C.FontSpec(size=10),
        )

        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 540, "DESCRIPTION")
        c.drawRightString(500, 540, "AMOUNT")

        c.setFont("Helvetica", 11)
        y = 520
        c.drawString(72, y, "Base services (current period)")
        c.drawRightString(500, y, base_str)
        y -= 20
        c.drawString(72, y, "Credit adjustment (see sign-convention clause)")
        # The em/en-dash prefix — visually looks like a minus.
        c.drawRightString(500, y, f"{fake_minus}{adj_str}")
        y -= 12
        c.line(380, y, 500, y)
        y -= 18
        c.setFont("Helvetica-Bold", 13)
        c.drawString(72, y, "FINAL AMOUNT DUE:")
        c.drawRightString(500, y, binding_str)

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="em_dash_minus_sign",
        seed=seed,
        question=question,
        expected_answer=binding_str,
        forbidden_answers=[decoy_str],
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "base": base,
            "adjustment": adjustment,
            "prefix_codepoint": f"U+{ord(fake_minus):04X}",
            "binding_total": binding_total,
            "decoy_total": decoy_total,
            "expected_failure_mode": (
                "Vision-anchored models read the em/en-dash as a minus sign and "
                "subtract the adjustment, returning the decoy. Codepoint-aware "
                "readers see U+2014/U+2013 and ADD per the clause."
            ),
        },
    )
    return pdf_bytes, case
