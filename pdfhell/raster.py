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

import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

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

    Cache identity includes PDF bytes, DPI and renderer version. Replacing a
    PDF at the same path cannot reuse the old pixels. Existing files from the
    old path-only cache are ignored. Writes are atomic for concurrent readers.
    """
    pypdfium2 = _pdfium()
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise ValueError("dpi must be a positive integer")
    pdf_path = Path(pdf_path)
    target = Path(out_dir) if out_dir is not None else pdf_path.parent
    target.mkdir(parents=True, exist_ok=True)

    source = pdf_path.read_bytes()
    renderer = str(getattr(pypdfium2, "PYPDFIUM_INFO", "unknown")) + ":" + pdfium_build()
    identity = hashlib.sha256(source + b"\0" + renderer.encode()).hexdigest()
    doc = pypdfium2.PdfDocument(source)
    try:
        paths: list[Path] = []
        for i in range(len(doc)):
            png = target / f"{pdf_path.stem}.{identity}.dpi{dpi}.p{i + 1}.png"
            if not png.exists():
                page = doc[i]
                try:
                    bitmap = page.render(scale=dpi / 72)
                    try:
                        with NamedTemporaryFile(dir=target, suffix=".png", delete=False) as tmp:
                            temporary = Path(tmp.name)
                        try:
                            bitmap.to_pil().save(temporary)
                            os.replace(temporary, png)
                        finally:
                            temporary.unlink(missing_ok=True)
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            paths.append(png)
        return paths
    finally:
        doc.close()
