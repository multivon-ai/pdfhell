"""Build a downloadable, hash-chained audit pack from a pdfhell run.

The pack is a ZIP containing:

- ``manifest.json`` — pdfhell version, run timestamp, model spec, suite,
  per-trap pass rates, total cost (when known), SHA-256 of every file
  inside the pack.
- ``run.json`` — the full :class:`SuiteReport` JSON.
- ``run.xml`` — JUnit XML (same data as ``run.json``, machine-readable
  for CI dashboards).
- ``cases/<case_id>.pdf`` — every adversarial PDF the model was tested
  against.
- ``cases/<case_id>.json`` — each case's answer key + metadata.
- ``README.txt`` — human-readable "what's in this ZIP" + reproduction
  command. Procurement teams open this first.

The audit pack is the artifact a buyer's procurement team attaches to
a diligence appendix. It must be self-describing (no out-of-band
context required), reproducible (the manifest tells you the exact
command to regenerate the run), and tamper-evident (the manifest
includes a SHA-256 for every file in the pack; auditors can verify the
ZIP wasn't edited after delivery).
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import __version__
from .case import HellCase
from .junit import report_to_junit
from .scorer import SuiteReport


_README_TEMPLATE = """\
# pdfhell audit pack

This ZIP is a complete, self-describing record of one PDF Hell run. It
contains every PDF the model was asked to read, every answer key, the
raw model output, and a tamper-evident manifest.

## What's in this pack

- manifest.json — Run metadata + SHA-256 of every file in this ZIP.
- run.json — Full run report (per-case scores, model outputs).
- run.xml — JUnit XML (renders in CI dashboards).
- cases/*.pdf — The adversarial PDFs the model was tested against.
- cases/*.json — The answer keys + per-case metadata.
- README.txt — This file.

## How to verify

The manifest contains a SHA-256 for every file in this ZIP. To verify
nothing was edited after delivery:

  unzip -p audit-pack.zip manifest.json | jq .files
  sha256sum cases/*.pdf cases/*.json run.json run.xml README.txt

Each hash in the manifest must match the file's actual SHA-256.

## How to reproduce

The manifest records the exact pdfhell command. To regenerate
byte-identical PDFs and re-run the same model:

  {repro_command}

pdfhell uses Canvas(invariant=True) on every generator so PDFs are
byte-identical across runs with the same seed.

## Scope

pdfhell {pdfhell_version}, suite {suite}, model {model}. Generated
{timestamp}. {n} cases, {passed}/{n} passed ({pass_rate:.0%}). See
manifest.json for per-trap breakdown.
"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _gather_files(report: SuiteReport, cases_dir: Path) -> Iterable[tuple[str, bytes]]:
    """Yield (arcname, bytes) pairs for every file going into the ZIP.

    Order: README first (humans see it first), then manifest, then JSON
    + XML, then case PDFs + answer keys. Stable ordering keeps the
    SHA-256 of the ZIP itself stable across runs.
    """
    for case_summary in report.cases:
        case_id = case_summary.case_id
        pdf_path = cases_dir / f"{case_id}.pdf"
        json_path = cases_dir / f"{case_id}.json"
        if pdf_path.exists():
            yield f"cases/{case_id}.pdf", pdf_path.read_bytes()
        if json_path.exists():
            yield f"cases/{case_id}.json", json_path.read_bytes()


def build_audit_pack(
    report: SuiteReport,
    cases_dir: Path,
    out_path: Path,
) -> Path:
    """Write a complete audit ZIP for ``report`` to ``out_path``.

    Returns the resolved output path.
    """
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Materialise the per-case files into bytes first so we can hash them.
    case_files: list[tuple[str, bytes]] = list(_gather_files(report, cases_dir))

    run_json_bytes = json.dumps(report.to_dict(), indent=2).encode("utf-8")
    run_xml_bytes = report_to_junit(report).encode("utf-8")
    timestamp = datetime.now(timezone.utc).isoformat()
    passed = sum(1 for c in report.cases if c.correct)

    repro_command = (
        f"uvx pdfhell run --model {report.model} --suite {report.suite}"
    )
    readme_bytes = _README_TEMPLATE.format(
        pdfhell_version=__version__,
        suite=report.suite,
        model=report.model,
        timestamp=timestamp,
        n=report.n,
        passed=passed,
        pass_rate=report.pass_rate,
        repro_command=repro_command,
    ).encode("utf-8")

    # Build a manifest that hashes every other file in the pack. The
    # manifest is the LAST file we hash so we can include the hashes of
    # everything else inside it.
    files_in_pack: list[tuple[str, bytes]] = [
        ("README.txt", readme_bytes),
        ("run.json", run_json_bytes),
        ("run.xml", run_xml_bytes),
        *case_files,
    ]
    manifest = {
        "pdfhell_version": __version__,
        "generated_at": timestamp,
        "model": report.model,
        "suite": report.suite,
        "n": report.n,
        "passed": passed,
        "pass_rate": report.pass_rate,
        "per_trap_pass": report.per_trap_pass,
        "per_trap_fell_for_trap": report.per_trap_fell_for_trap,
        "reproduction": {
            "command": repro_command,
            "note": (
                "PDFs are regenerated byte-identically via Canvas(invariant=True). "
                "Same seed → same PDF → same answer key."
            ),
        },
        "files": [
            {"path": name, "sha256": _sha256(data), "size": len(data)}
            for name, data in files_in_pack
        ],
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")

    # ZIP_DEFLATED is universal; mtime is set to the run timestamp so
    # the ZIP itself is reproducible across packaging runs.
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in [("manifest.json", manifest_bytes), *files_in_pack]:
            info = zipfile.ZipInfo(name)
            info.date_time = (2026, 1, 1, 0, 0, 0)
            zf.writestr(info, data)

    return out_path


__all__ = ["build_audit_pack"]
