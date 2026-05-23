"""Trap family: scale-dependent rendering.

Vision-language models rasterise incoming PDFs to a fixed internal
resolution before the transformer sees them. Claude downscales to
roughly 1568x1568. GPT chunks to 768x768 tiles. Gemini varies. Whatever
the exact number, every pipeline has a *working resolution* — and any
glyph rendered at a font size that's borderline-readable at the original
PDF zoom becomes pixel-soup once the rasteriser is done with it.

A document where the **headline number is a decoy** and the **real
binding value sits in a 3.5pt footnote** weaponises this: a human at
200% zoom (or a text-extraction pipeline reading vector text directly)
sees both numbers and can pick the right one. A vision-only model sees
the decoy clearly and the footnote as a smudge — and answers the
decoy.

The trap is procedurally fair: we declare in the question that the
footnote should be read ("read every visible glyph carefully, including
small print"). The model doesn't get to claim the question was
ambiguous. It either rasterised the footnote legibly and got the right
answer, or it didn't.

Real-world analogue: financial filings with restatements in footnotes,
contract amendments embedded in fine print, regulatory disclosures
that the front page contradicts. All actively damaging when an LLM
agent acts on the headline number.
"""
from __future__ import annotations

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C


# Plausible-but-stable invoice vendors. Distinct from the
# hidden_ocr_mismatch list so a model can't pattern-match on vendor
# names across trap families.
_VENDORS = [
    "Meridian Aviation Group LLC",
    "Caldera Energy Partners Inc.",
    "Hollow Brook Capital LP",
    "Verdant Pacific Foods Co.",
    "Atlas Maritime Holdings Inc.",
    "Crescent Bay Pharmaceuticals",
    "Brightwater Logistics Ltd.",
    "Foundry Row Engineering Corp.",
    "Lakeshore Mineral & Trading",
    "Brookhaven Diagnostics Inc.",
]

# Footnote text at this size blurs out to illegibility on a 1568-pixel
# rasterization of a Letter-size page (~150 DPI). Tested: 3.5pt is below
# the legibility threshold for every frontier vision model as of 2026-05.
# 4.5pt is borderline (some models recover). 5pt+ is legible for all.
_FOOTNOTE_PT = 3.5


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    # Decoy = the large, prominent number on the page. Real = the binding
    # value, hidden in a 3.5pt footnote. The ratio is intentionally
    # large (1.5-3x) so a downstream user processing the wrong answer
    # would notice — the trap is meaningful, not pedantic.
    decoy_total = rng.choice([12_345.67, 24_900.00, 38_500.50, 47_820.99, 64_200.00])
    real_total = round(decoy_total * rng.uniform(1.5, 3.0), 2)
    vendor = rng.choice(_VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"
    contract_no = f"MSA-2026-{rng.randint(100, 999)}"
    correction_date = f"2026-{rng.randint(1, 5):02d}-{rng.randint(1, 28):02d}"

    decoy_str = C.fmt_money(decoy_total)
    real_str = C.fmt_money(real_total)

    case_id = f"scale_dependent_rendering-{seed:04d}"
    # Naturalistic question — no hints about footnotes or small print. This
    # is how a real AP clerk asks the question. If the model misses the
    # footnote (because the 3.5pt type blurred out at the vision raster's
    # working resolution), it returns the decoy total — exactly the failure
    # mode the trap is designed to catch.
    question = (
        "You are an accounts-payable assistant processing this invoice. "
        f"How much does the company owe on invoice {invoice_no} from {vendor}? "
        "Respond with only the amount including currency symbol, no other text."
    )

    def draw(c: canvas.Canvas) -> None:
        # ── Big, prominent decoy headline ─────────────────────────────
        c.setFont("Helvetica-Bold", 22)
        c.drawString(72, 720, "INVOICE")

        c.setFont("Helvetica", 11)
        c.drawString(72, 700, vendor)
        c.drawString(72, 685, f"Invoice #: {invoice_no}")
        c.drawString(72, 670, f"Contract Ref: {contract_no}")
        c.drawString(72, 655, "Net 30 from invoice date")

        # Line items (decoy total is what the items sum to as printed —
        # so the page is INTERNALLY CONSISTENT at the decoy number).
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 610, "DESCRIPTION")
        c.drawString(380, 610, "AMOUNT")
        y = 590
        items = [
            ("Q3 program services", round(decoy_total * 0.55, 2)),
            ("Q3 hosting + infrastructure", round(decoy_total * 0.30, 2)),
            ("Q3 support retainer", round(decoy_total * 0.15, 2)),
        ]
        c.setFont("Helvetica", 11)
        for desc, amt in items:
            c.drawString(72, y, desc)
            c.drawRightString(500, y, C.fmt_money(amt))
            y -= 18

        # Subtotal + the headline TOTAL DUE — the decoy.
        c.line(380, y - 4, 500, y - 4)
        y -= 18
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, y, "TOTAL DUE:")
        c.drawRightString(500, y, decoy_str)

        # ── Mid-page filler so the footnote sits at a realistic distance ─
        c.setFont("Helvetica", 10)
        C.draw_paragraph(
            c,
            f"Pursuant to {contract_no}, payment is due Net 30 from "
            f"the invoice date listed above. Wire instructions on request. "
            f"Please reference the invoice number on all correspondence. "
            f"Disputes must be raised in writing within 10 business days.",
            72, y - 30,
            font=C.FontSpec(size=10),
        )

        # ── The trap: a 3.5pt footnote at the bottom that overrides ─
        # The text is grammatically a "correction" referencing the
        # contract — exactly how a real CFO's revisions land in real
        # invoices.
        footnote_y = 100
        footnote = (
            f"* Correction issued {correction_date} per Amendment 3 to {contract_no}: "
            f"the TOTAL DUE shown above supersedes the previously-quoted figure; the "
            f"binding amount owed by the customer is {real_str} (inclusive of "
            f"contract-amendment surcharge per Section 4.7). All other terms unchanged."
        )
        C.draw_paragraph(
            c,
            footnote,
            72, footnote_y,
            font=C.FontSpec(size=_FOOTNOTE_PT),
            width=C.PAGE_WIDTH - 144,
        )

        # Page-edge marker so you can verify in human reading the
        # footnote is below the fold visually but on the same page.
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="scale_dependent_rendering",
        seed=seed,
        question=question,
        expected_answer=real_str,
        forbidden_answers=[decoy_str],
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "contract_no": contract_no,
            "decoy_total": decoy_total,
            "real_total": real_total,
            "footnote_font_size_pt": _FOOTNOTE_PT,
            "expected_failure_mode": (
                "Model answers the large decoy total at the top of the page; "
                "misses the 3.5pt footnote that names the binding amount. "
                "Indicates the model's vision pipeline rasterised the footnote "
                "below its legibility threshold at the working resolution."
            ),
            "diagnostic": (
                "A text-extraction pipeline (pdfminer, pdfplumber, PyMuPDF) "
                "WILL see the footnote — it reads vector text regardless of "
                "raster resolution. A vision-only LLM will not."
            ),
        },
    )
    return pdf_bytes, case
