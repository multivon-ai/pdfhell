"""Trap family: upside-down (180-degree rotated) binding amount.

The invoice shows a large prominent decoy TOTAL drawn normally, and the
binding amount drawn upside-down (rotated 180 degrees) in a clearly
labeled 'BINDING AMOUNT' box. A printed clause states that the binding
amount is the one inside the box labeled BINDING AMOUNT.

A human reader can tilt the page (or their head) and read the rotated
text. A text-extraction pipeline reads the vector text trivially
regardless of rotation. But vision-language models that rasterize the
page tend to either (a) skip rotated text entirely, (b) hallucinate
digits when trying to read upside-down glyphs, or (c) anchor on the
upright decoy. The codepoints in the text stream are unchanged ASCII
digits — no Unicode trickery — so text-only verifiers solve it cleanly.

Novel vs prior traps: not Unicode confusable, not small print, not
overlay, not encoding. Pure geometric transformation of vector glyphs.
Distinct from `rotated_binding_clause` (which rotated a clause, not the
amount itself, and presumably reverted).
"""
from __future__ import annotations

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C

_VENDORS = [
    "Cobalt Harbor Trading Co.",
    "Westmoor Industrial Supply",
    "Juniper Ridge Analytics Inc.",
    "Ashford Marine Services Ltd.",
    "Stellaris Components LLC",
    "Birchwood Procurement Group",
]


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    vendor = rng.choice(_VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"
    po_no = f"PO-{rng.randint(10000, 99999)}"

    decoy_total = round(rng.uniform(9000, 28000), 2)
    real_total = round(decoy_total * rng.uniform(1.4, 2.3), 2)

    decoy_str = C.fmt_money(decoy_total)
    real_str = C.fmt_money(real_total)

    case_id = f"upside_down_amount-{seed:04d}"
    question = (
        f"You are processing invoice {invoice_no} from {vendor}. "
        "According to the disambiguation clause printed on the invoice, "
        "what is the binding amount owed? Respond with only the amount "
        "including currency symbol, no other text."
    )

    def draw(c: canvas.Canvas) -> None:
        c.setFont("Helvetica-Bold", 22)
        c.drawString(72, 720, "INVOICE")

        c.setFont("Helvetica", 11)
        c.drawString(72, 700, vendor)
        c.drawString(72, 685, f"Invoice #: {invoice_no}")
        c.drawString(72, 670, f"PO Reference: {po_no}")
        c.drawString(72, 655, "Terms: Net 30")

        # Disambiguation clause — plain text, easy to read.
        C.draw_paragraph(
            c,
            "Disambiguation clause: this invoice contains a PRELIMINARY TOTAL "
            "shown in the standard upright orientation for reference only. The "
            "BINDING AMOUNT — the figure the customer is legally obligated to "
            "pay — is printed inside the bordered box labeled 'BINDING AMOUNT' "
            "below, rotated 180 degrees per our document-security convention. "
            "In case of any discrepancy, the BINDING AMOUNT governs.",
            72, 620,
            font=C.FontSpec(size=10),
        )

        # Decoy preliminary total, upright and prominent.
        c.setFont("Helvetica-Bold", 12)
        c.drawString(72, 520, "PRELIMINARY TOTAL (reference only):")
        c.setFont("Helvetica-Bold", 18)
        c.drawRightString(500, 500, decoy_str)

        # Binding amount box, drawn upside-down.
        box_x, box_y, box_w, box_h = 180, 280, 250, 90
        c.setLineWidth(1.2)
        c.rect(box_x, box_y, box_w, box_h)

        # Draw the label and the real amount rotated 180 degrees.
        # We translate to the box's far corner and rotate 180, so text
        # drawn at (0,0) relative-frame appears upside-down inside the
        # box from the viewer's perspective.
        c.saveState()
        # Translate to top-right of box, then rotate 180.
        c.translate(box_x + box_w, box_y + box_h)
        c.rotate(180)
        # Now (0,0) is the bottom-left of an inverted frame.
        c.setFont("Helvetica-Bold", 11)
        c.drawString(12, box_h - 22, "BINDING AMOUNT")
        c.setFont("Helvetica-Bold", 20)
        c.drawString(12, box_h - 60, real_str)
        c.restoreState()

        c.setFont("Helvetica-Oblique", 9)
        c.drawString(72, 230, "(Box contents rotated 180 degrees per security convention — see clause above.)")

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    # Sanity: byte-determinism is enforced by canvas_to_bytes(invariant=True).

    case = HellCase(
        id=case_id,
        trap_family="upside_down_amount",
        seed=seed,
        question=question,
        expected_answer=real_str,
        forbidden_answers=[decoy_str],
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "po_no": po_no,
            "decoy_total": decoy_total,
            "real_total": real_total,
            "expected_failure_mode": (
                "Vision models skip or misread the 180-degree rotated text in "
                "the BINDING AMOUNT box and default to the upright decoy. "
                "Text-extraction pipelines read the rotated glyphs as normal "
                "ASCII because the codepoints in the content stream are "
                "unchanged — only the CTM is rotated."
            ),
        },
    )
    return pdf_bytes, case
