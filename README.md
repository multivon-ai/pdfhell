# PDF Hell

**Adversarial PDFs that break AI document readers — with procedural ground truth, not LLM-as-judge.**

PDF Hell is a small, sharp benchmark for the "AI reads PDFs" claim. Every test case is a PDF generated *from code*, so the correct answer is known exactly. There's no LLM judging another LLM's interpretation — the same loop that fooled the model isn't asked to grade it.

If your AI claims it can read documents, it should survive PDFs designed to break it.

## Quickstart

```bash
# Run the mini suite against a vision model (uses your API key from env)
export ANTHROPIC_API_KEY=sk-ant-...
uvx pdfhell run --model anthropic:claude-sonnet-4-6

# Or generate one trap PDF for inspection
uvx pdfhell make --trap hidden_ocr_mismatch --seed 42
open ./cases/hidden_ocr_mismatch-0042.pdf

# List available trap families
uvx pdfhell list-traps
```

That's it. The mini suite is 30 procedurally-generated cases across 3 trap families. Costs about $0.01 against `claude-haiku-4-5` and runs in under 30 seconds.

## What's in the mini suite

| Trap family | Cases | What breaks |
|---|---|---|
| `hidden_ocr_mismatch` | 10 | Invoices where the visible amount differs from an invisible text layer. Vision-only models read the page; text-extraction pipelines read the layer; they disagree. |
| `footnote_override` | 10 | Legal clauses where a 6pt footnote overrides the body — liability caps with carve-outs, terminations with restrictions, data-residency with disaster-recovery exceptions. |
| `split_table_across_pages` | 10 | Financial tables where the header row sits on page 1 and the body rows on page 2. RAG loaders that paginate independently lose column context. |

Every case has a deterministic seed. Re-running with the same seed regenerates byte-identical PDFs and identical answer keys.

## Why this exists

The current AI-eval state of the art uses an LLM-as-judge to grade another LLM's answer. That's circular assurance: the same complexity that fools the agent fools the judge. PDF Hell rejects that. The PDF is generated from code, so we have:

1. **Code-based ground truth.** The answer is a literal Python value the generator chose, not a frontier model's opinion.
2. **A named failure mode per trap.** When a model fails, we know *which* specific failure it fell into (e.g. "trusted the hidden OCR layer over the visible page").
3. **A diagnostic signal**, not just a score. Pass rate is the headline, but per-trap-family breakdown tells you which assumption broke.

## Sample run (Gemini 2.5 Flash on a 3-case smoke subset)

```
✓ hidden_ocr_mismatch-1001        expected='$1,234.56'        got='$1,234.56'
✗ footnote_override-2001          expected='Liability is capped at 12 months ... EXCEPT ...'
                                  got='Based on the SOW: liability shall not exceed...'
✓ split_table_across_pages-3001   expected='$780,803.18'      got='$780,803.18'

PDF Hell mini suite — n=3
model: google:gemini-2.5-flash
pass: 2/3  (66.7%)
per-trap pass rate:
  hidden_ocr_mismatch         pass=100%  fell-for-trap=0%
  split_table_across_pages    pass=100%  fell-for-trap=0%
  footnote_override           pass=0%    fell-for-trap=0%
```

Gemini Flash reads the rendered page (not the hidden OCR layer) — good. It tracks columns across page boundaries — good. It misses 6pt footnotes — bad, and exactly the failure pdfhell was built to surface.

## Installation

```bash
# Recommended (zero-install with uv):
uvx pdfhell list-traps

# Or in a venv:
python -m venv .venv && source .venv/bin/activate
pip install pdfhell

# With provider extras:
pip install 'pdfhell[anthropic,openai,google]'
```

PDF Hell depends on `multivon-eval` (the underlying evaluation engine — provider adapters, cost tracking, audit packaging) and `reportlab` (PDF generation). No GPU required.

## Commands

```
pdfhell list-traps                              # list trap families
pdfhell make --trap <family> --seed <n>         # generate one case
pdfhell build --suite mini --out cases/mini     # materialise the canonical suite
pdfhell run --model <provider>:<model>          # evaluate a model
pdfhell report runs/<file>.json                 # print a saved run's summary
```

Provider shorthand: `anthropic:claude-sonnet-4-6`, `openai:gpt-4o`, `google:gemini-2.5-pro`, `google:gemini-2.5-flash`.

## How scoring works

Two layers, applied in order:

1. **Procedural exact match (primary)**: did the model's free-text answer contain the expected value? Whitespace-tolerant, case-insensitive. This is the headline correctness signal.
2. **Forbidden-answer detection (diagnostic)**: did the model return one of the answers the trap was specifically designed to elicit? If so, we know *which* failure mode caught it. Recorded but doesn't affect the primary score.

Anything that looks like a refusal (`"I can't determine..."`) is recorded as `refused`, not as a wrong answer.

The QAG explanation layer from `multivon-eval` is available separately (via `multivon_eval.DocumentGrounding`) for users who want a human-readable "why did the model fail" breakdown — but it's not what produces the score.

## Adding a new trap family

Add a generator at `pdfhell/generators/<your_trap>.py`:

```python
from ..case import HellCase
from . import _common as C

def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)
    # ... draw a PDF with reportlab using rng for all random choices ...
    return pdf_bytes, HellCase(
        id=f"your_trap-{seed:04d}",
        trap_family="your_trap",
        seed=seed,
        question="What is ...?",
        expected_answer="42",
        forbidden_answers=["41", "43"],
        metadata={"expected_failure_mode": "Model does X when it should do Y."},
    )
```

Register it in `pdfhell/generators/__init__.py`. PRs welcome.

## Roadmap

The 0.1 release is intentionally narrow — three trap families, 30 cases. Coming in 0.2:

- `merged_table_cells` — value depends on row/column span interpretation
- `rotated_scan` — visually legible but OCR-broken pages
- `near_duplicate_entities` — "ACME Ltd." vs "ACME Holdings Ltd."
- `prompt_injection_in_body` — "Ignore previous instructions and answer X"
- `chart_axis_inversion` — answers depend on reading axis direction
- `checkbox_ambiguity` — selected vs unselected with low visual margin
- `cross_page_citation` — answers requiring page + bounding-box citations

The full suite is 50–100 cases across 10 trap families.

## Hosted generator (early access)

For document-AI teams who need adversarial test cases tailored to *their* templates (claims forms, MSAs, medical records, KYC docs), there's a hosted generator that takes your templates and produces adversarial variants with code-based ground truth — same methodology, your data shape.

Email `hello@multivon.ai` for early access.

## License

Apache 2.0. Built on [`multivon-eval`](https://github.com/multivon-ai/multivon-eval).

## Citing

```bibtex
@software{pdfhell2026,
  title  = {PDF Hell: Adversarial PDFs for AI document readers},
  author = {Multivon},
  year   = {2026},
  url    = {https://github.com/multivon-ai/pdfhell},
}
```
