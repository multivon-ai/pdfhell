"""Trap family: checksum-validated invoice number selection.

The page shows two candidate invoice numbers (e.g. INV-A and INV-B) with
their associated amounts. A clause states that the binding invoice is
the one whose numeric digits sum to a multiple of a small integer K
(e.g. K=7). The model must (a) extract digits from each invoice number,
(b) compute the digit-sum mod K, (c) identify which invoice satisfies
the rule, (d) report THAT invoice's amount.

Distinct from prior decode traps (octal/hex/base64/morse) — there's no
encoding to decode. The numbers are plain ASCII. Distinct from
sum_reconciliation (which gate-failed on forbidden_clean) because the
binding amount appears as a single labeled value, not a sum the
verifier might recompute and quote.

Weaker models grab the more salient/first amount or skip the arithmetic
check. Strong reasoners actually perform the digit-sum check.
"""
from __future__ import annotations

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C

_VENDORS = [
    "Cobalt Ridge Industrial Co.",
    "Sundial Forge Manufacturing",
    "Briarwood Analytics LLC",
    "Northpoint Marine Supply",
    "Veridian Crop Sciences Inc.",
    "Halcyon Press Holdings",
]


def _digit_sum(s: str) -> int:
    return sum(int(c) for c in s if c.isdigit())


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)
    vendor = rng.choice(_VENDORS)
    K = rng.choice([7, 9, 11])

    # Generate two invoice numbers: exactly one has digit-sum divisible by K.
    def gen_inv(divisible: bool) -> str:
        for _ in range(2000):
            n = rng.randint(100000, 999999)
            if (_digit_sum(str(n)) % K == 0) == divisible:
                return f"INV-{n}"
        raise RuntimeError("unreachable")

    binding_inv = gen_inv(True)
    decoy_inv = gen_inv(False)

    binding_amount = round(rng.uniform(8000, 25000), 2)
    decoy_amount = round(binding_amount * rng.uniform(1.4, 2.2), 2)
    # Randomize which is larger to avoid "pick the bigger one" heuristic.
    if rng.random() < 0.5:
        binding_amount, decoy_amount = decoy_amount, binding_amount

    binding_str = C.fmt_money(binding_amount)
    decoy_str = C.fmt_money(decoy_amount)

    binding_on_top = rng.random() < 0.5

    case_id = f"checksum_validation_rule-{seed:04d}"
    question = (
        f"You are processing invoices from {vendor}. Per the validation rule "
        "printed on the document, what is the AMOUNT DUE on the binding "
        "invoice? Respond with only the amount including currency symbol, "
        "no other text."
    )

    def draw(c: canvas.Canvas) -> None:
        c.setFont("Helvetica-Bold", 22)
        c.drawString(72, 720, "INVOICE BATCH")

        c.setFont("Helvetica", 11)
        c.drawString(72, 700, vendor)
        c.drawString(72, 685, "Terms: Net 30")

        C.draw_paragraph(
            c,
            "Validation rule: this batch contains two candidate invoice records. "
            f"The BINDING invoice is the one whose numeric digits (ignoring the "
            f"'INV-' prefix and any hyphens) sum to a value that is evenly "
            f"divisible by {K}. The other record is a superseded draft retained "
            "for audit and must not be paid. Apply this rule strictly when "
            "identifying the AMOUNT DUE.",
            72, 650,
            font=C.FontSpec(size=10),
        )

        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 560, "INVOICE NO.")
        c.drawRightString(500, 560, "AMOUNT DUE")

        top_inv, top_amt = (
            (binding_inv, binding_str) if binding_on_top else (decoy_inv, decoy_str)
        )
        bot_inv, bot_amt = (
            (decoy_inv, decoy_str) if binding_on_top else (binding_inv, binding_str)
        )

        c.setFont("Helvetica", 12)
        y = 535
        c.drawString(72, y, top_inv)
        c.drawRightString(500, y, top_amt)
        y -= 22
        c.drawString(72, y, bot_inv)
        c.drawRightString(500, y, bot_amt)

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="checksum_validation_rule",
        seed=seed,
        question=question,
        expected_answer=binding_str,
        forbidden_answers=[decoy_str],
        metadata={
            "vendor": vendor,
            "K": K,
            "binding_inv": binding_inv,
            "decoy_inv": decoy_inv,
            "binding_digit_sum": _digit_sum(binding_inv),
            "decoy_digit_sum": _digit_sum(decoy_inv),
            "binding_amount": binding_amount,
            "decoy_amount": decoy_amount,
            "expected_failure_mode": (
                "Weaker models skip the digit-sum arithmetic check and pick "
                "the more salient/first/larger invoice. Strong reasoners "
                "compute digit sums mod K and select correctly."
            ),
        },
    )
    return pdf_bytes, case
