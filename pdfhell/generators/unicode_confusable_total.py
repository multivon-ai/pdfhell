"""Trap family: confusable glyph in the binding total's label.

The page shows an invoice with two candidate 'TOTAL' rows: one labeled
with the word TOTAL spelled entirely with letters, another labeled
'T0TAL' where the O is the DIGIT ZERO (U+0030). In Helvetica-Bold the
two glyphs are easy to skim past and hard to discriminate at a glance;
a disambiguating clause in plain text states which row is binding.

Text-extraction pipelines can tell the two rows apart trivially (the
codepoints differ). Vision pipelines must do careful glyph-level
discrimination — exactly the skill OCR confusions punish in the wild.
The question is procedurally fair: a careful human can zoom in, spot
the zero, and apply the clause.

History: through 0.6.0 this family used the Cyrillic capital O
(U+041E) and claimed the labels were "visually identical". They were
not — Helvetica's WinAnsi encoding has no Cyrillic glyphs, so the page
rendered a visible tofu box ("T■TAL:") and even the extracted text
carried the substitute character, never a Cyrillic codepoint. Found by
the pixels-only modality + the glyph_clean gate (issue #8). Same-seed
PDFs differ between <=0.6.0 and >=0.6.1.
"""
from __future__ import annotations

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C

_VENDORS = [
    "Northwind Robotics Ltd.",
    "Sablefin Capital Group",
    "Greyloft Avionics Inc.",
    "Pinecrest Materials Co.",
    "Hartwell Biosciences PLC",
    "Ironvale Logistics LLC",
]


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    vendor = rng.choice(_VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"

    amount_a = round(rng.uniform(8000, 25000), 2)
    amount_b = round(amount_a * rng.uniform(1.4, 2.2), 2)

    # Randomise which label (letter vs digit-zero) is the binding one and
    # which amount is on which row.
    letter_is_binding = rng.random() < 0.5
    letter_on_top = rng.random() < 0.5

    # Assign amounts to labels independently of position.
    if rng.random() < 0.5:
        letter_amount, zero_amount = amount_a, amount_b
    else:
        letter_amount, zero_amount = amount_b, amount_a

    binding_amount = letter_amount if letter_is_binding else zero_amount
    decoy_amount = zero_amount if letter_is_binding else letter_amount

    binding_str = C.fmt_money(binding_amount)
    decoy_str = C.fmt_money(decoy_amount)

    letter_label = "TOTAL"
    zero_label = "T0TAL"  # digit zero in place of the letter O

    # The disambiguating clause names which label is binding.
    if letter_is_binding:
        rule_clause = (
            "For the avoidance of doubt: the binding amount is the row whose "
            "label 'TOTAL' is spelled entirely with letters. Any "
            "similar-looking label containing the digit zero (0, U+0030) in "
            "place of the letter O is a non-binding reference value retained "
            "from a prior draft."
        )
    else:
        rule_clause = (
            "For the avoidance of doubt: the binding amount is the row whose "
            "label is written with the digit zero (0, U+0030) in place of "
            "the letter O. Any label spelled entirely with letters is a "
            "non-binding reference value retained from a prior draft."
        )

    case_id = f"unicode_confusable_total-{seed:04d}"
    question = (
        f"You are processing invoice {invoice_no} from {vendor}. According to "
        "the disambiguation clause printed on the invoice, what is the binding "
        "amount owed? Respond with only the amount including currency symbol, "
        "no other text."
    )

    def draw(c: canvas.Canvas) -> None:
        c.setFont("Helvetica-Bold", 22)
        c.drawString(72, 720, "INVOICE")

        c.setFont("Helvetica", 11)
        c.drawString(72, 700, vendor)
        c.drawString(72, 685, f"Invoice #: {invoice_no}")
        c.drawString(72, 670, "Terms: Net 30")

        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 620, "DESCRIPTION")
        c.drawRightString(500, 620, "AMOUNT")

        y = 600
        c.setFont("Helvetica", 11)
        c.drawString(72, y, "Engagement services (current period)")
        c.drawRightString(500, y, C.fmt_money(round(letter_amount * 0.6, 2)))
        y -= 18
        c.drawString(72, y, "Engagement services (prior-draft reconciliation)")
        c.drawRightString(500, y, C.fmt_money(round(zero_amount * 0.6, 2)))
        y -= 24

        c.line(380, y + 12, 500, y + 12)

        # Two TOTAL rows; near-identical labels.
        top_label, top_amount = (
            (letter_label, letter_amount) if letter_on_top else (zero_label, zero_amount)
        )
        bot_label, bot_amount = (
            (zero_label, zero_amount) if letter_on_top else (letter_label, letter_amount)
        )

        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, y, f"{top_label}:")
        c.drawRightString(500, y, C.fmt_money(top_amount))
        y -= 22
        c.drawString(72, y, f"{bot_label}:")
        c.drawRightString(500, y, C.fmt_money(bot_amount))
        y -= 40

        c.setFont("Helvetica-Oblique", 9)
        C.draw_paragraph(
            c,
            rule_clause,
            72, y,
            font=C.FontSpec(family="Helvetica-Oblique", size=9),
            width=C.PAGE_WIDTH - 144,
        )

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="unicode_confusable_total",
        seed=seed,
        question=question,
        expected_answer=binding_str,
        forbidden_answers=[decoy_str],
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "letter_is_binding": letter_is_binding,
            "letter_on_top": letter_on_top,
            "letter_amount": letter_amount,
            "zero_amount": zero_amount,
            "binding_amount": binding_amount,
            "decoy_amount": decoy_amount,
            "expected_failure_mode": (
                "Models skim past the digit zero in 'T0TAL' (or cannot "
                "discriminate the 0 vs O glyphs in the render) and so cannot "
                "apply the disambiguation rule; they pick the wrong TOTAL row."
            ),
        },
    )
    return pdf_bytes, case
