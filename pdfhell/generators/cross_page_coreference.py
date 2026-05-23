"""Trap family: cross-page coreference.

A ~20-page Master Services Agreement defines several capitalised terms
on page 1 ("Term Alpha" = N days, "Term Beta" = M days, "Term Gamma" =
K days), then on page 20 uses Term Alpha + Term Beta in a compound
condition: e.g., "the procedure described in Section 12.4 shall
complete within Term Alpha plus Term Beta."

The right answer is N + M days. The wrong answers are:
  - K days (model anchors on Term Gamma — the most-recently-mentioned
    capitalised term on page 19-20, the "anchoring on what's local" bias)
  - N days (model resolves only the first term it sees)
  - M days (model resolves only the second term)
  - The literal string "Term Alpha + Term Beta" (model declines to do
    the arithmetic)

Vision models with 100K+ context windows technically have the relevant
content in their context. But precision drops on long documents,
especially when vision context is heavier than text. Cross-page
definition tracing breaks around 15-20 pages even for frontier models.

Real-world analogue: this is what real legal agents and contract-review
agents face every day. The cap-x-versus-carve-out logic in an MSA is
exactly this pattern, just with more pages and more capitalised terms.
A 50% failure rate on this trap means contract-review AI is dangerous
to deploy without human review.

Why ~20 pages and not 5 or 200: at 5 pages every model with a context
window can do this. At 200 pages every model has truncation effects
that confound the trap. 20 pages is the sweet spot — well within context
windows for every frontier model, well past the point where attention
precision starts decaying.
"""
from __future__ import annotations

import random

from reportlab.pdfgen import canvas

from ..case import HellCase
from . import _common as C


# Plausible MSA filler. Each item is a short paragraph that reads as
# real legal boilerplate. We sample with repetition from this pool to
# fill the middle pages — the precise wording doesn't matter, only that
# it's there and credible.
_FILLER_PARAGRAPHS = [
    "Each party represents and warrants to the other that it has full corporate "
    "power and authority to enter into this Agreement, that the execution and "
    "delivery of this Agreement have been duly authorized by all necessary "
    "corporate action, and that this Agreement constitutes a legal, valid, and "
    "binding obligation enforceable in accordance with its terms.",
    "Customer agrees to comply with all applicable laws, regulations, and "
    "ordinances in its use of the Services, including but not limited to those "
    "relating to data protection, export controls, and anti-bribery. Customer "
    "shall indemnify Provider against any losses arising from Customer's failure "
    "to comply with this Section.",
    "Provider shall use commercially reasonable efforts to provide the Services "
    "in accordance with the Service Level Agreement attached as Schedule 2. If "
    "Provider fails to meet the Service Levels for three (3) consecutive months, "
    "Customer's sole and exclusive remedy shall be the service credit specified "
    "in Schedule 2.",
    "Each party shall maintain the confidentiality of the other party's "
    "Confidential Information and shall use such Confidential Information solely "
    "for the purposes of this Agreement. The obligations in this Section shall "
    "survive termination of this Agreement for a period of five (5) years.",
    "This Agreement shall be governed by and construed in accordance with the "
    "laws of the State of Delaware, without regard to its conflict of laws "
    "provisions. Any dispute arising out of or relating to this Agreement shall "
    "be submitted to binding arbitration in accordance with the Commercial "
    "Arbitration Rules of the American Arbitration Association.",
    "Neither party shall be liable for any failure or delay in performance under "
    "this Agreement to the extent such failure or delay is caused by a Force "
    "Majeure Event. The party affected by the Force Majeure Event shall give "
    "prompt written notice to the other party and shall use commercially "
    "reasonable efforts to mitigate the impact.",
    "Provider's Services may be subject to third-party terms and conditions, "
    "including open-source software licenses, which are incorporated by reference. "
    "Customer's use of any third-party services accessed through the Services "
    "shall be governed by the applicable third-party terms.",
    "Customer grants Provider a non-exclusive, royalty-free license to use "
    "Customer Data solely to the extent necessary to provide the Services. "
    "Provider shall not sell, license, or otherwise commercialize Customer Data, "
    "and shall delete Customer Data within thirty (30) days following termination.",
    "Either party may assign this Agreement to a successor in connection with a "
    "merger, acquisition, or sale of substantially all of its assets, provided "
    "that the assignee assumes all obligations under this Agreement. Any other "
    "assignment requires the prior written consent of the other party, not to be "
    "unreasonably withheld.",
    "All notices required or permitted under this Agreement shall be in writing "
    "and shall be delivered by hand, by overnight courier, or by certified mail, "
    "return receipt requested, to the addresses specified in the signature block "
    "or such other addresses as the parties may designate.",
]

# Section headings to give the filler structure.
_SECTION_HEADINGS = [
    "Representations and Warranties", "Customer Obligations", "Service Levels",
    "Confidentiality", "Governing Law and Dispute Resolution", "Force Majeure",
    "Third-Party Components", "Customer Data and Privacy", "Assignment",
    "Notices", "Order of Precedence", "Entire Agreement",
    "Severability", "Counterparts", "Headings",
    "Waiver of Jury Trial", "Interpretation",
    "Limitation of Remedies", "Insurance Coverage",
]


