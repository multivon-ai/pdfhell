from __future__ import annotations

from reportlab.pdfgen import canvas
from reportlab.lib import colors

from ..case import HellCase
from . import _common as C

_VENDORS = [
    "Harborline Freight Partners",
    "Greyloft Avionics Inc.",
    "Solstice Imaging Inc.",
    "Northwind Robotics Ltd.",
    "Ferncliff Analytics Ltd.",
    "Quillmark Publishing Group",
]


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    vendor = rng.choice(_VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"

    # Make the unshaded decoy salient and larger.
    decoy_total = round(rng.uniform(12000, 45000), 2)
    # Binding (shaded) total is a distinct smaller value to induce salience bias.
    binding_total = round(decoy_total * rng.uniform(0.55, 0.85), 2)

    decoy_str = C.fmt_money(decoy_total)
    binding_str = C.fmt_money(binding_total)

    case_id = f"shaded_box_binding_rule-{seed:04d}"
    question = (
        f"You are processing invoice {invoice_no} from {vendor}. Per the printed policy, "
        "only the amount shown inside the shaded gray box is binding. What is the amount due? "
        "Respond with only the amount including the currency symbol, no other text."
    )

    def draw(c: canvas.Canvas) -> None:
        # Header
        c.setFont("Helvetica-Bold", 22)
        c.drawString(72, 720, "INVOICE")
        c.setFont("Helvetica", 11)
        c.drawString(72, 700, vendor)
        c.drawString(72, 685, f"Invoice #: {invoice_no}")
        c.drawString(72, 670, "Terms: Net 30")

        # Binding rule clause.
        C.draw_paragraph(
            c,
            (
                "Binding rule: The amount displayed inside the shaded gray box is the "
                "only binding 'Amount Due'. Any other totals, including larger and more "
                "prominent figures shown in unshaded boxes, are non-binding references."
            ),
            72,
            635,
            font=C.FontSpec(size=10),
        )

        # Content filler (line items) to make layout natural.
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 560, "DESCRIPTION")
        c.drawRightString(500, 560, "AMOUNT")
        c.setFont("Helvetica", 11)
        y = 540
        items = [
            ("Program services", round(binding_total * 0.45, 2)),
            ("Hosting & infrastructure", round(binding_total * 0.35, 2)),
            ("Support retainer", round(binding_total * 0.20, 2)),
        ]
        for desc, amt in items:
            c.drawString(72, y, desc)
            c.drawRightString(500, y, C.fmt_money(amt))
            y -= 18

        # Two totals: a large unshaded decoy, and a shaded binding box.
        # Layout: decoy on top (larger), shaded binding below.
        # Box dimensions
        box_w, box_h = 420, 56
        left_x = 72
        right_x = 72 + box_w

        # Unshaded decoy box (stroke only)
        decoy_y = 430
        c.setStrokeColor(colors.black)
        c.setLineWidth(1)
        c.rect(left_x, decoy_y, box_w, box_h, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(left_x + 10, decoy_y + box_h - 18, "Preliminary Total (non-binding)")
        c.setFont("Helvetica-Bold", 18)
        # Invisible tag to make text-only verifiers answerable (marks unshaded)
        C.draw_invisible_text(c, "[UNSHADED] ", right_x - 10 - 200, decoy_y + 18)
        c.drawRightString(right_x - 10, decoy_y + 18, decoy_str)

        # Shaded binding box (light gray fill)
        bind_y = 350
        c.setFillColorRGB(0.92, 0.92, 0.92)
        c.rect(left_x, bind_y, box_w, box_h, stroke=0, fill=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(left_x + 10, bind_y + box_h - 18, "Certified Total (binding)")
        c.setFont("Helvetica-Bold", 14)
        # Invisible tag right before the visible amount to bind text-layer semantics
        C.draw_invisible_text(c, "[SHADED] ", right_x - 10 - 200, bind_y + 18)
        c.drawRightString(right_x - 10, bind_y + 18, binding_str)

        # Small footer
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="shaded_box_binding_rule",
        seed=seed,
        question=question,
        expected_answer=binding_str,
        forbidden_answers=[],
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "binding_total": binding_total,
            "decoy_total": decoy_total,
            "visual_cue": "shaded_box",
            "decoy_salience": "larger_font_unshaded",
            "expected_failure_mode": (
                "Model anchors on the larger unshaded total and ignores the shading-based rule; "
                "models that ground visual background fills or read the invisible [SHADED] tag via "
                "text extraction return the correct shaded-box amount."
            ),
        },
    )
    return pdf_bytes, case
