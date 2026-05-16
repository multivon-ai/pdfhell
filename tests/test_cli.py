"""CLI smoke tests.

These call the argparse-driven entry point with a temp output dir to
verify the user-facing surface stays sane. They don't hit any LLM
provider — the runner subcommand is tested separately with a mocked
``call_vision`` function.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from pdfhell.cli import build_parser, main


def test_list_traps_prints_all_families(capsys):
    code = main(["list-traps"])
    assert code == 0
    out = capsys.readouterr().out
    for trap in ("hidden_ocr_mismatch", "footnote_override", "split_table_across_pages"):
        assert trap in out


def test_make_writes_pdf_and_json(tmp_path):
    out = tmp_path / "cases"
    code = main([
        "make",
        "--trap", "hidden_ocr_mismatch",
        "--seed", "42",
        "--out", str(out),
    ])
    assert code == 0
    pdfs = list(out.glob("*.pdf"))
    jsons = list(out.glob("*.json"))
    assert len(pdfs) == 1
    assert len(jsons) == 1
    # The case JSON has the expected answer and matches the PDF id.
    raw = json.loads(jsons[0].read_text())
    assert raw["trap_family"] == "hidden_ocr_mismatch"
    assert raw["seed"] == 42
    assert raw["expected_answer"]
    assert pdfs[0].name == jsons[0].name.replace(".json", ".pdf")


def test_make_unknown_trap_exits_nonzero(tmp_path):
    """argparse with choices= raises SystemExit(2) before our handler
    runs. That's the right behaviour for a CLI — the user gets the
    available choices in the error message — we just need to assert
    the exit code is non-zero."""
    with pytest.raises(SystemExit) as exc:
        main([
            "make",
            "--trap", "not_a_real_trap",
            "--seed", "1",
            "--out", str(tmp_path),
        ])
    assert exc.value.code != 0


def test_build_mini_suite_writes_30_cases(tmp_path):
    out = tmp_path / "mini"
    code = main(["build", "--suite", "mini", "--out", str(out)])
    assert code == 0
    assert len(list(out.glob("*.pdf"))) == 30
    assert len(list(out.glob("*.json"))) == 30
    # 10 of each trap family.
    for trap in ("hidden_ocr_mismatch", "footnote_override", "split_table_across_pages"):
        assert len(list(out.glob(f"{trap}-*.pdf"))) == 10


def test_run_uses_mocked_vision(tmp_path, monkeypatch):
    """Smoke test: run --model X invokes call_vision and produces a JSON report.

    We monkeypatch ``call_vision`` so the test doesn't hit a real API.
    """
    # First materialise a single case to evaluate.
    out_cases = tmp_path / "cases"
    main([
        "make",
        "--trap", "hidden_ocr_mismatch",
        "--seed", "42",
        "--out", str(out_cases),
    ])

    # Patch the runner's call_vision to return the expected answer.
    from pdfhell import runner as runner_mod
    monkeypatch.setattr(runner_mod, "call_vision", lambda **kw: "$18,900.25")

    out_run = tmp_path / "runs" / "smoke.json"
    code = main([
        "run",
        "--model", "anthropic:claude-haiku-4-5",
        "--cases-dir", str(out_cases),
        "--workers", "1",
        "--quiet",
        "--out", str(out_run),
    ])
    assert code == 0
    assert out_run.is_file()
    report = json.loads(out_run.read_text())
    assert report["n"] == 1
    assert report["pass_rate"] == 1.0


def test_help_includes_all_subcommands():
    parser = build_parser()
    help_text = parser.format_help()
    for sub in ("list-traps", "make", "build", "run", "report"):
        assert sub in help_text
