"""Generator smoke tests.

These tests verify the contract every trap-family generator promises:

- ``generate(seed)`` returns ``(pdf_bytes, HellCase)``.
- The PDF starts with ``%PDF-`` (a valid PDF magic prefix).
- ``HellCase.expected_answer`` is a non-empty string.
- The case id is stable across reruns with the same seed.

They do NOT call any vision model — that's tested separately in
``test_cli.py`` against a mocked runner. The point of these is to keep
the procedural-ground-truth guarantee tight: re-seeding produces
byte-identical artifacts.
"""
from __future__ import annotations

import pytest

from pdfhell.case import HellCase
from pdfhell.generators import GENERATORS, TRAP_FAMILIES, generate_case


@pytest.mark.parametrize("trap", TRAP_FAMILIES)
def test_generator_returns_pdf_and_case(trap: str):
    pdf_bytes, case = generate_case(trap, seed=42)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:5] == b"%PDF-", "output is not a valid PDF"
    assert isinstance(case, HellCase)
    assert case.trap_family == trap
    assert case.seed == 42
    assert case.expected_answer.strip(), "expected_answer must not be empty"
    assert case.question.strip(), "question must not be empty"


@pytest.mark.parametrize("trap", TRAP_FAMILIES)
def test_generator_is_deterministic(trap: str):
    """Re-seeding must produce byte-identical PDFs and identical answer keys.

    This is the load-bearing guarantee for "code-based ground truth" —
    if the same seed produces different bytes, the published leaderboard
    is not reproducible.
    """
    a_bytes, a_case = generate_case(trap, seed=7)
    b_bytes, b_case = generate_case(trap, seed=7)
    assert a_bytes == b_bytes, "PDF bytes drifted between runs of the same seed"
    assert a_case.expected_answer == b_case.expected_answer
    assert a_case.question == b_case.question
    assert a_case.forbidden_answers == b_case.forbidden_answers


@pytest.mark.parametrize("trap", TRAP_FAMILIES)
def test_different_seeds_produce_different_cases(trap: str):
    """Two different seeds must produce different IDs (and almost
    certainly different bytes — vanishingly small chance of collision)."""
    _, a_case = generate_case(trap, seed=1)
    _, b_case = generate_case(trap, seed=2)
    assert a_case.id != b_case.id


def test_unknown_trap_raises_clearly():
    with pytest.raises(KeyError) as exc:
        generate_case("not_a_real_trap", seed=1)
    msg = str(exc.value)
    assert "unknown trap family" in msg
    # The error message lists available families so the user knows the fix.
    for trap in TRAP_FAMILIES:
        assert trap in msg


def test_hidden_ocr_mismatch_has_forbidden_answer():
    """The trap is specifically designed to elicit the hidden-OCR amount.
    The case's forbidden_answers must record it so the scorer can detect
    the named failure mode."""
    _, case = generate_case("hidden_ocr_mismatch", seed=1)
    assert case.forbidden_answers, "forbidden_answers must list the trap value"
    assert case.forbidden_answers[0] != case.expected_answer


def test_split_table_forbidden_is_an_adjacent_column():
    """The 'forbidden' answer for this trap is the value of an adjacent
    column in the same row — the classic column-confusion failure mode.
    """
    _, case = generate_case("split_table_across_pages", seed=1)
    assert case.forbidden_answers
    # Both expected and forbidden are dollar strings of similar shape.
    assert case.expected_answer.startswith("$")
    assert case.forbidden_answers[0].startswith("$")


@pytest.mark.parametrize("trap", TRAP_FAMILIES)
def test_no_substitution_glyphs_in_any_family(trap: str):
    """Every drawn string must be encodable in its font.

    An unencodable codepoint renders as a visible tofu box (and a
    substitute char in the text layer) — zero_width_space_split shipped
    exactly this for five releases before the pixels-only modality
    caught it (issue #8). Transform-based traps (mirror/upside-down)
    keep ordinary chars in the text layer, so this is safe for them.
    """
    import io
    from pypdf import PdfReader

    pdf_bytes, _case = generate_case(trap, 7001)
    text = "".join(
        page.extract_text() or ""
        for page in PdfReader(io.BytesIO(pdf_bytes)).pages
    )
    bad = sorted({ch for ch in text if ch in "■□�"})
    assert not bad, (
        f"{trap}: substitution glyph(s) {bad!r} in extracted text — "
        f"a drawn string contains characters the font cannot encode"
    )
