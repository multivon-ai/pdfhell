"""Validation gates for agent-proposed trap generators.

The agent will try to game the discrimination metric. These gates are
how we stay honest:

1. **Parseable** — the candidate's generate(seed) returns a valid PDF
2. **Deterministic** — same seed → byte-identical PDF (twice)
3. **Answerable** — text-only LLM verifiers agree on the expected answer
4. **Forbidden-clean** — forbidden_answers don't false-positive on verbose-correct
5. **Lint-clean** — generator file passes ruff + imports without error

Each gate returns ``GateResult(passed, reason)``. If any gate fails the
candidate is reverted and the failure is logged. We don't grade on a
curve — partial credit means the agent learns to half-pass gates.
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pdfhell.case import HellCase


# ─── Result type ────────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class GateResult:
    passed: bool
    gate: str
    reason: str = ""

    def __bool__(self) -> bool:
        return self.passed


# ─── Gate 1: parseable ─────────────────────────────────────────────────


def gate_parseable(pdf_bytes: bytes) -> GateResult:
    """The PDF must open in at least one mainstream Python PDF parser.

    Tries pypdf first (strict-conformance, what most enterprise
    pipelines use), then pdfplumber (laxer, built on pdfminer.six)
    as a fallback. The intent is to accept PDFs that any major
    real-world tool can read, even if pypdf's stricter validation
    flags non-fatal annotation-dict quirks (e.g., reportlab's
    FreeTextAnnotation missing ``fontName``).

    Reasoning: a PDF that pdfplumber can parse will be successfully
    read by RAG pipelines (LangChain's PyMuPDFLoader, LlamaIndex's
    PyPDFLoader, etc.) — strict-only rejection drops valid traps.
    """
    pypdf_err = None
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        n = len(reader.pages)
        if n < 1:
            return GateResult(False, "parseable", "0 pages (pypdf)")
        return GateResult(True, "parseable", f"{n} pages (pypdf)")
    except ImportError:
        return GateResult(False, "parseable", "no PDF parser installed")
    except Exception as exc:
        pypdf_err = f"{type(exc).__name__}: {exc}"

    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            n = len(pdf.pages)
        if n < 1:
            return GateResult(False, "parseable", "0 pages (pdfplumber)")
        return GateResult(
            True, "parseable",
            f"{n} pages (pdfplumber fallback; pypdf said: {pypdf_err[:80]})",
        )
    except ImportError:
        pass
    except Exception as exc:
        return GateResult(
            False, "parseable",
            f"both parsers failed. pypdf: {pypdf_err[:120]}. "
            f"pdfplumber: {type(exc).__name__}: {exc}",
        )

    return GateResult(False, "parseable", f"pypdf: {pypdf_err}")


# Substitution glyphs that betray an unencodable character: a generator
# that draws a codepoint outside the font's encoding gets a visible tofu
# box on the page (and a substitute char in the text layer) instead of
# what it intended. The zero_width_space_split family shipped exactly
# this bug for five releases — "visually normal" with a black box in the
# Grand Total (issue #8). The five original gates were text/code-level
# and structurally could not catch a rendering artifact.
_SUBSTITUTION_CHARS = "\u25a0\u25a1\ufffd"  # ■ □ �


def gate_glyph_clean(pdf_bytes: bytes) -> GateResult:
    """No substitution/tofu glyphs in the extracted text.

    Generators that *intend* visual transformations do them with canvas
    transforms (mirror_image_glyphs, upside_down_amount), which keep the
    text layer in ordinary characters — so this gate is safe for them.
    """
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = "".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        return GateResult(False, "glyph_clean",
                          f"could not extract text: {type(exc).__name__}: {exc}")
    bad = sorted({ch for ch in text if ch in _SUBSTITUTION_CHARS})
    if bad:
        return GateResult(
            False, "glyph_clean",
            f"substitution glyph(s) {bad!r} in extracted text — a drawn "
            f"string contains characters the font cannot encode; the page "
            f"shows a tofu box where the generator thinks its text is",
        )
    return GateResult(True, "glyph_clean", "no substitution glyphs")


# ─── Gate 2: deterministic ─────────────────────────────────────────────


def gate_deterministic(
    generate_fn,
    seed: int,
) -> GateResult:
    """generate(seed) must return byte-identical PDFs across two calls."""
    try:
        pdf_a, case_a = generate_fn(seed)
        pdf_b, case_b = generate_fn(seed)
    except Exception as exc:
        return GateResult(False, "deterministic", f"generate raised: {exc}")
    if pdf_a != pdf_b:
        return GateResult(
            False,
            "deterministic",
            f"PDF bytes differ ({len(pdf_a)} vs {len(pdf_b)})",
        )
    if case_a.id != case_b.id or case_a.expected_answer != case_b.expected_answer:
        return GateResult(False, "deterministic", "HellCase fields differ")
    return GateResult(True, "deterministic", f"{len(pdf_a)} bytes stable")


# ─── Gate 3: answerable ────────────────────────────────────────────────


_VERIFIER_PROMPT = """You are reading a document. Below is the full
TEXT of a PDF (extracted directly from the vector text stream, not
from OCR), followed by a question.

