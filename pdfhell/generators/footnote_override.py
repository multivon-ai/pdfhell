"""Trap family: footnote override.

The body of the document states a contractual position confidently — for
example, *"Customer's liability shall be capped at twelve (12) months of
fees paid."* — but a 6pt footnote near the bottom of the page overrides
it: *"Notwithstanding the foregoing, liability for breaches of Sections
4.2 (Confidentiality) and 7.1 (Data Protection) shall be uncapped."*

A model that summarises the document by reading only the body will state
the cap is 12 months. The correct answer is "12 months, except for
breaches of Sections 4.2 and 7.1, which are uncapped." Missing the
footnote is the single most common failure mode for legal/contract AI
agents.

We procedurally fabricate this so the *exact* set of carve-outs is in
the answer key.
"""
from __future__ import annotations

import random

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C


_CONTRACT_TYPES = [
    "Master Services Agreement",
    "Software License Agreement",
    "Data Processing Addendum",
    "Subscription Order Form",
    "Statement of Work #4",
]

_BODY_POSITIONS = [
    # (label, body_text_template, footnote_template, expected_answer_template)
    (
        "liability_cap",
        "The aggregate liability of either party for any claims arising out of or relating to "
        "this Agreement shall not exceed an amount equal to {months} months of fees paid by Customer "
        "during the twelve (12) month period immediately preceding the event giving rise to such liability.",
        "Notwithstanding Section {section_num}, liability arising from "
        "Sections {carveout_sections} shall be uncapped.",
        "Liability is capped at {months} months of fees paid, EXCEPT that liability arising from "
        "Sections {carveout_sections} is uncapped.",
        "Liability is capped at {months} months of fees paid.",  # the wrong/forbidden answer
    ),
    (
        "termination_notice",
        "Either party may terminate this Agreement for convenience upon "
        "{notice_days} days written notice to the other party.",
        "However, termination for convenience is not permitted during the "
        "initial twelve (12) month term.",
        "Either party may terminate for convenience on {notice_days} days notice, "
        "BUT NOT during the initial 12-month term.",
        "Either party may terminate for convenience on {notice_days} days notice.",
    ),
    (
        "data_residency",
        "Customer Data shall be stored and processed in the {primary_region} region.",
        "Provided that, with Customer's written consent, Customer Data may also "
        "be processed in {fallback_region} for purposes of disaster recovery.",
        "Customer Data is stored in {primary_region}, with disaster-recovery "
        "processing permitted in {fallback_region} ONLY with written consent.",
        "Customer Data is stored in {primary_region}.",
    ),
]


