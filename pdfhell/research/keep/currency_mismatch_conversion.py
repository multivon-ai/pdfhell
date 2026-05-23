from __future__ import annotations

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C

_VENDORS = [
    "Redwood Industrial Systems LLC",
    "Bluefin Maritime Services Ltd.",
    "Northline Data Centers Inc.",
    "Sable Ridge Consulting Co.",
    "Cobalt Harbor Biologics",
    "Altavista Freight & Logistics",
    "Keystone Hydro Works",
    "Aurora Field Engineering",
    "Summit Ridge Minerals",
    "Horizon Analytics Group",
]


def _money_from_cents(cents: int, currency: str) -> str:
    return C.fmt_money(cents / 100.0, currency)


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    vendor = C.pick_from(rng, _VENDORS)
    invoice_no = f"INV-{rng.randint(100000, 999999)}"
    po_no = f"PO-{rng.randint(2000, 9999)}"

    # Choose a clean EUR total in whole cents and a plausible FX rate.
    euro_total_cents = rng.choice([
        1234567, 2490000, 385005, 478209, 642000, 915500, 1532750, 2079400
    ])  # e.g., 12,345.67 EUR etc.

    fx_rate = C.pick_from(rng, [1.06, 1.09, 1.12, 1.15, 1.18, 1.21, 1.24, 1.27, 1.30, 1.33])
    usd_total = round((euro_total_cents / 100.0) * fx_rate + 1e-9, 2)

    eur_str = _money_from_cents(euro_total_cents, "€")
    usd_str = C.fmt_money(usd_total, "$")

    # Split line items so they sum exactly to the EUR total.
    a1 = int(round(euro_total_cents * 0.55))
    a2 = int(round(euro_total_cents * 0.30))
    a3 = euro_total_cents - a1 - a2

    case_id = f"currency_mismatch_conversion-{seed:04d}"

    question = (
        "You are an accounts-payable assistant. The invoice totals are shown in EUR, "
        "but the settlement note specifies USD payment at the stated FX rate. "
        f"How much (in USD) should be paid for invoice {invoice_no}? Respond with only the amount including currency symbol."
    )

    def draw(c: canvas.Canvas) -> None:
        # Header
        c.setFont("Helvetica-Bold", 22)
        c.drawString(72, 730, "INVOICE")

        c.setFont("Helvetica", 11)
        c.drawString(72, 710, vendor)
        c.drawString(72, 695, f"Invoice #: {invoice_no}")
        c.drawString(72, 680, f"PO Reference: {po_no}")
        c.drawString(72, 665, "Net 30 from invoice date")

        # Bill/Ship columns (light filler)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 640, "BILL TO")
        c.drawString(320, 640, "SHIP TO")
        c.setFont("Helvetica", 10)
        c.drawString(72, 625, "Accounts Payable")
        c.drawString(320, 625, "Receiving Dock")

        # Line items in EUR
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 600, "DESCRIPTION")
        c.drawString(420, 600, "AMOUNT (EUR)")
        y = 582
        c.setFont("Helvetica", 11)
        c.drawString(72, y, "Q3 program services")
        c.drawRightString(520, y, _money_from_cents(a1, "€"))
        y -= 18
        c.drawString(72, y, "Q3 hosting + infrastructure")
        c.drawRightString(520, y, _money_from_cents(a2, "€"))
        y -= 18
        c.drawString(72, y, "Q3 support retainer")
        c.drawRightString(520, y, _money_from_cents(a3, "€"))
        y -= 10
        c.line(420, y, 520, y)
        y -= 22

        # Prominent EUR total (decoy for USD question)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, y, "TOTAL DUE (EUR):")
        c.drawRightString(520, y, eur_str)

        # Policy note: payable in USD at given FX rate
        y -= 28
        c.setFont("Helvetica", 10)
        C.draw_paragraph(
            c,
            (
                "Settlement note: All amounts are payable in USD. Apply conversion at settlement "
                f"using the published rate 1 EUR = {fx_rate:.2f} USD. Round to the nearest cent. "
                "Wire USD to the account on file."
            ),
            72, y,
            font=C.FontSpec(size=10),
            width=C.PAGE_WIDTH - 144,
        )

        # Small print to anchor the instruction but still fully legible
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(72, 90, "Note: For reporting, amounts may be shown in EUR; settlement occurs in USD per rate above.")
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="currency_mismatch_conversion",
        seed=seed,
        question=question,
        expected_answer=usd_str,
        forbidden_answers=[C.fmt_money(euro_total_cents / 100.0, "$")],  # common error: slap $ on the EUR number
        metadata={
            "vendor": vendor,
            "invoice_no": invoice_no,
            "po_no": po_no,
            "eur_total": euro_total_cents / 100.0,
            "usd_rate": fx_rate,
            "usd_total": usd_total,
            "expected_failure_mode": (
                "Model returns the visibly prominent EUR total or attaches a $ to it, "
                "ignoring the conversion note or failing the arithmetic."
            ),
            "diagnostic": (
                "A careful reader converts EUR to USD at the stated rate and rounds to 2dp."
            ),
        },
    )

    return pdf_bytes, case
