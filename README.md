# PDF Hell

**Adversarial PDFs that stress-test AI document readers — with procedural ground truth, not LLM-as-judge.**

PDF Hell is a small, focused benchmark for three specific failure modes in AI document pipelines. Every test case is a PDF generated *from code*, so the correct answer is known exactly. There's no LLM judging another LLM's interpretation — the same complexity that fools the model isn't asked to grade it.

## The headline finding (mini-v1, 30 cases, 2026-05-17)

GPT-4o falls for the hidden-OCR trap on **10 out of 10 cases (95% Wilson CI [72%, 100%])** — it consistently returns the *invisible* amount from the PDF's text layer instead of the *visible* amount rendered on the page:

```
Trap: hidden_ocr_mismatch (invoice — visible total $12,345.67, hidden OCR total $22,345.67)
Question: What is the TOTAL AMOUNT DUE?

→ openai:gpt-4o            $22,345.67   ← fell for trap (10/10 in this trap family)
→ openai:gpt-5.4-mini      $22,345.67   ← fell for trap (9/10)
→ openai:gpt-5.4           $12,345.67   ← correct (8/10 across trap)
→ google:gemini-2.5-flash  $12,345.67   ← correct (10/10)
→ anthropic:claude-sonnet-4-6  $12,345.67   ← correct (10/10)
```

The visible page, the hidden text layer, and an agent that fuses both will give three different answers. pdfhell exists to catch that.

## Quickstart (30 seconds)

```bash
# 3-case smoke run against the cheapest vision model
export GOOGLE_API_KEY=...
uvx pdfhell run --model google:gemini-2.5-flash --suite smoke

# Or the full mini-v1 suite (30 cases, ~10s on Flash, ~$0.01)
uvx pdfhell run --model anthropic:claude-sonnet-4-6 --suite mini

# Or generate one trap PDF and inspect it
uvx pdfhell make --trap hidden_ocr_mismatch --seed 42
open ./cases/hidden_ocr_mismatch-0042.pdf
```

`pdfhell run` builds the suite on first use, sends each PDF to the vision model, and grades the answer against code-based ground truth.

## Mini-v1 leaderboard (8 models, 30 cases)

| Model | Pass rate | 95% CI | Hidden OCR | Footnote | Split table |
|---|---:|---:|---:|---:|---:|
| `anthropic:claude-sonnet-4-6` | 29/30 (97%) | [83%, 99%] | 10/10 | 9/10 | 10/10 |
| `google:gemini-3.1-pro-preview` | 28/30 (93%) | [78%, 98%] | 10/10 | 8/10 | 10/10 |
| `google:gemini-3.1-flash-lite` | 28/30 (93%) | [78%, 98%] | 10/10 | 8/10 | 10/10 |
| `google:gemini-2.5-pro` | 28/30 (93%) | [78%, 98%] | 10/10 | 8/10 | 10/10 |
| `google:gemini-2.5-flash` | 28/30 (93%) | [78%, 98%] | 10/10 | 8/10 | 10/10 |
| `openai:gpt-5.4` | 27/30 (90%) | [74%, 97%] | 8/10 | 9/10 | 10/10 |
| `openai:gpt-5.4-mini` | 20/30 (67%) | [49%, 81%] | 1/10 | 9/10 | 10/10 |
| `openai:gpt-4o` | 14/30 (47%) | [30%, 64%] | **0/10** | 8/10 | 6/10 |

**What is and isn't supported by this data:**

- ✅ GPT-4o is materially worse than the others on this suite — its CI [30%, 64%] does not overlap with any other model's.
- ✅ GPT-4o falls for the hidden-OCR trap 100% of cases (CI [72%, 100%]). Every failure returned the hidden-OCR amount specifically.
- ✅ GPT-5.4 fixes most of it (80% pass on hidden OCR) — a real generational improvement.
- ❌ "Claude leads" — Sonnet's CI [83%, 99%] overlaps with Gemini's [78%, 98%]. The two are statistically indistinguishable on this suite. Don't read ordinal rankings from 30 cases.
- ❌ "PDF Hell is sufficient to evaluate document AI." It's a stress test for three specific failure modes. Pair it with a domain benchmark (DocVQA, your own regression suite) for coverage.

Suite hash: `8ad87b8d` (mini-v1, 30 cases). Every leaderboard row above was measured on the same hash. Raw run JSON at <https://github.com/multivon-ai/multivon-web/tree/main/public/data/pdfhell-runs>.

## What's in mini-v1

| Trap family | Cases | What breaks |
|---|---|---|
| `hidden_ocr_mismatch` | 10 | Invoices where the visible amount differs from an invisible OCR text layer. Vision-only models read the page; text-extraction pipelines read the layer; they disagree. |
| `footnote_override` | 10 | Legal clauses where a 6pt footnote overrides the body — liability caps with carve-outs, terminations with restrictions, data-residency with disaster-recovery exceptions. |
| `split_table_across_pages` | 10 | Financial tables where the header row sits on page 1 and the body rows on page 2. RAG loaders that paginate independently lose column context. |

Every case has a deterministic seed. Re-running with the same seed regenerates **byte-identical PDFs** and identical answer keys (`Canvas(invariant=True)` on every generator).

**Suite versioning.** The `mini-v1` label + suite hash (`8ad87b8d`) fingerprints the exact (trap_family, seed) pairs measured. Adding a new trap family produces `mini-v2` with a different hash — runs across different hashes are not directly comparable. See the next section for the roadmap.

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

Email `hello@multivon.ai` for early access, or see [multivon.ai/commercial](https://multivon.ai/commercial).

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