def _random_sections(rng: random.Random) -> tuple[str, str]:
    """Return ``(section_num, carveout_sections)`` for the carve-out clause."""
    sec = f"{rng.randint(8, 14)}.{rng.randint(1, 5)}"
    carve = ", ".join(
        sorted(
            {
                f"{rng.randint(2, 7)}.{rng.randint(1, 4)}"
                for _ in range(rng.randint(2, 3))
            }
        )
    )
    return sec, carve


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)
    contract = rng.choice(_CONTRACT_TYPES)
    label, body_tpl, footnote_tpl, expected_tpl, wrong_tpl = rng.choice(_BODY_POSITIONS)

    # Bind the per-template parameters.
    # expected_tokens are the substrings any acceptable prose answer must
    # contain — facts, not phrasing. The scorer requires ALL tokens.
    if label == "liability_cap":
        months = rng.choice([3, 6, 12, 24])
        section_num, carveout_sections = _random_sections(rng)
        ctx = {"months": months, "section_num": section_num, "carveout_sections": carveout_sections}
        question = (
            f"Read the attached {contract}. What is the LIABILITY CAP "
            "and what carve-outs (if any) apply? Be precise about which Sections are uncapped."
        )
        # Acceptable: any prose that includes (1) the cap value, (2) the
        # carve-out section refs, (3) the word "uncapped" or equivalent.
        expected_tokens = [
            f"{months} month",
            "uncapped",
            *carveout_sections.split(", "),
        ]
    elif label == "termination_notice":
        notice_days = rng.choice([30, 60, 90])
        ctx = {"notice_days": notice_days}
        question = (
            f"Read the attached {contract}. Under what conditions can either party "
            "terminate this Agreement for convenience? Be specific about any restrictions."
        )
        expected_tokens = [
            f"{notice_days} day",
            "12 month",  # the initial-term restriction
        ]
    else:  # data_residency
        primary_region = rng.choice(["us-east-1", "eu-west-1", "ap-southeast-2"])
        fallback_region = rng.choice(["us-west-2", "eu-central-1", "ap-northeast-1"])
        while fallback_region == primary_region:
            fallback_region = rng.choice(["us-west-2", "eu-central-1", "ap-northeast-1"])
        ctx = {"primary_region": primary_region, "fallback_region": fallback_region}
        question = (
            f"Read the attached {contract}. Where is Customer Data stored, "
            "and under what conditions (if any) may it be processed elsewhere?"
        )
        expected_tokens = [
            primary_region,
            fallback_region,
            "consent",
        ]

    body_text = body_tpl.format(**ctx)
    footnote_text = footnote_tpl.format(**ctx)
    expected_answer = expected_tpl.format(**ctx)
    wrong_answer = wrong_tpl.format(**ctx)

    section_index = rng.randint(8, 14)
    section_label = f"{section_index}.{rng.randint(1, 5)}"

    case_id = f"footnote_override-{seed:04d}"

    def draw(c: canvas.Canvas) -> None:
        # Heading
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, 720, contract.upper())
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(72, 700, f"Effective Date: 2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}")

        # Intro paragraph (filler so the doc looks normal)
        intro = (
            "This Agreement is entered into between the Customer and Vendor (each a "
            '"Party" and collectively the "Parties") and governs the Parties\' '
            "respective rights and obligations with respect to the Services described in the Order Form. "
            "Capitalised terms used but not defined herein have the meanings given in the Order Form."
        )
        y = C.draw_paragraph(c, intro, 72, 670, font=C.FontSpec(size=10))

        # The clause of interest (body)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(72, y - 10, f"{section_label}  Limitation.")
        y = C.draw_paragraph(
            c,
            body_text + f"¹",  # superscript 1 — the footnote marker
            72, y - 30,
            font=C.FontSpec(size=11),
        )

        # More filler so the footnote isn't suspiciously isolated
        filler = (
            "Each Party shall comply with all applicable laws and regulations in connection with "
            "its performance under this Agreement and shall promptly notify the other Party of any "
            "material non-compliance of which it becomes aware. The provisions of this Section shall "
            "survive termination of this Agreement."
        )
        y = C.draw_paragraph(c, filler, 72, y - 10, font=C.FontSpec(size=10))

        # The footnote (6pt — the trap)
        # We deliberately place it near the bottom of page 1 to mimic
        # real legal-doc layout where footnotes get visually compressed.
        c.setFont("Helvetica", 6)
        c.drawString(72, 100, f"¹ {footnote_text}")

        # Page number
        c.setFont("Helvetica", 9)
        c.drawCentredString(C.PAGE_WIDTH / 2, 60, "Page 1 of 1")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="footnote_override",
        seed=seed,
        question=question,
        expected_answer=expected_answer,
        expected_tokens=expected_tokens,
        forbidden_answers=[wrong_answer],
        metadata={
            "contract_type": contract,
            "clause_label": label,
            "section_label": section_label,
            "params": ctx,
            "footnote_text": footnote_text,
            "expected_failure_mode": (
                "Model reads the body clause and ignores the 6pt footnote, missing the "
                "material carve-out / exception."
            ),
        },
    )
    return pdf_bytes, case
