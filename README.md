# PDF Hell

**Adversarial PDFs that break AI document readers — with procedural ground truth, not LLM-as-judge.**

PDF Hell is a small, sharp benchmark for the "AI reads PDFs" claim. Every test case is a PDF generated *from code*, so the correct answer is known exactly. There's no LLM judging another LLM's interpretation — the same loop that fooled the model isn't asked to grade it.

If your AI claims it can read documents, it should survive PDFs designed to break it.

## Quickstart (30 seconds)

```bash
# 3-case smoke run against the cheapest vision model — works in any env with a Gemini key
export GOOGLE_API_KEY=...
uvx pdfhell run --model google:gemini-2.5-flash --suite smoke

# Or run the full mini suite (30 cases, ~10s on Flash, ~$0.01)
uvx pdfhell run --model anthropic:claude-sonnet-4-6 --suite mini

# Or just generate one trap PDF and open it
uvx pdfhell make --trap hidden_ocr_mismatch --seed 42
open ./cases/hidden_ocr_mismatch-0042.pdf
```

That's it. `pdfhell run` builds the suite on first use, sends each PDF to the vision model, and grades the answer against code-based ground truth.

Smoke result on Gemini 2.5 Flash (one case per family, run this minute):

```
PDF Hell smoke suite — n=3
model: google:gemini-2.5-flash
pass: 3/3  (100.0%)
```

## What's in the mini suite

| Trap family | Cases | What breaks |
|---|---|---|
| `hidden_ocr_mismatch` | 10 | Invoices where the visible amount differs from an invisible OCR text layer. Vision-only models read the page; text-extraction pipelines read the layer; they disagree. |
| `footnote_override` | 10 | Legal clauses where a 6pt footnote overrides the body — liability caps with carve-outs, terminations with restrictions, data-residency with disaster-recovery exceptions. |
| `split_table_across_pages` | 10 | Financial tables where the header row sits on page 1 and the body rows on page 2. RAG loaders that paginate independently lose column context. |

Every case has a deterministic seed. Re-running with the same seed regenerates **byte-identical PDFs** and identical answer keys. `Canvas(invariant=True)` is set on every generator so timestamps and document IDs don't drift between runs.