def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)

    # ── Define three terms on page 1. The trap uses Alpha + Beta.
    # Gamma is the decoy — it'll appear on the same page as the
    # compound reference, just as a separate clause, so models that
    # anchor on local mentions get it wrong.
    term_alpha_days = rng.randint(10, 45)
    term_beta_days = rng.randint(5, 30)
    term_gamma_days = rng.randint(60, 120)  # different magnitude so the
                                            # wrong-answer is visibly wrong
    final_deadline = term_alpha_days + term_beta_days

    # Section numbers for the references.
    definitions_section = "1.4"
    compound_section = "12.4"

    case_id = f"cross_page_coreference-{seed:04d}"
    # Naturalistic question — does NOT point at where the definitions live.
    # A lawyer reviewing the agreement asks "what is the deadline for the
    # post-cutover validation procedure" — they don't tell the reader to
    # look at Section 1.4 because they don't know that's where it is. The
    # trap bites when the model resolves the reference using only the local
    # context on page 20 (where Term Gamma is mentioned) instead of tracing
    # back to the definitions on page 1.
    question = (
        "You are reviewing the attached Master Services Agreement. "
        "What is the deadline for the post-cutover validation procedure, "
        "in calendar days? Respond with just a number and the word 'days' "
        "(e.g. '42 days')."
    )

    expected_answer = f"{final_deadline} days"
    # Forbidden answers must be SUBSTRINGS that only appear if the model
    # gave a *wrong* answer — never a substring that a correct-but-verbose
    # response might quote back. Earlier versions of this generator also
    # listed "Term Alpha plus Term Beta" as forbidden, intending to catch
    # the "model declined to compute" failure mode, but that false-
    # flagged any model that correctly answered "59 days" while quoting
    # the source clause back. Removed.
    forbidden_answers = [
        # Anchoring on Term Gamma — the most recently-mentioned term on page 20
        f"{term_gamma_days} days",
        # Using only one of the two referenced terms
        f"{term_alpha_days} days",
        f"{term_beta_days} days",
    ]

    # ── Draw the document ─────────────────────────────────────────────
    def draw(c: canvas.Canvas) -> None:
        # ═══════════ PAGE 1 — Title + Defined Terms ══════════════════
        c.setFont("Helvetica-Bold", 18)
        c.drawString(72, 720, "MASTER SERVICES AGREEMENT")

        c.setFont("Helvetica", 10)
        C.draw_paragraph(
            c,
            "This Master Services Agreement (the \"Agreement\") is entered "
            "into as of the Effective Date by and between the parties set "
            "forth in the signature block at the end of this Agreement.",
            72, 690, font=C.FontSpec(size=10),
        )

        c.setFont("Helvetica-Bold", 12)
        c.drawString(72, 640, "1. Definitions")
        c.setFont("Helvetica", 10)
        C.draw_paragraph(
            c,
            "Capitalised terms used in this Agreement have the meanings "
            "set out in this Section 1, or as otherwise defined in the body "
            "of the Agreement.",
            72, 620, font=C.FontSpec(size=10),
        )

        # Section 1.1, 1.2, 1.3 — filler definitions to make the
        # definitions section feel realistic.
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 570, "1.1 \"Affiliate\"")
        c.setFont("Helvetica", 10)
        c.drawString(72, 555, "means an entity controlled by, controlling, or under common control with a party.")

        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 530, "1.2 \"Confidential Information\"")
        c.setFont("Helvetica", 10)
        c.drawString(72, 515, "means non-public business or technical information designated as confidential.")

        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 490, "1.3 \"Services\"")
        c.setFont("Helvetica", 10)
        c.drawString(72, 475, "means the products and services to be provided by Provider as described in the SOW.")

        # ── THE BINDING DEFINITIONS — Section 1.4 ─────────────────────
        c.setFont("Helvetica-Bold", 11)
        c.drawString(72, 440, f"{definitions_section} Service Calendar Terms")
        c.setFont("Helvetica", 10)
        C.draw_paragraph(
            c,
            "For purposes of computing service-completion deadlines, the "
            "following terms have the meanings set forth below. All days "
            "are calendar days unless otherwise specified.",
            72, 420, font=C.FontSpec(size=10),
        )

        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 380, "\"Term Alpha\"")
        c.setFont("Helvetica", 10)
        c.drawString(180, 380, f"means {term_alpha_days} calendar days.")

        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 360, "\"Term Beta\"")
        c.setFont("Helvetica", 10)
        c.drawString(180, 360, f"means {term_beta_days} calendar days.")

        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 340, "\"Term Gamma\"")
        c.setFont("Helvetica", 10)
        c.drawString(180, 340, f"means {term_gamma_days} calendar days.")

        # Some prose under the definitions so they don't feel orphaned.
        C.draw_paragraph(
            c,
            "The terms defined in this Section 1.4 are referenced in "
            "Sections 7 (Service Levels), 12 (Implementation), and the "
            "schedules to this Agreement. Cross-references to these terms "
            "throughout the Agreement carry the meanings set forth above.",
            72, 300, font=C.FontSpec(size=10),
        )

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 1 of 20")
        c.showPage()

        # ═══════════ PAGES 2-19 — Plausible filler ═══════════════════
        # 18 filler pages. Each page has a section heading + 2-3 filler
        # paragraphs. We sample with repetition; the precise wording
        # doesn't matter — only that the document is genuinely long.
        for page_num in range(2, 20):
            # Vary the section heading per page so the document reads as
            # a real MSA, not 18 copies of the same content.
            heading = _SECTION_HEADINGS[(page_num - 2) % len(_SECTION_HEADINGS)]
            c.setFont("Helvetica-Bold", 12)
            c.drawString(72, 720, f"{page_num}. {heading}")

            # 3 filler paragraphs per page.
            y = 690
            for _ in range(3):
                para = _FILLER_PARAGRAPHS[rng.randrange(len(_FILLER_PARAGRAPHS))]
                y = C.draw_paragraph(c, para, 72, y, font=C.FontSpec(size=10))
                y -= 10
                if y < 200:
                    break

            c.setFont("Helvetica-Oblique", 8)
            c.drawString(72, 60, f"Page {page_num} of 20")
            c.showPage()

        # ═══════════ PAGE 20 — Compound reference (the trap) ═════════
        c.setFont("Helvetica-Bold", 12)
        c.drawString(72, 720, "12. Implementation Timelines")

        c.setFont("Helvetica", 10)
        C.draw_paragraph(
            c,
            "Implementation activities under this Agreement are subject to "
            "the timelines set forth in this Section 12. Capitalised terms "
            "used in this Section have the meanings given in Section 1.4.",
            72, 690, font=C.FontSpec(size=10),
        )

        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 640, "12.1 Onboarding")
        c.setFont("Helvetica", 10)
        c.drawString(72, 620,
                     "Provider shall complete onboarding within a reasonable period following the Effective Date.")

        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 590, "12.2 Migration")
        c.setFont("Helvetica", 10)
        c.drawString(72, 570,
                     "Customer Data migration shall be completed in accordance with the schedule attached to the SOW.")

        # ── THE DECOY — Section 12.3 references Term Gamma ───────────
        # Models that anchor on "most recent capitalised-term mention"
        # will fail (b) below.
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 540, "12.3 Cut-Over")
        c.setFont("Helvetica", 10)
        C.draw_paragraph(
            c,
            f"Final cut-over from any prior provider must be completed "
            f"within Term Gamma of the Migration completion date, after "
            f"which Provider's Services shall be the sole production "
            f"environment for the Customer's workloads.",
            72, 520, font=C.FontSpec(size=10),
        )

        # ── THE TRAP — Section 12.4 references Term Alpha + Term Beta ─
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 460, f"{compound_section} Post-Cutover Validation")
        c.setFont("Helvetica", 10)
        C.draw_paragraph(
            c,
            f"Following Cut-Over, Provider shall complete the post-cutover "
            f"validation procedure described in Schedule 3. The procedure "
            f"shall be deemed complete upon Customer's written acceptance, "
            f"which Customer shall not unreasonably withhold. The procedure "
            f"shall be completed within Term Alpha plus Term Beta from the "
            f"Cut-Over date. Failure to complete within this period shall "
            f"entitle Customer to the remedies set forth in Section 13.",
            72, 440, font=C.FontSpec(size=10),
        )

        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, 370, "12.5 Reporting")
        c.setFont("Helvetica", 10)
        c.drawString(72, 350,
                     "Provider shall report on validation status weekly to Customer's designated contact.")

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(72, 60, "Page 20 of 20")

    pdf_bytes = C.canvas_to_bytes(draw)

    case = HellCase(
        id=case_id,
        trap_family="cross_page_coreference",
        seed=seed,
        question=question,
        expected_answer=expected_answer,
        forbidden_answers=forbidden_answers,
        metadata={
            "definitions": {
                "Term Alpha": term_alpha_days,
                "Term Beta": term_beta_days,
                "Term Gamma": term_gamma_days,
            },
            "expected_sum": final_deadline,
            "page_count": 20,
            "definitions_page": 1,
            "compound_reference_page": 20,
            "decoy_term": "Term Gamma",
            "decoy_value": term_gamma_days,
            "expected_failure_mode": (
                "Model anchors on Term Gamma (mentioned in Section 12.3 immediately "
                "before the trap reference on page 20) instead of resolving Term Alpha "
                "and Term Beta from Section 1.4 on page 1; or resolves only one of the "
                "two terms; or declines to compute the sum. Precision-decay on "
                "long-context attention is the underlying mechanism."
            ),
        },
    )
    return pdf_bytes, case
