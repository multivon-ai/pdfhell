# pdfhell 0.4.0 (draft — TODO: replace with actual numbers after curation)

## mini-v3: agent-discovered trap families

**The first pdfhell release where the new trap families were discovered by an autoresearch loop rather than hand-authored.**

The `pdfhell.research` loop ran a $XX overnight session across XX candidates from three rotating researchers (Opus 4-7, GPT-5, Gemini 2.5 Pro), gating each through five validation checks (parseable, deterministic, answerable, forbidden-clean, lint-clean) before any expensive vision-eval spend. After human curator review and confirmation re-runs, **N new trap families** are promoted into `mini-v3`:

### `unicode_confusable_total` *(score 1.00, by Opus 4-7)*

Two visually-identical "TOTAL" rows differ only by ASCII "O" vs Cyrillic capital "О" (U+041E). A printed disambiguation clause names which codepoint is binding.

| Model | Pass |
|---|---:|
| `openai:gpt-5` | 100% |
| `anthropic:claude-haiku-4-5` | 93% |
| `google:gemini-2.5-flash` | 87% |
| `openai:gpt-4o` | 80% |
| `google:gemini-2.5-pro` | 67% |
| `anthropic:claude-sonnet-4-6` | 60% |
| `anthropic:claude-opus-4-7` | **0%** |
| `google:gemini-flash-lite-latest` | **0%** |

**Why this matters:** Anthropic's premium model (Opus 4-7) fails 0/15, Anthropic's cheapest (Haiku 4-5) passes 14/15. Premium tier is not universally better at PDF reading.

### `zero_width_space_split` *(score 0.05, by Gemini 2.5 Pro)*

The binding total contains a U+200B ZWSP character in the text layer, fragmenting it into smaller decoy substrings. Visually the number renders correctly; text-anchored pipelines parse the fragments and fall back to a smaller decoy.

| Model | Pass |
|---|---:|
| `anthropic:claude-haiku-4-5` | 80% |
| `google:gemini-2.5-flash` | 70% |
| `openai:gpt-5` | 55% |
| `openai:gpt-4o` | 50% |
| `google:gemini-2.5-pro` | 50% |
| `anthropic:claude-sonnet-4-6` | **0%** |
| `anthropic:claude-opus-4-7` | **0%** |
| `google:gemini-flash-lite-latest` | **0%** |

**Why this matters:** Three models at 0%. Catches Sonnet 4-6 (which passes the unicode trap at 60%) — different blind spot, complementary coverage.

### `mirrored_footer_notice` *(score 0.17, by GPT-5)*

The binding amount appears only in a horizontally-mirrored footer notice. Vision-only OCR pipelines that don't internally un-mirror text miss the binding clause and fall back to the visible (non-binding) headline.

### `currency_mismatch_conversion` *(score 0.02, by GPT-5)*

The invoice headlines a EUR total; a settlement clause requires USD payment at a stated FX rate. Models that grab the salient number without applying the conversion fail.

## Methodology

All four traps were:
1. Proposed by a single LLM call (different researcher each turn)
2. Filtered through five gates (no human authorship of the source code)
3. Evaluated on a fixed 8-model panel
4. Human-curated for promotion (this release): confirmation re-runs with fresh seeds, max per-model delta ≤ 20% required

The full audit trail is at [`pdfhell/research/`](pdfhell/research/):
- `results.tsv` — every candidate ever proposed (XX rows)
- `keep/*.json` — survivors with code + per-model results
- `budget.jsonl` — every dollar spent
- `METHODOLOGY.md` — formal write-up

## What's `mini-v3`

`mini-v3` is `mini-v2` (180 cases, 6 families × 30) plus the N new agent-discovered families × 30 seeds each = **XXX cases**. `mini-v1` and `mini-v2` `suite_hash` are unchanged — existing leaderboard rows remain comparable.

```bash
uvx pdfhell run --model anthropic:claude-sonnet-4-6 --suite mini-v3
```

## Reproducing the research run

```bash
pip install 'pdfhell[research]>=0.4.0'
export ANTHROPIC_API_KEY=...  OPENAI_API_KEY=...  GOOGLE_API_KEY=...
python -m pdfhell.research.loop --budget 50 --max-candidates 200
```

The `pdfhell.research` module ships with the package; running your own overnight loop produces a separate `results.tsv` + `keep/` audit trail that you can publish or critique.

## Other changes

- `pdfhell.research.report` — CLI for summarising a research run
- `pdfhell.research.curate` — CLI for the human-curator workflow (verify, preview, confirm, promotion-plan)
- 43 new unit tests for the research module (`pytest tests/test_research_*.py`)
- Parseable gate now falls back to pdfplumber if pypdf rejects a valid PDF (catches reportlab annotation quirks)
- Smarter loose-equality in answerable gate: `$18,400` matches `$18,400.00`, handles currency-symbol variants
- Researcher prompt now includes top kept candidates as positive examples (calibration)
- Fixed a leftover `import random` in `hidden_ocr_mismatch.py`
