from __future__ import annotations

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C

# Zero-width space, U+200B. A non-printing character that can break tokenization.
_ZWSP = "\u200b"

_VENDORS = [
    "Quantum Leap Innovations",
    "Starlight Data Corp.",
    "Silverstream Analytics",
    "Apex Digital Group",
    "Blue Ridge Robotics",
]

def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    vendor = C.pick_from(rng, _VENDORS)
    invoice_no = f"INV-{rng.randint(20000, 80000)}"

    # The real total is a large number that will be visually correct but
    # textually "split" by a zero-width space.
    real_total = round(rng.uniform(75000, 150000), 2)
    # The decoy is a smaller, plausible number that is textually intact.
    decoy_total = round(real_total / rng.uniform(10, 20), 2)

    # Format the numbers for rendering and for the expected answer.
    real_str_clean = C.fmt_money(real_total)
    decoy_str = C.fmt_money(decoy_total)

    # Inject the zero-width space into the real total string.
    # e.g., "$123,456.78" -> "$12\u200b3,456.78"
    # This position is chosen to be non-obvious but also likely to break parsing.
    # Split after the dollar sign and one or two digits.
    split_point = rng.randint(2, 3)
    real_str_split = real_str_clean[:split_point] + _ZWSP + real_str_clean[split_point:]

    case_id = f"zero_width_space_split-{seed:04d}"
    question = (
        f"You are processing invoice {invoice_no} from {vendor}. "
        "What is the Grand Total? Respond with only the final amount, "
        "including the currency symbol."
    )

    def draw(c: canvas.Canvas) -> None:
        c.setFont("Helvetica-Bold", 24)
        c.drawString(72, 750, "INVOICE")

        c.setFont("Helvetica", 11)
        c.drawString(72, 720, vendor)
        c.drawString(72, 705, f"Invoice No: {invoice_no}")

        # Draw line items that sum to the decoy total, making it seem plausible.
        items = [
            ("Consulting Services", decoy_total * 0.6),
            ("Platform Licensing", decoy_total * 0.4),
        ]
        y = 650
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, y, "Item Description")
        c.drawRightString(500, y, "Amount")
        y -= 20
        c.setFont("Helvetica", 11)
        for desc, amt in items:
            c.drawString(72, y, desc)
            c.drawRightString(500, y, C.fmt_money(amt))
            y -= 18

        # Draw the decoy total as a "Subtotal".
        y -= 10
        c.line(380, y, 500, y)
        y -= 20
        c.setFont("Helvetica-Bold", 12)
        c.drawString(300, y, "Subtotal:")
        c.drawRightString(500, y, decoy_str)
        y -= 25

        # Draw the real total as "Grand Total" using the split string.
        # Visually, it will look perfectly normal.
        c.setFont("Helvetica-Bold", 16)
        c.drawString(300, y, "Grand Total:")
        c.drawRightString(500, y, real_str_split)
        y -= 40

        C.draw_paragraph(
            c,
            "Payment is due upon receipt. Please remit the Grand Total amount specified. "
            "Any discrepancies should be reported within five business days.",
            x=72,
            y=y,
            font=C.FontSpec(size=9),
        )

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="zero_width_space_split",
        seed=seed,
        question=question,
        expected_answer=real_str_clean,
        forbidden_answers=[decoy_str],
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "real_total": real_total,
            "decoy_total": decoy_total,
            "split_string": real_str_split.replace(_ZWSP, "[ZWSP]"),
            "expected_failure_mode": (
                "Model's text extraction pipeline fails to handle the zero-width space "
                "(U+200B) in the 'Grand Total', fragmenting the number. It then falls back "
                "to the smaller, textually-intact 'Subtotal' decoy amount."
            ),
            "diagnostic": (
                "Visually, the 'Grand Total' is unambiguous. A text-extraction-only "
                "pipeline may see a broken string (e.g., '$98', ',765.43') which a "
                "naive model could misinterpret. A vision-capable model should read the "
                "pixels and get the correct answer."
            ),
        },
    )
    return pdf_bytes, case
