"""Shared utilities for trap-family generators.

Each helper here is a small, well-typed primitive that the per-trap
generators compose. The aim is that adding a new trap family means
writing one new file under ``pdfhell/generators/`` and registering it in
``__init__.py`` — without copy-pasting reportlab boilerplate.
"""
from __future__ import annotations

import io
import random
from dataclasses import dataclass
from typing import Iterable, Sequence

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas


# Letter portrait. We keep the page size constant across traps so visual
# scoring across the suite is comparable.
PAGE_WIDTH, PAGE_HEIGHT = LETTER


@dataclass(slots=True)
class FontSpec:
    """Font selection + size."""

    family: str = "Helvetica"
    size: float = 11.0
    bold: bool = False

    @property
    def name(self) -> str:
        return f"{self.family}-Bold" if self.bold else self.family


# A reproducible RNG that's seeded per-case. Generators must use this
# (not the global ``random``) so byte-identical PDFs come out of byte-
# identical seeds even when many generators run in the same process.
def rng_for(seed: int) -> random.Random:
    return random.Random(seed)


def draw_paragraph(
    c: "canvas.Canvas",
    text: str,
    x: float,
    y: float,
    *,
    width: float = PAGE_WIDTH - 144,
    font: FontSpec = FontSpec(),
    leading: float | None = None,
) -> float:
    """Draw wrapped text with simple word-wrap. Returns the next free y.

    We hand-roll wrapping rather than using Platypus flowables because
    every trap family wants pixel-precise control over where text lands
    (especially for tiny footnotes and split-table headers). Platypus
    would fight us. canvas.drawString gives us the control.
    """
    leading = leading or (font.size * 1.25)
    c.setFont(font.name, font.size)
    words = text.split()
    current: list[str] = []

    def line_width(parts: list[str]) -> float:
        return c.stringWidth(" ".join(parts), font.name, font.size)

    cursor_y = y
    for word in words:
        current.append(word)
        if line_width(current) > width:
            current.pop()
            c.drawString(x, cursor_y, " ".join(current))
            cursor_y -= leading
            current = [word]
    if current:
        c.drawString(x, cursor_y, " ".join(current))
        cursor_y -= leading
    return cursor_y


def draw_invisible_text(c: "canvas.Canvas", text: str, x: float, y: float, *, size: float = 11.0) -> None:
    """Place a string in the PDF text stream that is invisible to the eye.

    This is the core trick behind :mod:`hidden_ocr_mismatch`. PDFs can
    contain text rendered as invisible (render mode 3 — neither stroke
    nor fill). A human reader sees nothing. An OCR/text-extraction
    pipeline that reads the underlying text stream sees the invisible
    string. A vision-only model reads the page's pixels. A
    text-extraction pipeline reads the invisible layer. The two answers
    diverge.

    This is exactly how scanned-then-re-OCR'd PDFs go wrong in the wild
    — the OCR layer can drift from the rendered page. Procedurally
    constructing this means we *know* both answers and can score either
    correctly.
    """
    text_obj = c.beginText(x, y)
    text_obj.setFont("Helvetica", size)
    # Render mode 3 = neither stroke nor fill, so the glyphs are placed
    # in the text content stream but never rasterised. Visible text is
    # mode 0.
    text_obj.setTextRenderMode(3)
    text_obj.textOut(text)
    c.drawText(text_obj)


def draw_table(
    c: "canvas.Canvas",
    rows: Sequence[Sequence[str]],
    x: float,
    y: float,
    *,
    col_widths: Sequence[float] | None = None,
    row_height: float = 24,
    font: FontSpec = FontSpec(size=10),
    header_bold: bool = True,
) -> float:
    """Draw a borderless monospaced table. Returns the next free y.

    Each generator that needs tables uses this to avoid reportlab's
    Platypus tables (which paginate awkwardly when we explicitly *want*
    to split a row across a page boundary).
    """
    if not rows:
        return y
    if col_widths is None:
        col_count = max(len(r) for r in rows)
        col_widths = [(PAGE_WIDTH - 144) / col_count] * col_count
    for i, row in enumerate(rows):
        cur_x = x
        is_header = i == 0
        c.setFont(
            "Helvetica-Bold" if (is_header and header_bold) else font.name,
            font.size,
        )
        for cell, w in zip(row, col_widths):
            c.drawString(cur_x, y, cell)
            cur_x += w
        y -= row_height
    return y


def page_break(c: "canvas.Canvas") -> None:
    c.showPage()


def canvas_to_bytes(make: "Callable[[canvas.Canvas], None]") -> bytes:  # noqa: F821
    """Run a draw routine against a fresh canvas and return the bytes.

    Centralised so every generator does ``return canvas_to_bytes(draw)``
    rather than duplicating BytesIO + canvas wiring.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    make(c)
    c.save()
    return buf.getvalue()


def fmt_money(amount: int | float, currency: str = "$") -> str:
    """Render money in a stable format. Generators set the *expected
    answer* using this exact function so the answer string and the
    rendered PDF text agree to the byte."""
    return f"{currency}{amount:,.2f}"


def pick_from(rng: random.Random, choices: Iterable):
    """Convenience for picking one element from an iterable using rng.

    ``random.Random.choice`` requires a sequence; this lets generators
    pass generators/sets without converting upfront.
    """
    items = list(choices)
    return rng.choice(items)
