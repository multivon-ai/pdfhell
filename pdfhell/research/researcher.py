"""The LLM researcher.

A researcher reads ``program.md``, the existing generators, and the
most recent rows of ``results.tsv``, and proposes the next candidate
to evaluate. Proposals are structured as JSON.

We rotate among three strong reasoning models so the search doesn't
collapse into one model's preferred patterns:

    1. anthropic:claude-opus-4-7
    2. openai:gpt-5
    3. google:gemini-3.0-pro

If a model returns a malformed proposal we count it as a `crash` and
move to the next researcher in the rotation. The malformed-proposal
rate is itself a research artifact worth tracking.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

from .budget import estimate_proposal_cost


RESEARCHER_ROTATION: tuple[str, ...] = (
    "anthropic:claude-opus-4-7",
    "openai:gpt-5",
    "google:gemini-2.5-pro",
)


@dataclass(slots=True)
class Proposal:
    """One structured proposal from a researcher.

    ``action`` is either:
      - ``create_generator``: write a new file at ``target_path`` with
        ``code`` and register ``trap_family`` in the GENERATORS dict
      - ``modify_generator``: replace the file at ``target_path`` with
        ``code`` (existing trap family — Tier 1 mutation)
    """

    action: str            # "create_generator" | "modify_generator"
    trap_family: str       # snake_case identifier
    target_path: str       # relative to repo root
    code: str              # full python file contents
    rationale: str         # ≤ 500 char explanation
    researcher_model: str  # which model emitted this


# ─── Building the prompt ────────────────────────────────────────────────


_SYSTEM_PROMPT = """You are an adversarial benchmark researcher. Your job is to
propose new PDF trap-family generators that discriminate between current
frontier vision-language models when they read documents.