The full suite (10 trap families, ~50 cases) is on the [roadmap](#roadmap).

## Why this exists

The current AI-eval state of the art uses an LLM-as-judge to grade another LLM's answer. That's circular: the same complexity that fools the agent fools the judge. PDF Hell rejects that:

1. **Code-based ground truth.** The answer is a literal Python value the generator chose, not a frontier model's opinion.
2. **A named failure mode per trap.** When a model fails, we know *which* specific failure caught it (e.g. "trusted the hidden OCR layer over the visible page").
3. **A diagnostic signal**, not just a score. Per-trap-family breakdown tells you which assumption broke.

## Commands

```
pdfhell list-traps                              # list trap families
pdfhell make --trap <family> --seed <n>         # generate one case
pdfhell build --suite <smoke|mini> --out <dir>  # materialise a suite
pdfhell run --model <provider>:<model>          # evaluate a model
  [--suite smoke|mini]                          #   (default: mini)
  [--cases-dir <dir>]                           #   (default: ./cases/<suite>)
  [--out <path>]                                #   JSON output
  [--junit <path>]                              #   JUnit XML for GitHub Actions / GitLab CI
  [--fail-threshold <0.0-1.0>]                  #   non-zero exit if pass_rate below threshold
  [--workers <n>]                               #   parallel API requests (default: 4)
  [--quiet]
pdfhell report runs/<file>.json                 # print a saved run's summary
```

Provider shorthand: `anthropic:claude-sonnet-4-6`, `openai:gpt-4o`, `google:gemini-2.5-pro`, `google:gemini-2.5-flash`, etc. API key from env (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`).

## CI integration

Drop this into `.github/workflows/eval.yml`:

```yaml
name: PDF Hell
on: [pull_request]
jobs:
  pdfhell:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uvx pdfhell run --model anthropic:claude-sonnet-4-6 --suite mini --junit results.xml --fail-threshold 0.7
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - uses: actions/upload-artifact@v4
        with:
          name: pdfhell-results
          path: results.xml
```

JUnit XML renders natively in the GitHub Actions / GitLab CI / CircleCI / Jenkins PR panel — failures show up as red rows with the expected and observed answers in the failure message.

## How scoring works

Two layers, applied in order:

1. **Procedural exact match (primary)** — for single-value traps, the model's free-text answer must contain the expected value (whitespace-tolerant, case-insensitive). For prose traps like `footnote_override`, the model must include every required token (the cap value, every carve-out section number, etc.) in any order, in any phrasing. The model isn't graded on prose style; it's graded on whether it captured the facts.
2. **Forbidden-answer detection (diagnostic)** — did the model return one of the answers the trap was specifically designed to elicit (e.g. the hidden-OCR amount)? If so, the trap caught a *known* failure mode and we record it. Doesn't affect the primary score.

Anything that looks like a refusal (`"I can't determine..."`) is recorded as `refused`, not as a wrong answer.

The QAG explanation layer from `multivon-eval` (`DocumentGrounding`) is available separately for users who want a human-readable "why did the model fail" breakdown — but it's never on the scoring path.

## Adding a new trap family

Add a generator at `pdfhell/generators/<your_trap>.py`:

```python
from ..case import HellCase
from . import _common as C

def generate(seed: int) -> tuple[bytes, HellCase]:
    rng = C.rng_for(seed)
    # ... draw a PDF with reportlab using rng for all random choices ...
    # invariant=True is the default — keep your generator deterministic.
    return pdf_bytes, HellCase(
        id=f"your_trap-{seed:04d}",
        trap_family="your_trap",
        seed=seed,
        question="What is ...?",
        expected_answer="42",                # single canonical answer
        expected_tokens=["42"],              # OR list of required substrings for prose
        forbidden_answers=["41", "43"],      # OR a value the trap specifically elicits
        metadata={"expected_failure_mode": "Model does X when it should do Y."},
    )
```

Register it in `pdfhell/generators/__init__.py`. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full guide. Tests run with `pytest`.

## Roadmap

The 0.1 release is intentionally narrow — three trap families, 30 cases. Coming next:

- `merged_table_cells` — value depends on row/column span interpretation
- `rotated_scan` — visually legible but OCR-broken pages
- `near_duplicate_entities` — "ACME Ltd." vs "ACME Holdings Ltd."
- `prompt_injection_in_body` — "Ignore previous instructions and answer X"
- `chart_axis_inversion` — answers depend on reading axis direction
- `checkbox_ambiguity` — selected vs unselected with low visual margin
- `cross_page_citation` — answers requiring page + bounding-box citations

Target full suite: 10 trap families, ~50 cases.

## Hosted generator

For document-AI teams who need adversarial test cases tailored to *their* templates (claims forms, MSAs, medical records, KYC docs), there's a hosted generator that takes your templates and produces adversarial variants with code-based ground truth — same methodology, your data shape.

Email `hello@multivon.ai` for early access, or see [multivon.ai/pricing](https://multivon.ai/pricing).

## Installing

```bash
# Recommended (zero-install with uv):
uvx pdfhell list-traps

# Or in a venv:
python -m venv .venv && source .venv/bin/activate
pip install pdfhell
```

Bare install brings in `multivon-eval` (the engine), `reportlab` (PDF generation), `pypdf`, and the three frontier-provider SDKs (anthropic, openai, google-genai). No provider extras to remember; no GPU required.

## License

Apache 2.0. Built on [`multivon-eval`](https://github.com/multivon-ai/multivon-eval).

## Citing

```bibtex
@software{pdfhell,
  title  = {PDF Hell: Adversarial PDFs for AI document readers},
  author = {Multivon},
  url    = {https://github.com/multivon-ai/pdfhell},
}
```
