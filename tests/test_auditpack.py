"""Tests for the audit-pack builder.

The audit pack is the artifact a procurement team attaches to a
diligence appendix. The tests below verify the contract a procurement
team will check:

- the ZIP opens
- every file the manifest claims is present in the ZIP
- every SHA-256 in the manifest matches the actual file content
- the manifest names the exact reproduction command
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from pdfhell.auditpack import build_audit_pack
from pdfhell.cli import main as cli_main
from pdfhell.case import HellCase
from pdfhell.scorer import score_case, summarise


def _build_run_with_real_pdfs(tmp_path: Path):
    """Use the actual pdfhell build pipeline so the audit pack has real PDFs."""
    cases_dir = tmp_path / "cases"
    cli_main(["build", "--suite", "smoke", "--out", str(cases_dir)])

    # Build a fake SuiteReport that says every case passed (no model call).
    case_jsons = sorted(cases_dir.glob("*.json"))
    scores = []
    for jp in case_jsons:
        case = HellCase.load_json(jp)
        # Pretend the model returned the expected answer verbatim.
        scores.append(score_case(case, case.expected_answer))
    return cases_dir, summarise("anthropic:claude-haiku-4-5", "smoke", scores)


def test_audit_pack_round_trips(tmp_path):
    cases_dir, report = _build_run_with_real_pdfs(tmp_path)
    out_zip = tmp_path / "audit.zip"
    build_audit_pack(report, cases_dir, out_zip)

    assert out_zip.is_file()
    with zipfile.ZipFile(out_zip, "r") as zf:
        names = set(zf.namelist())
        # Top-level files
        assert "manifest.json" in names
        assert "README.txt" in names
        assert "run.json" in names
        assert "run.xml" in names
        # Per-case PDFs + JSON for each of the 3 smoke cases.
        case_pdfs = [n for n in names if n.startswith("cases/") and n.endswith(".pdf")]
        case_jsons = [n for n in names if n.startswith("cases/") and n.endswith(".json")]
        assert len(case_pdfs) == 3
        assert len(case_jsons) == 3

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        # Every file in the manifest must exist in the ZIP and hash correctly.
        for entry in manifest["files"]:
            name = entry["path"]
            assert name in names, f"manifest references missing file: {name}"
            actual = hashlib.sha256(zf.read(name)).hexdigest()
            assert actual == entry["sha256"], f"hash mismatch for {name}"

        # Manifest carries the exact reproduction command.
        assert "uvx pdfhell run" in manifest["reproduction"]["command"]
        assert manifest["model"] == "anthropic:claude-haiku-4-5"
        assert manifest["suite"] == "smoke"
        assert manifest["n"] == 3
        assert manifest["passed"] == 3


def test_audit_pack_case_files_stable_across_runs(tmp_path):
    """Per-case PDFs and JSON answer keys MUST be byte-identical across
    builds — that's the reproducibility guarantee customers care about
    ("the same seed produces the same PDF"). README and run.xml embed a
    timestamp so they intentionally differ between builds; everything
    else should be stable.
    """
    cases_dir, report = _build_run_with_real_pdfs(tmp_path)
    a = tmp_path / "a.zip"
    b = tmp_path / "b.zip"
    build_audit_pack(report, cases_dir, a)
    build_audit_pack(report, cases_dir, b)
    with zipfile.ZipFile(a, "r") as za, zipfile.ZipFile(b, "r") as zb:
        ma = json.loads(za.read("manifest.json").decode("utf-8"))
        mb = json.loads(zb.read("manifest.json").decode("utf-8"))
        a_files = {f["path"]: f["sha256"] for f in ma["files"]}
        b_files = {f["path"]: f["sha256"] for f in mb["files"]}
        # Per-case files (PDFs + answer keys) and run.json (which has no
        # timestamp) must be byte-identical. README + run.xml may differ.
        stable_paths = {p for p in a_files if p.startswith("cases/") or p == "run.json"}
        assert stable_paths, "no stable paths to compare?"
        for path in stable_paths:
            assert a_files[path] == b_files[path], f"case file drift: {path}"