Answer the question using ONLY information present in the text below.
Respond with the SHORTEST possible answer (a single number, name, or
phrase). If the text genuinely doesn't contain the answer, respond
"INSUFFICIENT".

DOCUMENT TEXT:
{text}

QUESTION: {question}

ANSWER (shortest form):"""


def gate_answerable(
    pdf_bytes: bytes,
    case: HellCase,
    *,
    verifiers: tuple[str, ...] = (
        "anthropic:claude-haiku-4-5",
        "google:gemini-2.5-flash",
        "openai:gpt-4.1",
        "anthropic:claude-sonnet-4-6",
    ),
    quorum: int = 3,
) -> GateResult:
    """Independent text-only LLMs must agree on the expected answer.

    The verifier reads the *extracted text* (not the rendered image)
    plus the question. If at least ``quorum`` of ``verifiers`` return
    an answer that contains ``case.expected_answer`` as a substring
    (loose match), the case is answerable. Otherwise it's ambiguous
    and we reject.

    We use a different reading modality than the eval panel
    intentionally — the eval panel reads images, the verifier reads
    text. The expected answer should be derivable from BOTH (humans
    can read either). If the verifier can't get the answer from text,
    the question is broken.
    """
    try:
        import pypdf
    except ImportError:
        return GateResult(False, "answerable", "pypdf not installed")

    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = "\n\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as exc:
        return GateResult(False, "answerable", f"text-extract failed: {exc}")

    if len(text.strip()) < 20:
        return GateResult(
            False,
            "answerable",
            f"extracted text too short ({len(text.strip())} chars) — "
            "vector text is missing or PDF is image-only",
        )

    prompt = _VERIFIER_PROMPT.format(text=text[:30_000], question=case.question)
    answers: list[str] = []
    for verifier in verifiers:
        out = _ask_text_only(verifier, prompt)
        if out is not None:
            answers.append(out.lower().strip())

    if len(answers) < quorum:
        return GateResult(
            False,
            "answerable",
            f"only {len(answers)}/{len(verifiers)} verifiers responded "
            "(provider errors)",
        )

    expected_lower = case.expected_answer.lower()
    agreement = sum(1 for a in answers if expected_lower in a or _loose_eq(a, expected_lower))
    if agreement < quorum:
        return GateResult(
            False,
            "answerable",
            f"only {agreement}/{len(answers)} verifiers found expected={case.expected_answer!r} "
            f"in their answers (responses: {answers[:3]})",
        )
    return GateResult(True, "answerable", f"{agreement}/{len(answers)} verifiers agree")


def _loose_eq(a: str, b: str) -> bool:
    """Looser equality for numeric / currency answers.

    Handles the common verifier-vs-expected drift modes:
      - "$1,234.56" vs "1234.56"           — currency symbol, commas
      - "$18,400.00" vs "$18,400"          — trailing .00 vs implicit integer
      - "1.5 million" vs "1500000"         — different magnitudes (NOT handled)
      - "USD 1234" vs "$1,234"             — alt currency markers
    """
    # Strip everything non-alphanumeric except '.', then attempt float
    # equality. This collapses "$1,234.56" → "1234.56" and lets us
    # compare to "1234.56" or "$1234.56" without fragile substring rules.
    def _num(s: str) -> float | None:
        clean = "".join(ch for ch in s if ch.isdigit() or ch == "." or ch == "-")
        # Handle ".50" or "-." edge cases by requiring at least one digit
        if not any(ch.isdigit() for ch in clean):
            return None
        try:
            return float(clean)
        except ValueError:
            return None

    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        # Float equality with a small absolute tolerance for currency rounding
        return abs(na - nb) < 1e-4

    # Fall back to alphanumeric-only comparison for non-numeric answers
    def _norm(s: str) -> str:
        return "".join(ch for ch in s if ch.isalnum())

    return _norm(a) == _norm(b)


def _ask_text_only(model_spec: str, prompt: str) -> str | None:
    """Call ``model_spec`` with a text prompt and return the response.

    Goes directly through the provider SDKs (not multivon_eval) so we
    can speak each provider's current parameter contract:
    - Anthropic Messages API: ``max_tokens``, no ``temperature`` on
      reasoning-tier models
    - OpenAI Responses API: ``max_output_tokens``
    - Google genai SDK: config-style
    """
    try:
        provider, model = model_spec.split(":", 1)
    except ValueError:
        return None
    try:
        if provider == "anthropic":
            return _ask_anthropic_text(model, prompt)
        if provider == "openai":
            return _ask_openai_text(model, prompt)
        if provider == "google":
            return _ask_google_text(model, prompt)
    except Exception:
        return None
    return None


def _ask_anthropic_text(model: str, prompt: str) -> str | None:
    try:
        from anthropic import Anthropic
    except ImportError:
        return None
    client = Anthropic()
    resp = client.messages.create(
        model=model, max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    if not resp.content:
        return None
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text") or None


def _ask_openai_text(model: str, prompt: str) -> str | None:
    try:
        from openai import OpenAI
    except ImportError:
        return None
    client = OpenAI()
    resp = client.responses.create(
        model=model, input=prompt, max_output_tokens=400,
    )
    return resp.output_text or None


def _ask_google_text(model: str, prompt: str) -> str | None:
    try:
        from google import genai
    except ImportError:
        return None
    client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
    resp = client.models.generate_content(model=model, contents=prompt)
    return resp.text or None


# ─── Gate 4: forbidden-clean ────────────────────────────────────────────


_VERBOSE_PROMPT = """You are reading a document. Below is the full
TEXT of a PDF (extracted directly from the vector text stream, not
from OCR), followed by a question.

