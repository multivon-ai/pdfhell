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

    # Binding vs decoy: visually, the decoy is larger (salient) but non-bold;
    # the binding amount is bold but smaller. Clause says bold binds.
    binding_amount = round(rng.uniform(9000, 18000), 2)
    decoy_amount = round(binding_amount * rng.uniform(1.25, 1.9), 2)

    binding_str = C.fmt_money(binding_amount)
    decoy_str = C.fmt_money(decoy_amount)

    # Randomise which row appears first to avoid position heuristics.
    binding_first = rng.random() < 0.5

    case_id = f"boldface_binding_rule-{seed:04d}"
    question = (
        f"You are processing invoice {invoice_no} from {vendor}. Per the formatting "
        "key printed on the page, only the dollar figure set in boldface is binding. "
        "What is the amount owed? Respond with only the amount including the currency "
        "symbol, no other text."
    )

    def draw(c: canvas.Canvas) -> None:
        c.setFont("Helvetica-Bold", 22)
        c.drawString(72, 720, "INVOICE")

        c.setFont("Helvetica", 11)
        c.drawString(72, 700, vendor)
        c.drawString(72, 685, f"Invoice #: {invoice_no}")
        c.drawString(72, 670, "Terms: Net 30")

        # Formatting key (explicit rule). Parenthetical ensures text-only
        # extractors have an accessible hint mapping style -> token.
        C.draw_paragraph(
            c,
            "Formatting key: figures typeset in boldface indicate binding amounts. "
            "Regular-weight figures are non-binding references retained for context. "
            "(In the accessible text layer: bold amounts are annotated as [bold], "
            "regular as [regular].)",
            72,
            635,
            font=C.FontSpec(size=10),
        )

        # A couple of filler line items for realism (values do not need to sum).
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 580, "DESCRIPTION")
        c.drawRightString(500, 580, "AMOUNT")
        c.setFont("Helvetica", 11)
        c.drawString(72, 560, "Consulting services (current period)")
        c.drawRightString(500, 560, C.fmt_money(round(binding_amount * 0.6, 2)))
        c.drawString(72, 542, "Infrastructure & hosting")
        c.drawRightString(500, 542, C.fmt_money(round(binding_amount * 0.35, 2)))

        y = 500
        c.line(380, y + 6, 500, y + 6)

        # Two TOTAL rows: one is bold (binding), one is regular (decoy, larger size).
        def draw_binding_row(ypos: float) -> None:
            c.setFont("Helvetica-Bold", 13)
            c.drawString(72, ypos, "TOTAL DUE:")
            c.drawRightString(500, ypos, binding_str)
            # Invisible accessibility tag for text-extractors
            C.draw_invisible_text(c, " [bold]", 505, ypos)

        def draw_decoy_row(ypos: float) -> None:
            c.setFont("Helvetica", 16)  # visually more salient but non-bold
            c.drawString(72, ypos, "TOTAL DUE:")
            c.drawRightString(500, ypos, decoy_str)
            # Invisible accessibility tag for text-extractors
            C.draw_invisible_text(c, " [regular]", 505, ypos)

        if binding_first:
            draw_binding_row(480)
            draw_decoy_row(455)
        else:
            draw_decoy_row(480)
            draw_binding_row(455)

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="boldface_binding_rule",
        seed=seed,
        question=question,
        expected_answer=binding_str,
        forbidden_answers=[],
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "binding_amount": binding_amount,
            "decoy_amount": decoy_amount,
            "binding_is_bold": True,
            "binding_row_first": binding_first,
            "expected_failure_mode": (
                "Model ignores typographic weight in favor of salience (larger non-bold number) "
                "and answers the decoy. Text-only verifiers can use the invisible [bold]/[regular] "
                "annotations; humans can rely on boldface as instructed."
            ),
        },
    )
    return pdf_bytes, case
