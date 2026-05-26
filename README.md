# PDF Hell

[![PyPI](https://img.shields.io/pypi/v/pdfhell.svg)](https://pypi.org/project/pdfhell)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://pypi.org/project/pdfhell)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Downloads](https://static.pepy.tech/badge/pdfhell/month)](https://pepy.tech/project/pdfhell)

**[Live leaderboard](https://multivon.ai/leaderboard)** · [Website](https://multivon.ai/pdfhell) · [PyPI](https://pypi.org/project/pdfhell) · [multivon-eval (engine)](https://github.com/multivon-ai/multivon-eval)

**Adversarial PDFs that stress-test AI document readers — with procedural ground truth, not LLM-as-judge.**

PDF Hell is a small, focused benchmark for three specific failure modes in AI document pipelines. Every test case is a PDF generated *from code*, so the correct answer is known exactly. There's no LLM judging another LLM's interpretation — the same complexity that fools the model isn't asked to grade it.

## The headline finding (mini-v4-sample, 2026-05-24)

> **⚠ Retraction notice — 2026-05-24:** earlier versions of this README, the 0.4.0 / 0.5.0 release notes, and the original `CONFIRMATION_REPORT.md` claimed Claude Opus 4-7 fails 0% on all seven mini-v4 trap families. **That claim was an eval artifact** — every Opus call had failed with a `temperature deprecated` API error that the runner silently scored as "wrong answer". Full retraction and corrected numbers in [`pdfhell/research/CORRECTION_NOTICE.md`](pdfhell/research/CORRECTION_NOTICE.md). The corrected leaderboard is below.

| Model | Overall (mini-v4-sample, n=170) | Notable per-trap weakness |
|---|---:|---|
| `openai:gpt-5` | **94.7%** | — |
| `anthropic:claude-haiku-4-5` | 91.2% | — |
| `google:gemini-flash-lite-latest` | 88.8% | 0% on `zero_width_space_split` |
| `openai:gpt-4o` | 81.2% | **0% on `hidden_ocr_mismatch`** (v1 finding holds) |
| `anthropic:claude-opus-4-7` | 79.4% | **0% on `scale_dependent_rendering` + `zero_width_space_split`** |
| `google:gemini-2.5-pro` | 67.1% | 0% on `mirror_image_glyphs`, `mirrored_footer_notice`, `shaded_box_binding_rule` |
| `anthropic:claude-sonnet-4-6` | 60.6% | 0% on 6 traps including `mirror_image_glyphs`, `upside_down_amount`, `color_grounding_trap` |
| `google:gemini-2.5-flash` | 59.4% | 0% on `mirror_image_glyphs`, `em_dash_minus_sign`, `mirrored_footer_notice` |

**Two real, narrower findings that survive correction:**

1. **GPT-4o blind spot on hidden OCR.** Falls for `hidden_ocr_mismatch` 10/10. GPT-5 fixed most of it (80% pass). Mini-v1 finding from 0.1.0 still holds.

2. **Anthropic premium + reasoning tier fail `scale_dependent_rendering` 0%.** Opus 4-7 and Sonnet 4-6 both miss the 3.5pt-footnote trap entirely. Haiku 4-5 passes 90%, GPT-5 100%. Mini-v2 finding from 0.2.0 — narrower than the originally-claimed "all 7 v4 traps", but real and replicated.

**The aggregate surprise:** Sonnet 4-6 (60.6%) underperforms Haiku 4-5 (91.2%) by 31 points on this suite. Same provider, mid-tier model is weakest — both the cheap and the premium tiers beat it.

## Quickstart (30 seconds)

```bash
# Quickest: 3-case smoke against the cheapest vision model
export GOOGLE_API_KEY=...
uvx pdfhell run --model google:gemini-2.5-flash --suite smoke

# Headline-reproducing: watch Opus 4-7 fall apart on mini-v4 (~$30, ~10 min)
uvx pdfhell run --model anthropic:claude-opus-4-7 --suite mini-v4

# Or run your own autoresearch loop to discover new traps
pip install 'pdfhell[research]'
python -m pdfhell.research.loop --budget 50 --max-candidates 200

# Inspect a single agent-discovered trap PDF
uvx pdfhell make --trap unicode_confusable_total --seed 7001
open ./cases/unicode_confusable_total-7001.pdf
```

`pdfhell run` builds the suite on first use, sends each PDF to the vision model, and grades the answer against code-based ground truth — no LLM judging another LLM.

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
- ✅ GPT-4o falls for the hidden-OCR trap 100% of cases (CI [72%, 100%]).
- ✅ GPT-5.4 fixes most of it (80% pass on hidden OCR).
- ❌ "Claude leads" — Sonnet's CI [83%, 99%] overlaps with Gemini's [78%, 98%]. Statistically indistinguishable on n=30.

Suite hash: `8ad87b8d` (mini-v1). Raw run JSON at <https://github.com/multivon-ai/multivon-web/tree/main/public/data/pdfhell-runs>.

## Mini-v4: 17 trap families, 510 cases — the current frontier

`mini-v4` extends `mini-v1` (3 families) and `mini-v2` (3 more frontier-targeting families) with **11 trap families autoresearched and validated by `pdfhell.research`** — 4 from mini-v3 and 7 from mini-v4. All 11 were proposed by a rotation of three strong reasoning models (Opus 4-7, GPT-5, Gemini 2.5 Pro), passed five validation gates, and survived fresh-seed re-evaluation. Total discovery + validation spend: **$89**.

Run it: `uvx pdfhell run --model anthropic:claude-opus-4-7 --suite mini-v4`. Live leaderboard: <https://multivon.ai/leaderboard>.

**Key findings on mini-v4:**

- ✅ **Opus 4-7 blind spot.** Combined n ≈ 280 Opus calls across 7 v4 traps, zero successes. P(under H₀ with 5% true pass) ≈ 5×10⁻⁷. Validated independently — see [`CONFIRMATION_REPORT.md`](pdfhell/research/CONFIRMATION_REPORT.md).
- ✅ **Premium tier is not universally better.** Haiku 4-5 (cheapest Anthropic model) beats Opus 4-7 (most expensive) on 6 of 7 v4 traps.
- ✅ **Convergent signal across researchers.** Opus, GPT-5, and Gemini 2.5 Pro independently proposed traps that catch Opus — not a single-model artifact.
- ❌ "Opus is bad" — false. Opus is excellent at many things. It has a specific failure mode on multi-step procedural rules embedded in PDF documents.

Full audit trail in [`pdfhell/research/`](pdfhell/research/) — `results.tsv` (every candidate proposed), `keep/*.json` (every survivor with code), `budget.jsonl` (every cent), `METHODOLOGY.md`, `CONFIRMATION_REPORT.md`.

## How traps get discovered

pdfhell ships with an autoresearch loop ([`pdfhell.research`](pdfhell/research/README.md)) inspired by Karpathy's [`autoresearch`](https://github.com/karpathy/autoresearch). Instead of minimising a training loss, the loop maximises **cross-model discrimination**:

```
score = (pass_max - pass_min) × novelty   if pass_max >= 0.7   else 0
```

A *useful* trap is one where the best model can do it ≥70% of the time and the worst model can't — gated by novelty against existing keepers so we don't keep redundant discriminators. Three strong reasoning models (Opus 4-7, GPT-5, Gemini 2.5 Pro) rotate as the researcher; every proposal passes five validation gates (parseable, deterministic, answerable, forbidden-clean, lint-clean) before any vision-eval spend.

Two overnight runs ($43.97 + ~$0.62 + $45 confirmation = **$89 total**) produced 11 surviving trap families. The agent does not get to merge its own work — every kept candidate sits in `keep/` until a human curator promotes it. See [`METHODOLOGY.md`](pdfhell/research/METHODOLOGY.md) for the formal write-up, [`CONFIRMATION_REPORT.md`](pdfhell/research/CONFIRMATION_REPORT.md) for the validation pass.

```bash
pip install 'pdfhell[research]>=0.5.0'
python -m pdfhell.research.loop --budget 50 --max-candidates 200
python -m pdfhell.research.report                      # see what was discovered
python -m pdfhell.research.curate --promotion-plan     # propose merge to next mini-vN
```

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
pdfhell list-traps                              # list the 17 trap families
pdfhell discover [--compact]                    # emit capability catalog as JSON (for agents)
pdfhell make --trap <family> --seed <n>         # generate one case (pdf + json)
pdfhell build --suite <name> [--out <dir>]      # materialise a suite (default out: ./cases/<suite>)
pdfhell run --model <provider>:<model>          # evaluate a model
  [--suite smoke|mini|mini-v2|mini-v3|mini-v4|mini-v4-sample]  # (default: mini)
  [--cases-dir <dir>]                           #   (default: ./cases/<suite>; built on demand)
  [--out <path>]                                #   JSON output (default: runs/<suite>-<model>.json)
  [--junit <path>]                              #   JUnit XML for GitHub Actions / GitLab CI
  [--audit-pack <path>]                         #   hash-chained audit ZIP (PDFs + keys + manifest)
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

The current frontier suite is `mini-v4` — **17 trap families, 510 cases**, 11 of them autoresearched and human-curated (see above). Candidate families on deck, not yet validated into a suite:

- `merged_table_cells` — value depends on row/column span interpretation
- `rotated_scan` — visually legible but OCR-broken pages
- `near_duplicate_entities` — "ACME Ltd." vs "ACME Holdings Ltd."
- `prompt_injection_in_body` — "Ignore previous instructions and answer X"
- `chart_axis_inversion` — answers depend on reading axis direction
- `checkbox_ambiguity` — selected vs unselected with low visual margin
- `cross_page_citation` — answers requiring page + bounding-box citations

Each runs through the same five validation gates as the autoresearched families before promotion into a `mini-vN` suite. File an issue to prioritize one.

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

## The Multivon ecosystem

Five public + one early-access package, all built on a shared evaluation engine:

| Repo | What it is |
|---|---|
| [multivon-eval](https://github.com/multivon-ai/multivon-eval) | Python SDK — 44 evaluators + `bootstrap` CLI + `multivon_eval.auto`. PDF Hell's engine. |
| **pdfhell** (you are here) | Adversarial PDFs that break AI document readers |
| [multivon-mcp](https://github.com/multivon-ai/multivon-mcp) | MCP server — exposes `pdfhell_run` + `pdfhell_make` as tools to Claude / Cursor |
| [eval-action](https://github.com/multivon-ai/eval-action) | GitHub Action — runs pdfhell + multivon-eval on every PR |
| [eval-framework-benchmark](https://github.com/multivon-ai/eval-framework-benchmark) | Reproducible head-to-head vs DeepEval + RAGAS (text eval, not PDFs) |
| multivon-guard *(early access)* | Local proxy that catches LLM coding agents leaking secrets / PII |

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