Answer the question THOROUGHLY. Cite the source clause verbatim. Use
multiple sentences. Show your reasoning.

DOCUMENT TEXT:
{text}

QUESTION: {question}

VERBOSE ANSWER:"""


def gate_forbidden_clean(
    pdf_bytes: bytes,
    case: HellCase,
    *,
    verifier: str = "anthropic:claude-sonnet-4-6",
) -> GateResult:
    """forbidden_answers must not appear in a verbose-correct response.

    The cross_page_coreference bug we fixed in 0.2.0 was exactly this:
    forbidden_answers contained source-text snippets that a *correct*
    verbose answer would quote. This gate catches that class of bug
    before it lands.

    Procedure: ask a verifier model to answer thoroughly, citing the
    source. If any forbidden_answer appears as a substring of that
    correct-and-verbose response, the gate fails — the forbidden list
    is too broad.
    """
    if not case.forbidden_answers:
        return GateResult(True, "forbidden_clean", "no forbidden_answers to check")

    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = "\n\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as exc:
        return GateResult(False, "forbidden_clean", f"text-extract failed: {exc}")

    prompt = _VERBOSE_PROMPT.format(text=text[:30_000], question=case.question)
    response = _ask_text_only(verifier, prompt)
    if response is None:
        # Verifier unavailable — don't reject, but flag. The probe
        # round will catch over-broad forbiddens via raw spread anyway.
        return GateResult(True, "forbidden_clean", "verifier unavailable; skipped")

    response_lower = response.lower()
    expected_lower = case.expected_answer.lower()
    if expected_lower not in response_lower:
        # The verbose answer didn't get the right answer — that's a
        # separate problem (answerability) but doesn't break the
        # forbidden gate per se.
        return GateResult(True, "forbidden_clean", "verifier did not produce expected answer")

    for forbidden in case.forbidden_answers:
        if forbidden.lower() in response_lower:
            return GateResult(
                False,
                "forbidden_clean",
                f"forbidden_answer {forbidden!r} appears in verbose-correct response — "
                "the forbidden list is over-broad and will false-positive against good answers",
            )
    return GateResult(True, "forbidden_clean", f"checked {len(case.forbidden_answers)} forbiddens")


# ─── Gate 5: lint-clean ────────────────────────────────────────────────


def gate_lint_clean(generator_path: Path) -> GateResult:
    """ruff check + python -c 'import <module>' must succeed."""
    if not generator_path.exists():
        return GateResult(False, "lint", f"file not found: {generator_path}")

    # 5a: ruff
    try:
        proc = subprocess.run(
            ["ruff", "check", "--quiet", str(generator_path)],
            capture_output=True,
            timeout=15,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or proc.stdout).decode("utf-8", errors="replace")
            return GateResult(False, "lint", f"ruff failed: {stderr[:300]}")
    except FileNotFoundError:
        # ruff not installed; skip but don't fail. The agent won't
        # learn to write clean code if the linter is silent — but
        # better to run partially than not at all.
        pass
    except subprocess.TimeoutExpired:
        return GateResult(False, "lint", "ruff timed out")

    # 5b: import smoke test (catches syntax errors ruff missed + missing
    # imports at module level). In-tree generators may use relative imports
    # (`from . import _common`), so import them by dotted module name within
    # the package. For a generator outside the package tree (e.g. a tmp file
    # under test, or a candidate staged elsewhere), relative_to() raises
    # ValueError — fall back to loading by file path, which still surfaces
    # syntax/import errors.
    pkg_root = Path(__file__).resolve().parents[2]
    gen_resolved = generator_path.resolve()
    try:
        module = str(gen_resolved.relative_to(pkg_root)).replace("/", ".").removesuffix(".py")
    except ValueError:
        module = None
    try:
        if module is not None:
            # Force re-import in case the file changed since last run.
            if module in sys.modules:
                importlib.reload(sys.modules[module])
            else:
                importlib.import_module(module)
        else:
            spec = importlib.util.spec_from_file_location(
                f"_pdfhell_gate_{gen_resolved.stem}", gen_resolved
            )
            if spec is None or spec.loader is None:
                return GateResult(False, "lint", f"could not load {generator_path.name}")
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
    except Exception as exc:
        return GateResult(False, "lint", f"import {generator_path.name} failed: {type(exc).__name__}: {exc}")

    return GateResult(True, "lint", "ruff + import OK")


# ─── Composite runner ──────────────────────────────────────────────────


def run_all_gates(
    generator_path: Path,
    trap_family: str,
    seed: int,
) -> list[GateResult]:
    """Run every gate in sequence. Returns a list of results, one per
    gate. Short-circuits on the first failure for the expensive gates
    (parseable + deterministic are cheap, answerable + forbidden_clean
    cost API calls)."""
    # Always re-import to pick up new file
    from pdfhell.generators import GENERATORS
    if trap_family in sys.modules:
        importlib.reload(sys.modules.get(f"pdfhell.generators.{trap_family}", sys.modules[__name__]))

    results: list[GateResult] = []

    # 5 first — cheap, catches dumb syntax errors before we waste API calls
    lint = gate_lint_clean(generator_path)
    results.append(lint)
    if not lint:
        return results

    # Need a generator handle
    if trap_family not in GENERATORS:
        results.append(GateResult(
            False, "registry",
            f"{trap_family!r} not registered in GENERATORS",
        ))
        return results
    gen_fn = GENERATORS[trap_family]

    # 1, 2: cheap, no API
    try:
        pdf_bytes, case = gen_fn(seed)
    except Exception as exc:
        results.append(GateResult(False, "parseable", f"generate raised: {exc}"))
        return results

    results.append(gate_parseable(pdf_bytes))
    if not results[-1]:
        return results

    results.append(gate_glyph_clean(pdf_bytes))
    if not results[-1]:
        return results

    results.append(gate_deterministic(gen_fn, seed))
    if not results[-1]:
        return results

    # 3, 4: expensive, API-bound
    results.append(gate_answerable(pdf_bytes, case))
    if not results[-1]:
        return results

    results.append(gate_forbidden_clean(pdf_bytes, case))
    return results
