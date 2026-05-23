"""Unit tests for pdfhell.research.researcher.parse_proposal (no API calls)."""
from __future__ import annotations

import json

from pdfhell.research.researcher import parse_proposal, build_prompt
from pathlib import Path


def _valid_payload(trap: str = "unicode_confusable") -> dict:
    return {
        "action": "create_generator",
        "trap_family": trap,
        "target_path": f"pdfhell/generators/{trap}.py",
        "code": (
            "from pdfhell.case import HellCase\n"
            "def generate(seed):\n"
            "    return b'%PDF', HellCase(id='x', trap_family='x', seed=seed, question='q', expected_answer='a')\n"
        ),
        "rationale": "Targets unicode lookalike chars in label strings",
    }


def test_parse_clean_json():
    p = parse_proposal(json.dumps(_valid_payload()), "opus")
    assert p is not None
    assert p.trap_family == "unicode_confusable"
    assert p.action == "create_generator"
    assert p.researcher_model == "opus"


def test_parse_fenced_json():
    raw = "Here you go:\n```json\n" + json.dumps(_valid_payload()) + "\n```\n"
    p = parse_proposal(raw, "gpt-5")
    assert p is not None
    assert p.trap_family == "unicode_confusable"


def test_parse_prose_prefix_then_json():
    """Some models include a sentence before the JSON. We extract on first/last brace."""
    raw = "Sure. Here is my proposal:\n" + json.dumps(_valid_payload()) + "\nLet me know if you want changes."
    p = parse_proposal(raw, "gemini")
    assert p is not None


def test_parse_garbage_returns_none():
    assert parse_proposal("hello world", "x") is None
    assert parse_proposal("", "x") is None
    assert parse_proposal("```python\n# not json\n```", "x") is None


def test_parse_rejects_missing_fields():
    obj = _valid_payload()
    del obj["rationale"]
    assert parse_proposal(json.dumps(obj), "x") is None


def test_parse_rejects_bad_action():
    obj = _valid_payload()
    obj["action"] = "delete_generator"  # not in whitelist
    assert parse_proposal(json.dumps(obj), "x") is None


def test_parse_rejects_invalid_trap_family_name():
    """trap_family must be snake_case, 3-40 chars."""
    for bad in ("X", "Weird-Name!", "0starts_with_digit", "x", "x" * 50):
        obj = _valid_payload(trap=bad)
        assert parse_proposal(json.dumps(obj), "x") is None, f"accepted bad name: {bad!r}"


def test_parse_normalises_target_path():
    obj = _valid_payload()
    obj["target_path"] = "pdfhell/wrong/place.py"  # wrong location
    p = parse_proposal(json.dumps(obj), "x")
    assert p is not None
    assert p.target_path == f"pdfhell/generators/{obj['trap_family']}.py"


def test_parse_truncates_rationale_to_500():
    obj = _valid_payload()
    obj["rationale"] = "x" * 2000
    p = parse_proposal(json.dumps(obj), "x")
    assert p is not None
    assert len(p.rationale) <= 500


def test_parse_rejects_code_without_generate():
    obj = _valid_payload()
    obj["code"] = "print('hello')\n"  # no def generate
    assert parse_proposal(json.dumps(obj), "x") is None


# ─── build_prompt ──────────────────────────────────────────────────────


def test_build_prompt_handles_missing_files(tmp_path):
    """Prompt should not crash if the support files don't exist."""
    sys_p, user_p = build_prompt(
        program_md_path=tmp_path / "nope.md",
        common_py_path=tmp_path / "nope.py",
        reference_py_path=tmp_path / "nope.py",
        results_tsv_path=tmp_path / "nope.tsv",
    )
    assert sys_p
    assert user_p


def test_build_prompt_includes_tried_names(tmp_path):
    _, user_p = build_prompt(
        program_md_path=tmp_path / "p.md",
        common_py_path=tmp_path / "c.py",
        reference_py_path=tmp_path / "r.py",
        results_tsv_path=tmp_path / "r.tsv",
        tried_names=["alpha_trap", "beta_trap"],
    )
    assert "alpha_trap" in user_p
    assert "beta_trap" in user_p
    assert "DO NOT RE-USE" in user_p


def test_build_prompt_keep_dir_optional(tmp_path):
    """No keep_dir → 'no prior keepers' placeholder."""
    _, user_p = build_prompt(
        program_md_path=tmp_path / "p.md",
        common_py_path=tmp_path / "c.py",
        reference_py_path=tmp_path / "r.py",
        results_tsv_path=tmp_path / "r.tsv",
        keep_dir=None,
    )
    assert "no prior keepers" in user_p.lower()