You will read three things:
1. program.md (the rules of the experiment — read it carefully)
2. The contents of pdfhell/generators/_common.py (the primitives you must use)
3. Recent rows of pdfhell/research/results.tsv (what's been tried and what worked)

Then you propose ONE candidate: either a new generator file (preferred) or a
modification to an existing one. You output STRICT JSON in the format below,
nothing else (no markdown fences, no commentary):

{
  "action": "create_generator" | "modify_generator",
  "trap_family": "<snake_case_name>",
  "target_path": "pdfhell/generators/<trap_family>.py",
  "code": "<full python file contents>",
  "rationale": "<≤500 char explanation of the failure mechanism you're targeting>"
}

Hard constraints:
- The code must define exactly one public function: `def generate(seed: int) -> tuple[bytes, HellCase]`
- The code must use `rng_for(seed)`, never global `random`
- The code must use `canvas_to_bytes(draw)` (it sets invariant=True for byte-determinism)
- The expected_answer must be a string that any competent human, reading the document carefully, would also return
- forbidden_answers must NOT contain substrings that a correct verbose answer would quote (e.g. don't put "Section 4.2" or quoted clause text in forbidden_answers)
- Do not modify pdfhell/generators/__init__.py — the loop will register your candidate automatically

Quality criteria:
- Simpler is better. A 50-line generator that discriminates is more valuable than a 250-line one.
- Novel mechanisms beat re-runs of existing mechanisms.
- The trap must be procedurally fair: a human reading the PDF can answer correctly.
"""


_USER_PROMPT_TEMPLATE = """## program.md

{program_md}

## pdfhell/generators/_common.py (the primitives — use these, do not re-invent)

{common_py}

## Reference generator (a working example you can pattern-match on)

{reference_py}

## Recent results.tsv (last 30 rows)

{recent_tsv}

## Prior kept candidates (positive examples — these scored well)

{kept_examples}

## Trap names already attempted this session — DO NOT RE-USE these names

{tried_names}

## Your task

Propose ONE candidate. Output JSON only, no prose. Pick a trap_family name that doesn't appear in the "already attempted" list above, and doesn't collide with existing v1/v2 trap names (hidden_ocr_mismatch, footnote_override, split_table_across_pages, composite_trap, scale_dependent_rendering, cross_page_coreference).

Strategic guidance:
- If `results.tsv` is empty and there are no kept examples, this is the first run — pick a high-novelty direction (the program.md "hints" section lists some)
- If kept examples exist, study what made them work — but DON'T duplicate the mechanism. A trap that discriminates the *same models* via a *different mechanism* is fine; a trap that just re-implements an existing mechanism is rejected at score (novelty=0)
- If recent rows show repeated revert_probe or gate_fail for similar mechanisms (look at the rationale column), abandon that direction — the eval panel already handles it or the gates trip
- Many models have the *same* blind spot. Finding novel mechanisms that defeat models OTHER than Opus-4-7 + Gemini-Flash-Lite is more valuable than yet-another-Opus-defeater

JSON proposal:"""


def build_prompt(
    *,
    program_md_path: Path,
    common_py_path: Path,
    reference_py_path: Path,
    results_tsv_path: Path,
    tried_names: list[str] | None = None,
    keep_dir: Path | None = None,
    max_kept_examples: int = 2,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt). Both are pre-formatted.

    ``tried_names`` is the set of trap_family names already attempted
    in the current session. Pass it explicitly so the agent doesn't
    re-propose a name that's already been evaluated (waste of spend).

    ``keep_dir``: directory of kept candidate JSONs. If provided, the
    top-scoring kept candidates are included as positive examples in
    the prompt so the agent can calibrate on what "good" looks like.
    """
    program_md = program_md_path.read_text(encoding="utf-8") if program_md_path.exists() else ""
    common_py = common_py_path.read_text(encoding="utf-8") if common_py_path.exists() else ""
    reference_py = reference_py_path.read_text(encoding="utf-8") if reference_py_path.exists() else ""
    if results_tsv_path.exists():
        lines = results_tsv_path.read_text(encoding="utf-8").splitlines()
        recent = "\n".join(lines[-30:]) if len(lines) > 30 else "\n".join(lines)
    else:
        recent = "(empty — first run)"

    if tried_names:
        tried_block = "\n".join(f"  - {n}" for n in sorted(set(tried_names)))
    else:
        tried_block = "  (none yet — this is the first proposal this session)"

    # Pull in top-scoring kept candidates as positive examples. Cap at
    # max_kept_examples and trim code blocks so we don't blow the
    # context budget — researchers are seeing program.md + _common.py +
    # a full reference already, plus recent_tsv. Aim for ~3K extra tokens
    # for kept examples max.
    kept_examples = "(no prior keepers — first run or none have scored above 0)"
    if keep_dir is not None and keep_dir.exists():
        keepers: list[dict] = []
        for f in sorted(keep_dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                keepers.append(d)
            except (json.JSONDecodeError, OSError):
                continue
        keepers.sort(key=lambda d: d.get("score", 0), reverse=True)
        if keepers:
            blocks: list[str] = []
            for k in keepers[:max_kept_examples]:
                spread = k.get("full_result", {}).get("spread", 0)
                novelty = k.get("novelty", 0)
                per_model = k.get("full_result", {}).get("per_model_pass", {})
                code = k.get("code", "")
                if len(code) > 5000:
                    code = code[:5000] + "\n# ...truncated for context...\n"
                blocks.append(
                    f"### {k.get('trap_family')}  (score={k.get('score', 0):.2f}, "
                    f"spread={spread:.2f}, novelty={novelty:.2f})\n"
                    f"Rationale: {k.get('rationale', '')[:300]}\n"
                    f"Per-model pass: {json.dumps(per_model, sort_keys=True)}\n"
                    f"```python\n{code}\n```"
                )
            kept_examples = "\n\n".join(blocks)

    user = _USER_PROMPT_TEMPLATE.format(
        program_md=program_md,
        common_py=common_py,
        reference_py=reference_py,
        recent_tsv=recent,
        tried_names=tried_block,
        kept_examples=kept_examples,
    )
    return _SYSTEM_PROMPT, user


# ─── Calling the researcher ────────────────────────────────────────────


def _call_researcher(model_spec: str, system: str, user: str) -> str | None:
    """Issue one API call to the researcher.

    We call the provider SDKs directly rather than going through
    multivon_eval's adapters — the adapter layer sends parameters
    (``temperature``, ``max_tokens``) that newer reasoning models
    (Opus 4-7, GPT-5) reject, and we'd rather control the request
    shape ourselves than chase adapter compatibility.
    """
    try:
        provider, model = model_spec.split(":", 1)
    except ValueError:
        return None
    try:
        if provider == "anthropic":
            return _call_anthropic(model, system, user)
        if provider == "openai":
            return _call_openai(model, system, user)
        if provider == "google":
            return _call_google(model, system, user)
    except Exception as exc:
        print(f"[researcher] {model_spec} failed: {exc}")
        return None
    return None


def _call_anthropic(model: str, system: str, user: str) -> str | None:
    """Direct Anthropic SDK call. Reasoning models (Opus 4-7) reject
    ``temperature``, so we don't pass it. ``max_tokens`` is still the
    correct field for the Anthropic Messages API."""
    try:
        from anthropic import Anthropic
    except ImportError:
        return None
    client = Anthropic()  # picks up ANTHROPIC_API_KEY from env
    resp = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if not resp.content:
        return None
    # Concatenate text blocks (ignoring tool-use blocks).
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "".join(parts) if parts else None


def _call_openai(model: str, system: str, user: str) -> str | None:
    """Direct OpenAI SDK call via the Responses API.

    The newer reasoning models (GPT-5, o3) use ``max_completion_tokens``
    in the chat API but ``max_output_tokens`` in the Responses API —
    we go through Responses because it's cleaner for system prompts
    and reasoning-style multi-step outputs.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return None
    client = OpenAI()
    resp = client.responses.create(
        model=model,
        instructions=system,
        input=user,
        max_output_tokens=8192,
    )
    return resp.output_text or None


def _call_google(model: str, system: str, user: str) -> str | None:
    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        return None
    client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
    cfg = gtypes.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=8192,
    )
    resp = client.models.generate_content(
        model=model, contents=user, config=cfg,
    )
    return resp.text or None


# ─── Parsing the response ──────────────────────────────────────────────


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_proposal(raw: str, researcher_model: str) -> Proposal | None:
    """Parse a researcher's response into a Proposal.

    We accept either:
    - A bare JSON object (the strict format we asked for)
    - A JSON object inside a ```json``` code fence (sometimes models
      add the fence despite instructions)

    If parsing fails we log and return None — the loop logs this as a
    `crash` and moves to the next researcher.
    """
    if not raw:
        return None

    # Try fenced first (handles polite models that wrap despite the rule)
    m = _JSON_FENCE.search(raw)
    payload = m.group(1) if m else raw.strip()

    # Some models still prefix prose. Find the first '{' and last '}'
    # and try parsing that slab.
    first = payload.find("{")
    last = payload.rfind("}")
    if first == -1 or last == -1 or last <= first:
        return None

    try:
        obj = json.loads(payload[first : last + 1])
    except json.JSONDecodeError:
        return None

    required = ("action", "trap_family", "target_path", "code", "rationale")
    if not all(k in obj for k in required):
        return None

    action = obj["action"]
    if action not in ("create_generator", "modify_generator"):
        return None

    trap_family = obj["trap_family"]
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", trap_family):
        return None

    target_path = obj["target_path"]
    expected = f"pdfhell/generators/{trap_family}.py"
    if target_path != expected:
        # Don't argue, just normalise.
        target_path = expected

    code = obj["code"]
    if not isinstance(code, str) or "def generate" not in code:
        return None

    rationale = str(obj["rationale"])[:500]

    return Proposal(
        action=action,
        trap_family=trap_family,
        target_path=target_path,
        code=code,
        rationale=rationale,
        researcher_model=researcher_model,
    )


# ─── The rotation iterator ──────────────────────────────────────────────


def rotation() -> "itertools.cycle[str]":
    """An infinite iterator over the researcher rotation."""
    return itertools.cycle(RESEARCHER_ROTATION)


def propose(
    rotator: "itertools.cycle[str]",
    *,
    program_md_path: Path,
    common_py_path: Path,
    reference_py_path: Path,
    results_tsv_path: Path,
    max_retries: int = 3,
    tried_names: list[str] | None = None,
    keep_dir: Path | None = None,
) -> Proposal | None:
    """Get one proposal from the next researcher in rotation.

    On parse failure we cycle to the next researcher (up to
    ``max_retries`` total). If the researcher returns a name that
    was already tried this session, we count it as a retry-eligible
    failure (the rotation will hit a different researcher next).

    The caller is responsible for cost accounting — call
    ``estimate_proposal_cost`` if you need to pre-flight.
    """
    system, user = build_prompt(
        program_md_path=program_md_path,
        common_py_path=common_py_path,
        reference_py_path=reference_py_path,
        results_tsv_path=results_tsv_path,
        tried_names=tried_names,
        keep_dir=keep_dir,
    )
    tried_set = set(tried_names or [])
    for _ in range(max_retries):
        model = next(rotator)
        raw = _call_researcher(model, system, user)
        if raw is None:
            continue
        proposal = parse_proposal(raw, researcher_model=model)
        if proposal is None:
            continue
        if proposal.trap_family in tried_set:
            # The agent re-proposed an existing name despite the
            # tried_names hint. Try the next researcher in rotation;
            # they may pick a different direction.
            continue
        return proposal
    return None
