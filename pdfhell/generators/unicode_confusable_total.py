"""Trap family: unicode confusable in the binding total.

The page shows an invoice with multiple line-item totals. Two candidate
'TOTAL' rows appear: one labeled with a normal ASCII 'TOTAL', another
labeled with a visually-identical 'TОTAL' where the 'O' is the
Cyrillic capital O (U+041E). Visually a human cannot distinguish them;
they must rely on a disambiguating clause in plain text that says: 'The
binding total is the row whose label contains only ASCII Latin
characters.' (or its inverse).

Text-extraction pipelines and strong models that inspect raw bytes can
tell the two rows apart trivially. Vision-only pipelines (and models
that over-rely on the rasterised image) cannot distinguish the labels
and must guess, often picking the first or larger number.

The question is procedurally fair: a careful human reading the
document's vector text (e.g. selecting text in a PDF viewer) can copy
the two TOTAL labels, see the codepoint difference, and apply the
disambiguating rule.
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

# Cyrillic capital O = U+041E (looks like Latin O)
_CYR_O = "\u041e"


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    vendor = rng.choice(_VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"

    amount_a = round(rng.uniform(8000, 25000), 2)
    amount_b = round(amount_a * rng.uniform(1.4, 2.2), 2)

    # Randomise which label (ASCII vs Cyrillic) is the binding one and
    # which amount is on which row.
    ascii_is_binding = rng.random() < 0.5
    ascii_on_top = rng.random() < 0.5

    # Assign amounts to labels independently of position.
    if rng.random() < 0.5:
        ascii_amount, cyr_amount = amount_a, amount_b
    else:
        ascii_amount, cyr_amount = amount_b, amount_a

    binding_amount = ascii_amount if ascii_is_binding else cyr_amount
    decoy_amount = cyr_amount if ascii_is_binding else ascii_amount

    binding_str = C.fmt_money(binding_amount)
    decoy_str = C.fmt_money(decoy_amount)

    ascii_label = "TOTAL"
    cyr_label = f"T{_CYR_O}TAL"  # visually identical

    # The disambiguating clause names which label is binding.
    if ascii_is_binding:
        rule_clause = (
            "For the avoidance of doubt: the binding amount is the row whose "
            "label 'TOTAL' is written entirely in ASCII Latin characters "
            "(Unicode block Basic Latin). Any visually-similar label whose "
            "letters include codepoints from the Cyrillic block (e.g. U+041E) "
            "is a non-binding reference value retained from a prior draft."
        )
    else:
        rule_clause = (
            "For the avoidance of doubt: the binding amount is the row whose "
            "label is written using the Cyrillic capital letter O (U+041E) in "
            "place of the Latin O. Any label written entirely in ASCII Latin "
            "characters is a non-binding reference value retained from a "
            "prior draft."
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
        c.drawRightString(500, y, C.fmt_money(round(ascii_amount * 0.6, 2)))
        y -= 18
        c.drawString(72, y, "Engagement services (prior-draft reconciliation)")
        c.drawRightString(500, y, C.fmt_money(round(cyr_amount * 0.6, 2)))
        y -= 24

        c.line(380, y + 12, 500, y + 12)

        # Two TOTAL rows; identical-looking labels.
        top_label, top_amount = (
            (ascii_label, ascii_amount) if ascii_on_top else (cyr_label, cyr_amount)
        )
        bot_label, bot_amount = (
            (cyr_label, cyr_amount) if ascii_on_top else (ascii_label, ascii_amount)
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
            "ascii_is_binding": ascii_is_binding,
            "ascii_on_top": ascii_on_top,
            "ascii_amount": ascii_amount,
            "cyr_amount": cyr_amount,
            "binding_amount": binding_amount,
            "decoy_amount": decoy_amount,
            "expected_failure_mode": (
                "Vision-only models cannot distinguish ASCII 'O' from "
                "Cyrillic 'O' in the rendered glyphs and so cannot apply "
                "the disambiguation rule; they pick the wrong TOTAL row."
            ),
        },
    )
    return pdf_bytes, case
