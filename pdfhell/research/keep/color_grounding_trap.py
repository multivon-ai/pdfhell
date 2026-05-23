from __future__ import annotations

from reportlab.lib.colors import red
from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C

_VENDORS = [
    "Crimson Crest Solutions",
    "Azure Dynamics Corp.",
    "Golden Gate Analytics",
    "Veridian Logistics Partners",
    "Saffron Capital Holdings",
    "Cerulean Robotics Inc.",
]

def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    vendor = rng.choice(_VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"

    # The real binding total is defined by the rule (color). The decoy is not.
    # Make them visually distinct in value.
    real_total = round(rng.uniform(5000, 15000), 2)
    decoy_total = round(real_total * rng.uniform(1.5, 2.5), 2)

    # Randomize which total appears first on the page.
    red_on_top = rng.random() < 0.5

    real_str = C.fmt_money(real_total)
    decoy_str = C.fmt_money(decoy_total)

    case_id = f"color_grounding_trap-{seed:04d}"
    question = (
        f"You are processing invoice {invoice_no} from {vendor}. According to the "
        "rules specified in the 'Disambiguation Clause' section, what is the "
        "final binding amount? Respond with only the amount including currency "
        "symbol, no other text."
    )

    def draw(c: canvas.Canvas) -> None:
        c.setFont("Helvetica-Bold", 22)
        c.drawString(72, 720, "INVOICE")

        c.setFont("Helvetica", 11)
        c.drawString(72, 700, vendor)
        c.drawString(72, 685, f"Invoice #: {invoice_no}")
        c.drawString(72, 670, "Terms: Net 30")

        # --- The rule clause ---
        c.setFont("Helvetica-Bold", 12)
        c.drawString(72, 620, "Disambiguation Clause")
        C.draw_paragraph(
            c,
            "Two candidate totals are provided below for reconciliation. The "
            "final, binding amount is the figure rendered in RED ink (RGB 1,0,0). "
            "Any figure rendered in standard black ink is a non-binding preliminary "
            "estimate and must be disregarded.",
            72,
            600,
            font=C.FontSpec(size=10),
        )

        y = 520
        c.line(72, y, C.PAGE_WIDTH - 72, y)
        y -= 25

        # --- The two candidate totals ---
        # Draw them in a random order to avoid positional bias.
        top_total_str, bot_total_str = (
            (real_str, decoy_str) if red_on_top else (decoy_str, real_str)
        )
        top_is_red = red_on_top

        # Top amount
        c.setFont("Helvetica", 12)
        c.drawString(72, y, "Candidate Amount A:")
        if top_is_red:
            c.setFillColor(red)
            c.drawRightString(400, y, top_total_str)
            c.setFillColorRGB(0, 0, 0)  # Reset to black
            C.draw_invisible_text(c, "INTERNAL_NOTE: Color=Red", 410, y)
        else:
            c.drawRightString(400, y, top_total_str)
            C.draw_invisible_text(c, "INTERNAL_NOTE: Color=Black", 410, y)
        y -= 30

        # Bottom amount
        c.drawString(72, y, "Candidate Amount B:")
        if not top_is_red:
            c.setFillColor(red)
            c.drawRightString(400, y, bot_total_str)
            c.setFillColorRGB(0, 0, 0)  # Reset to black
            C.draw_invisible_text(c, "INTERNAL_NOTE: Color=Red", 410, y)
        else:
            c.drawRightString(400, y, bot_total_str)
            C.draw_invisible_text(c, "INTERNAL_NOTE: Color=Black", 410, y)
        y -= 30

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="color_grounding_trap",
        seed=seed,
        question=question,
        expected_answer=real_str,
        forbidden_answers=[decoy_str],
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "real_total": real_total,
            "decoy_total": decoy_total,
            "red_on_top": red_on_top,
            "expected_failure_mode": (
                "Model fails to ground the semantic rule ('the red amount') in the "
                "visual property of the text. It may ignore color and pick the "
                "larger or first-listed amount."
            ),
            "diagnostic": (
                "The invisible text labels allow text-only verifiers to solve this, "
                "isolating the failure to the multimodal model's vision-language "
                "grounding capabilities."
            ),
        },
    )

    return pdf_bytes, case
