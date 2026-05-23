"""Unit tests for pdfhell.research.validate (no API calls).

The gates that hit external APIs (answerable, forbidden_clean) are
not exercised here — they need network. We test the local-only
gates: lint, parseable, deterministic, plus the _loose_eq matcher.
"""
from __future__ import annotations

import io

import pytest

from pdfhell.case import HellCase
from pdfhell.research.validate import (
    _loose_eq,
    gate_deterministic,
    gate_parseable,
    gate_lint_clean,
)


# ─── _loose_eq ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("a,b", [
    ("$18,400.00", "$18,400"),       # trailing .00
    ("$1,234.56", "1234.56"),        # bare number vs formatted
    ("USD 1234", "$1,234"),          # alt currency
    ("$1,234.56", "$1234.56"),       # commas
    ("$1234", "1234.00"),            # implicit integer
    ("1.5", "1.5"),                  # plain
    ("$1,234.5", "1234.50"),         # different decimal precision
])
def test_loose_eq_currency_variants_match(a, b):
    assert _loose_eq(a, b)


@pytest.mark.parametrize("a,b", [
    ("$1234", "$5678"),
    ("$1,234.56", "$1,234.57"),     # tiny but real diff
    ("hello", "world"),
    ("$1234", "$12340"),            # off by 10x
])
def test_loose_eq_different_amounts_dont_match(a, b):
    assert not _loose_eq(a, b)


def test_loose_eq_non_numeric_falls_back_to_alphanumeric():
    # No numbers → falls back to alphanumeric-strip comparison
    assert _loose_eq("hello-world", "helloworld")
    assert _loose_eq("FOO 123", "foo123")  # case-insensitive via lower?
    # The current impl is case-sensitive on the fallback path
    assert not _loose_eq("HELLO", "world")


# ─── gate_parseable ────────────────────────────────────────────────────


def _trivial_pdf_bytes() -> bytes:
    """A valid 1-page PDF generated via reportlab."""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "hello")
    c.save()
    return buf.getvalue()


def test_gate_parseable_accepts_valid_pdf():
    r = gate_parseable(_trivial_pdf_bytes())
    assert r.passed
    assert "1 pages" in r.reason


def test_gate_parseable_rejects_garbage():
    r = gate_parseable(b"definitely not a PDF")
    assert not r.passed
    # Both parsers must have been attempted
    assert "pypdf" in r.reason or "pdfplumber" in r.reason


def test_gate_parseable_rejects_empty():
    r = gate_parseable(b"")
    assert not r.passed


# ─── gate_deterministic ────────────────────────────────────────────────


def test_gate_deterministic_passes_for_stable_generator():
    """A generator that uses rng_for(seed) must produce identical bytes."""
    from reportlab.pdfgen import canvas
    from pdfhell.generators._common import canvas_to_bytes, rng_for

    def gen(seed):
        rng = rng_for(seed)
        x = rng.randint(50, 100)

        def draw(c: canvas.Canvas) -> None:
            c.drawString(x, 720, f"hello {x}")

        pdf = canvas_to_bytes(draw)
        case = HellCase(
            id=f"test-{seed:04d}", trap_family="test", seed=seed,
            question="q?", expected_answer="a",
        )
        return pdf, case

    r = gate_deterministic(gen, 42)
    assert r.passed, r.reason


def test_gate_deterministic_catches_drift():
    """A generator using global random will produce different bytes each call."""
    import random
    from reportlab.pdfgen import canvas
    from pdfhell.generators._common import canvas_to_bytes

    def gen(seed):
        # Wrong: uses global random, not rng_for(seed) → non-deterministic
        x = random.randint(50, 100)

        def draw(c: canvas.Canvas) -> None:
            c.drawString(x, 720, "hi")

        pdf = canvas_to_bytes(draw)
        case = HellCase(
            id="drift-x", trap_family="test", seed=seed,
            question="q?", expected_answer="a",
        )
        return pdf, case

    r = gate_deterministic(gen, 42)
    assert not r.passed
    assert "differ" in r.reason.lower() or "bytes" in r.reason.lower()


# ─── gate_lint_clean ───────────────────────────────────────────────────


def test_gate_lint_clean_on_valid_file(tmp_path):
    """A clean file should pass."""
    # Use an existing pdfhell generator — guaranteed clean
    from pathlib import Path
    target = Path(__file__).resolve().parents[1] / "pdfhell" / "generators" / "hidden_ocr_mismatch.py"
    assert target.exists()
    r = gate_lint_clean(target)
    assert r.passed, r.reason


def test_gate_lint_clean_on_missing_file(tmp_path):
    r = gate_lint_clean(tmp_path / "does_not_exist.py")
    assert not r.passed
    assert "not found" in r.reason.lower()


def test_gate_lint_clean_on_syntax_error(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:  # syntax error\n    pass\n")
    r = gate_lint_clean(bad)
    assert not r.passed
