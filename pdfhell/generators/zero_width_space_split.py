from __future__ import annotations

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C

# Trap mechanics (since 0.6.1): the Grand Total is drawn as TWO adjacent
# text runs ("$99" + ",051.90") at the exact pen position — visually
# seamless, but text extractors fragment the number at the run boundary
# (pypdf yields "$99\n,051.90"). This is the real-world failure mode the
# family targets: a number that is intact to the eye and broken to a
# text-layer reader.
#
# History: 0.x-0.6.0 injected a literal U+200B into the drawn string.
# That was doubly broken — Helvetica/WinAnsi has no ZWSP glyph, so the
# page rendered a visible black tofu box AND the extracted text carried a
# substitute character, not a zero-width space. Found by the pixels-only
# modality on its first run; see issue #8. Same-seed PDFs from this
# family therefore differ between <=0.6.0 and >=0.6.1.

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

    # Split the real total into two runs after the dollar sign and one or
    # two digits — non-obvious, and guaranteed to land mid-number.
    split_point = rng.randint(2, 3)
    run_a, run_b = real_str_clean[:split_point], real_str_clean[split_point:]

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

        # Draw the real total as "Grand Total" in two adjacent runs at the
        # exact pen position: pixel-identical to one run, fragmented in the
        # text layer.
        c.setFont("Helvetica-Bold", 16)
        c.drawString(300, y, "Grand Total:")
        total_w = stringWidth(real_str_clean, "Helvetica-Bold", 16)
        start_x = 500 - total_w
        c.drawString(start_x, y, run_a)
        c.drawString(start_x + stringWidth(run_a, "Helvetica-Bold", 16), y, run_b)
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
            "split_runs": [run_a, run_b],
            "expected_failure_mode": (
                "Model's text extraction pipeline fragments the 'Grand Total' at the "
                "text-run boundary (extractors yield e.g. '$99' / ',051.90' as separate "
                "tokens). It then falls back to the smaller, textually-intact "
                "'Subtotal' decoy amount."
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
