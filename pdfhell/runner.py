"""Run a model against a pdfhell suite.

The runner is intentionally thin. It:

1. Loads cases from disk (or builds them on demand by re-seeding).
2. Sends each ``(question, pdf)`` pair to a vision-capable model.
3. Scores the model's free-text answer against code-based ground truth.

It does NOT do its own scoring methodology — that lives in
:mod:`pdfhell.scorer`. It does NOT do its own provider dispatch — that
lives in :mod:`multivon_eval.judge` (we reuse the vision-call dispatch
from the multimodal evaluators).
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from multivon_eval import JudgeConfig

from .case import HellCase
from .scorer import CaseScore, SuiteReport, score_case, summarise
from .vision import call_vision


def parse_model_spec(spec: str) -> JudgeConfig:
    """Parse ``"provider:model"`` shorthand into a ``JudgeConfig``.

    Examples::

        anthropic:claude-sonnet-4-6
        openai:gpt-4o
        google:gemini-2.5-pro

    The shorthand is opinionated about temperature (0.0 — we want
    deterministic answers for a benchmark) and max_tokens (256 — answers
    should be short; long answers usually mean the model is rambling
    around the answer rather than giving it).
    """
    if ":" not in spec:
        raise ValueError(
            f"model spec must be 'provider:model', got {spec!r}. "
            "Example: anthropic:claude-sonnet-4-6"
        )
    provider, model = spec.split(":", 1)
    provider = provider.strip().lower()
    if provider not in {"anthropic", "openai", "google"}:
        raise ValueError(
            f"unsupported provider {provider!r}; "
            "use anthropic, openai, or google"
        )
    # max_tokens=2048 gives prose answers room (e.g. footnote_override
    # carve-out summaries) without letting models ramble. Gemini 2.5
    # Flash allocates output tokens to internal "thinking"; tight
    # budgets either produce empty responses or truncate mid-sentence.
    # 2k is sufficient headroom in practice.
    return JudgeConfig(
        provider=provider,
        model=model.strip(),
        temperature=0.0,
        max_tokens=2048,
    )


@dataclass(slots=True)
class _Job:
    case: HellCase
    pdf_path: Path


def _ask_model(job: _Job, judge: JudgeConfig) -> tuple[HellCase, str]:
    """Send one case to the model. Returns (case, raw_answer).

    Provider-level errors propagate as JudgeUnavailable. The CLI catches
    them and records the case as refused.
    """
    answer = call_vision(
        prompt=job.case.question,
        sources=[str(job.pdf_path)],
        judge=judge,
        max_tokens=judge.max_tokens or 2048,
    )
    return job.case, answer.strip()


def run_suite(
    cases_dir: Path,
    model_spec: str,
    *,
    workers: int = 4,
    progress: bool = True,
    suite_name: str = "mini",
) -> SuiteReport:
    """Evaluate every case under ``cases_dir`` against ``model_spec``.

    ``cases_dir`` must contain ``<case_id>.json`` and ``<case_id>.pdf``
    pairs produced by :func:`pdfhell.suite.build_suite`.
    """
    judge = parse_model_spec(model_spec)
    jobs = list(_load_jobs(cases_dir))
    if not jobs:
        raise FileNotFoundError(f"no cases found in {cases_dir}")
    scores: list[CaseScore] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_ask_model, job, judge): job for job in jobs}
        completed = 0
        for fut in as_completed(futures):
            job = futures[fut]
            try:
                case, answer = fut.result()
            except Exception as exc:  # JudgeUnavailable, provider error, etc.
                # Treat upstream errors as refusals so the run still
                # produces a complete report; the case is scored as
                # incorrect with a refusal flag.
                case = job.case
                answer = f"[error] {type(exc).__name__}: {exc}"
            score = score_case(case, answer)
            scores.append(score)
            completed += 1
            if progress:
                mark = "✓" if score.correct else ("⚠" if score.fell_for_trap else "✗")
                print(f"  {mark} {score.case_id:36s}  expected={score.expected!r:30s}  got={answer[:60]!r}")
    return summarise(model_spec, suite_name, scores)


def _load_jobs(cases_dir: Path) -> Iterable[_Job]:
    """Yield (case, pdf_path) pairs sorted by case id."""
    for json_path in sorted(cases_dir.glob("*.json")):
        case = HellCase.load_json(json_path)
        pdf_path = json_path.with_suffix(".pdf")
        if not pdf_path.exists():
            # The case JSON tracks its own pdf_path relative to the
            # suite root; honour that as a fallback.
            pdf_path = (cases_dir / case.pdf_path).resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(
                f"PDF not found for case {case.id}; expected {pdf_path}"
            )
        yield _Job(case=case, pdf_path=pdf_path)
