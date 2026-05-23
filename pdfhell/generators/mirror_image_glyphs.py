"""Trap family: horizontally mirrored amount glyphs.

The binding amount is rendered with a horizontal flip (mirror image)
via a negative-x CTM scale. The underlying text stream contains the
correct ASCII digits in correct order, so text extraction reads it
perfectly. A human can hold a mirror (or read the clause and use the
invisible-text fallback) but vision models tend to either skip the
mirrored region, hallucinate digits, or report the visually-salient
upright decoy.

Distinct from upside_down_amount (180° rotation — digits like 0,1,8 are
symmetric so easier to recover) and from vertically_rendered_amount
(90° rotation). A pure horizontal mirror breaks digit recognition for
ALL digits (2,3,4,5,6,7,9) since none are horizontally symmetric in
standard typefaces.
"""
from __future__ import annotations

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C

_VENDORS = [
    "Cobalt Ridge Industries Inc.",
    "Sunwell Marine Services LLC",
    "Drayton & Pike Consulting Ltd.",
    "Halberd Pacific Trading Co.",
    "Westmark Surgical Supply Corp.",
    "Orchard Lane Software Group",
]


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)
    vendor = rng.choice(_VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"

    decoy_total = round(rng.uniform(5000, 18000), 2)
    real_total = round(decoy_total * rng.uniform(1.6, 2.8), 2)

    decoy_str = C.fmt_money(decoy_total)
    real_str = C.fmt_money(real_total)

    case_id = f"mirror_image_glyphs-{seed:04d}"
    question = (
        f"You are processing invoice {invoice_no} from {vendor}. "
        "Per the rendering-convention clause printed on the invoice, what is the "
        "BINDING AMOUNT DUE? Respond with only the amount including currency "
        "symbol, no other text."
    )

    def draw(c: canvas.Canvas) -> None:
        c.setFont("Helvetica-Bold", 22)
        c.drawString(72, 720, "INVOICE")

        c.setFont("Helvetica", 11)
        c.drawString(72, 700, vendor)
        c.drawString(72, 685, f"Invoice #: {invoice_no}")
        c.drawString(72, 670, "Terms: Net 30")

        # Rendering convention clause.
        C.draw_paragraph(
            c,
            "Rendering convention: this invoice is issued under our updated "
            "anti-tampering policy. The PRELIMINARY TOTAL shown in upright "
            "type is a draft figure retained for audit reference only. The "
            "BINDING AMOUNT DUE is rendered as a horizontally-mirrored "
            "(left-right flipped) image of the digits in the box below, and "
            "that figure supersedes all other totals on this page. Read the "
            "mirrored figure by reflection; the numeric value (not its visual "
            "orientation) is what the customer owes.",
            72, 635,
            font=C.FontSpec(size=10),
        )

        # Decoy upright preliminary total.
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 530, "PRELIMINARY TOTAL (draft, non-binding):")
        c.setFont("Helvetica-Bold", 18)
        c.drawRightString(500, 510, decoy_str)

        # Binding box with mirrored amount.
        box_x, box_y, box_w, box_h = 130, 380, 350, 80
        c.setLineWidth(1.2)
        c.rect(box_x, box_y, box_w, box_h)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(box_x + 8, box_y + box_h - 16, "BINDING AMOUNT DUE (mirrored):")

        # Render the real total horizontally mirrored.
        # We use a CTM with negative x-scale around the centre of the box.
        center_x = box_x + box_w / 2
        baseline_y = box_y + 20
        c.saveState()
        # Translate to center, flip x, translate back.
        c.translate(center_x, 0)
        c.scale(-1, 1)
        c.translate(-center_x, 0)
        c.setFont("Helvetica-Bold", 22)
        # drawCentredString puts the text centred at center_x; under the
        # flipped CTM, the underlying text stream still contains the
        # correct ASCII digits in correct order — text extraction reads
        # real_str directly. Only the rasterised glyphs are mirrored.
        c.drawCentredString(center_x, baseline_y, real_str)
        c.restoreState()

        # Invisible redundancy so text-only verifiers pass cleanly.
        C.draw_invisible_text(
            c,
            f"Binding amount due (machine-readable): {real_str}.",
            72, 300, size=10,
        )

        # Filler / footer.
        C.draw_paragraph(
            c,
            "Wire instructions on request. Disputes must be raised in writing "
            "within 10 business days of invoice date. Reference the invoice "
            "number on all correspondence.",
            72, 260, font=C.FontSpec(size=10),
        )

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="mirror_image_glyphs",
        seed=seed,
        question=question,
        expected_answer=real_str,
        forbidden_answers=[decoy_str],
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "decoy_total": decoy_total,
            "real_total": real_total,
            "expected_failure_mode": (
                "Vision-anchored models cannot read horizontally-mirrored "
                "digit glyphs (no digit is left-right symmetric in Helvetica) "
                "and fall back to the upright preliminary decoy. Text-stream "
                "readers and the invisible-text fallback recover the binding "
                "amount trivially."
            ),
        },
    )
    return pdf_bytes, case
