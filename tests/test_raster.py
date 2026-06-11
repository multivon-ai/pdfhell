"""Pixels-only modality (--pixels): rasterisation + report annotation.

Pins the contracts from issue #1:
  - PNGs are derived inputs named with their DPI (no cross-DPI cache reuse)
  - the run JSON records modality / raster_dpi / pdfium_build
  - pdf and pixels runs land at different default paths (never clobber)
  - old run JSONs without the modality field still load as "pdf"
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pypdfium2")

from pdfhell.cli import main, _default_run_path
from pdfhell.raster import rasterize_pdf
from pdfhell.scorer import SuiteReport


def _make_case(tmp_path: Path) -> Path:
    out_cases = tmp_path / "cases"
    main(["make", "--trap", "hidden_ocr_mismatch", "--seed", "42",
          "--out", str(out_cases)])
    return out_cases


def test_rasterize_writes_dpi_tagged_pngs_and_caches(tmp_path):
    cases = _make_case(tmp_path)
    pdf = next(cases.glob("*.pdf"))

    pages = rasterize_pdf(pdf, dpi=150)
    assert pages and all(p.exists() for p in pages)
    assert all(".dpi150.p" in p.name for p in pages)

    # Different DPI → different files, never a silent cache hit.
    pages_300 = rasterize_pdf(pdf, dpi=300)
    assert {p.name for p in pages_300}.isdisjoint({p.name for p in pages})

    # Re-render reuses the existing file (mtime unchanged).
    before = pages[0].stat().st_mtime_ns
    rasterize_pdf(pdf, dpi=150)
    assert pages[0].stat().st_mtime_ns == before


def test_pixels_run_sends_pngs_and_annotates_report(tmp_path, monkeypatch):
    cases = _make_case(tmp_path)

    seen_sources: list[list[str]] = []

    def fake_vision(**kw):
        seen_sources.append(list(kw["sources"]))
        return "$18,900.25"

    from pdfhell import runner as runner_mod
    monkeypatch.setattr(runner_mod, "call_vision", fake_vision)

    out_run = tmp_path / "runs" / "px.json"
    code = main([
        "run", "--model", "anthropic:claude-haiku-4-5",
        "--cases-dir", str(cases), "--workers", "1", "--quiet",
        "--pixels", "--dpi", "150",
        "--out", str(out_run),
    ])
    assert code == 0
    # The model saw PNG pages, not the PDF.
    assert seen_sources and all(
        src.endswith(".png") for sources in seen_sources for src in sources
    )
    report = json.loads(out_run.read_text())
    assert report["modality"] == "pixels"
    assert report["raster_dpi"] == 150
    assert report["pdfium_build"]


def test_pdf_run_report_records_pdf_modality(tmp_path, monkeypatch):
    cases = _make_case(tmp_path)
    from pdfhell import runner as runner_mod
    monkeypatch.setattr(runner_mod, "call_vision", lambda **kw: "$18,900.25")

    out_run = tmp_path / "runs" / "pdf.json"
    code = main([
        "run", "--model", "anthropic:claude-haiku-4-5",
        "--cases-dir", str(cases), "--workers", "1", "--quiet",
        "--out", str(out_run),
    ])
    assert code == 0
    report = json.loads(out_run.read_text())
    assert report["modality"] == "pdf"
    assert report["raster_dpi"] is None


def test_default_run_paths_never_clobber_across_modalities():
    pdf_path = _default_run_path("anthropic:claude-haiku-4-5", "smoke")
    px_path = _default_run_path("anthropic:claude-haiku-4-5", "smoke",
                                modality="pixels")
    assert pdf_path != px_path
    assert "pixels" in px_path.name


def test_old_run_json_without_modality_loads_as_pdf():
    report = SuiteReport(
        model="m", suite="s", n=1, pass_rate=1.0,
        per_trap_pass={}, per_trap_fell_for_trap={}, refused_rate=0.0,
    )
    d = report.to_dict()
    assert d["modality"] == "pdf"
    # cmd_report reads raw.get("modality", "pdf") — emulate an old JSON.
    d.pop("modality"), d.pop("raster_dpi"), d.pop("pdfium_build")
    assert d.get("modality", "pdf") == "pdf"
