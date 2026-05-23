"""Unit tests for pdfhell.research.eval (no API calls)."""
from __future__ import annotations

from pdfhell.research.eval import PanelResult, novelty_score, write_results_row


def _mk(per_model: dict[str, float], trap: str = "x") -> PanelResult:
    r = PanelResult(trap_family=trap, n_cases=10, panel=tuple(per_model.keys()))
    r.per_model_pass = dict(per_model)
    return r


# ─── PanelResult metrics ────────────────────────────────────────────────


def test_spread_solvability_score():
    # Perfect spread, max passes 70%, novelty 1.0 → score = 1.0
    r = _mk({"a": 1.0, "b": 0.0, "c": 0.7})
    assert r.spread == 1.0
    assert r.solvable is True
    assert r.score(novelty=1.0) == 1.0


def test_score_zero_when_not_solvable():
    # Max passes only 60%, below 0.7 threshold → score 0
    r = _mk({"a": 0.6, "b": 0.0, "c": 0.5})
    assert r.solvable is False
    assert r.score(novelty=1.0) == 0.0


def test_score_scales_with_novelty():
    r = _mk({"a": 1.0, "b": 0.0})
    assert r.score(novelty=1.0) == 1.0
    assert r.score(novelty=0.5) == 0.5
    assert r.score(novelty=0.0) == 0.0


def test_empty_panel_is_safe():
    r = PanelResult(trap_family="x", n_cases=0, panel=())
    assert r.pass_max == 0.0
    assert r.pass_min == 0.0
    assert r.spread == 0.0
    assert r.solvable is False


# ─── Novelty ────────────────────────────────────────────────────────────


def test_novelty_empty_history_is_one():
    r = _mk({"a": 1.0, "b": 0.0, "c": 0.5})
    assert novelty_score(r, []) == 1.0


def test_novelty_identical_history_is_zero():
    pattern = {"a": 1.0, "b": 0.0, "c": 0.5}
    r = _mk(pattern, trap="new")
    h = [_mk(pattern, trap="old")]
    assert novelty_score(r, h) < 0.01  # close to 0, allow float dust


def test_novelty_orthogonal_history_is_positive():
    r = _mk({"a": 1.0, "b": 0.0, "c": 0.5})
    h = [_mk({"a": 0.0, "b": 1.0, "c": 0.5})]
    nov = novelty_score(r, h)
    assert nov > 0.3  # the per-model vectors point in noticeably different directions


def test_novelty_takes_nearest_history():
    # Candidate matches one prior closely and one prior loosely;
    # novelty should reflect the *closest* match (lowest distance).
    r = _mk({"a": 1.0, "b": 0.0})
    near = _mk({"a": 1.0, "b": 0.1})
    far = _mk({"a": 0.0, "b": 1.0})
    nov_near = novelty_score(r, [near])
    nov_far = novelty_score(r, [far])
    nov_both = novelty_score(r, [near, far])
    # The nearest prior dominates: novelty against {near} stays low,
    # adding `far` to history doesn't make it higher.
    assert nov_both <= nov_near + 1e-6
    assert nov_far > nov_near  # sanity: far prior is more "different"


# ─── write_results_row TSV serialisation ────────────────────────────────


def test_write_results_row_creates_header(tmp_path):
    out = tmp_path / "results.tsv"
    write_results_row(
        out, timestamp="2026-01-01T00:00:00Z",
        candidate_id="c1", researcher_model="anthropic:opus", trap_family="x",
        status="keep", score=0.5, spread=0.7, solvable=True, cost_usd=1.0,
        per_model_pass={"haiku": 0.9},
        rationale="why",
    )
    text = out.read_text(encoding="utf-8")
    assert text.startswith("timestamp\t")
    assert text.count("\n") == 2  # header + 1 row


def test_write_results_row_sanitises_tabs_in_rationale(tmp_path):
    out = tmp_path / "results.tsv"
    write_results_row(
        out, timestamp="t", candidate_id="c1", researcher_model="m",
        trap_family="x", status="keep", score=0.0, spread=0.0,
        solvable=True, cost_usd=0.0, per_model_pass={},
        rationale="line1\twith\ttabs\nand\nnewlines",
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # header + one data row (newlines stripped)
    # Each data row should have exactly 10 tabs (11 fields)
    assert lines[1].count("\t") == 10
