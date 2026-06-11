"""PDF → PNG rasterisation for the pixels-only modality (issue #1).

The default pdfhell run sends the PDF itself to the provider, which may
read the embedded text layer, render pixels, or both — provider-opaque.
``--pixels`` mode rasterises locally at a fixed DPI and sends only the
page images, so a pass/fail is attributable to vision alone.

Honesty notes baked into the design:
  - The PDF stays the byte-identical reproducible artifact. PNGs are a
    DERIVED input: pixel-level determinism across pypdfium2 versions is
    not claimed, which is why the pdfium build is recorded in the run
    JSON alongside the DPI.
  - DPI is part of the experimental setup (a 3.5pt footnote is ~7px tall
    at 150 DPI). Any published pixels-only number must carry its DPI.
"""
from __future__ import annotations

from pathlib import Path


DEFAULT_DPI = 150


def _pdfium():
    try:
        import pypdfium2
    except ImportError as exc:  # pragma: no cover - exercised via message test
        raise RuntimeError(
            "pixels mode needs pypdfium2 for local PDF rasterisation. "
            "Install with `pip install 'pdfhell[pixels]'` or "
            "`pip install pypdfium2 Pillow`."
        ) from exc
    return pypdfium2


def pdfium_build() -> str:
    """Identifier of the pdfium build in use — recorded in run JSON."""
    pypdfium2 = _pdfium()
    info = getattr(pypdfium2, "PDFIUM_INFO", None)
    build = getattr(info, "build", None) if info is not None else None
    return str(build) if build is not None else "unknown"


def rasterize_pdf(pdf_path: Path, *, dpi: int = DEFAULT_DPI,
                  out_dir: Path | None = None) -> list[Path]:
    """Render every page of ``pdf_path`` to PNG at ``dpi``.

    Output files land next to the PDF (or in ``out_dir``) as
    ``<stem>.dpi<dpi>.p<page>.png`` — the DPI is part of the filename so
    runs at different DPIs never reuse each other's cache. Existing
    outputs are reused without re-rendering.
    """
    pypdfium2 = _pdfium()
    pdf_path = Path(pdf_path)
    target = Path(out_dir) if out_dir is not None else pdf_path.parent
    target.mkdir(parents=True, exist_ok=True)

    doc = pypdfium2.PdfDocument(str(pdf_path))
    try:
        paths: list[Path] = []
        for i in range(len(doc)):
            png = target / f"{pdf_path.stem}.dpi{dpi}.p{i + 1}.png"
            if not png.exists():
                bitmap = doc[i].render(scale=dpi / 72)
                try:
                    bitmap.to_pil().save(png)
                finally:
                    bitmap.close()
            paths.append(png)
        return paths
    finally:
        doc.close()
