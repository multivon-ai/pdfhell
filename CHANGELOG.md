# Changelog

All notable changes to pdfhell. Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.2] — 2026-05-24

Architectural cleanup: vision dispatch moves upstream to `multivon-eval>=0.9.1`. No behaviour change — every `pdfhell.vision.*` import still resolves, just to the upstream implementation now. The Opus temperature fix, the `ollama:` provider, and the per-provider content-block handling are all shared with any other multivon-eval consumer that needs to grade documents or images.

### Changed

- **`pdfhell.vision`** is now a ~30-line shim that re-exports `call_vision`, `JudgeUnavailable`, and the private helpers from `multivon_eval.vision`. The implementation lives at <https://github.com/multivon-ai/multivon-eval/blob/main/multivon_eval/vision.py> as of multivon-eval 0.9.1. Downstream code importing from `pdfhell.vision` continues to work without changes.
- **`pdfhell.runner`** still constructs a duck-typed `_OllamaConfig` for the `ollama:` provider, since multivon-eval's `JudgeConfig` validation now also accepts `ollama` — either approach works.

### Why

Three pieces of plumbing were duplicated between pdfhell and multivon-eval — Anthropic adapter code, the Opus temperature-deprecation handling, and the model-pricing tables. The cleanup avoids the next class of "I fixed it on one side and forgot the other" silent bug.

### Compatibility

- Bumps `multivon-eval` dep from `>=0.7.2` to `>=0.9.1`.
- All `suite_hash` values, CLI commands, audit-pack format unchanged.
- 133/133 unit tests pass. Smoke-tested both `anthropic:claude-opus-4-7` and `ollama:gemma3:4b` end-to-end through the new shim.

## [0.5.1] — 2026-05-24

### Retraction — Opus 4-7 "blind spot" finding from 0.4.0 / 0.5.0

**The headline finding promoted in 0.4.0 and 0.5.0 — that Claude Opus 4-7 fails 0% on every mini-v3 and mini-v4 trap family — was an evaluation artifact, not a real model failure.** Full details in [`pdfhell/research/CORRECTION_NOTICE.md`](pdfhell/research/CORRECTION_NOTICE.md).

What happened: `pdfhell/vision.py` was passing `temperature=0.0` to `client.messages.create()` for every Anthropic model. The reasoning-tier Opus 4-7 rejects that parameter with a 400. The runner caught the exception, returned its string repr as the "model output", and the scorer dutifully recorded every case as `pass=0%, fell-for-trap=0%, refused=0%` — outwardly indistinguishable from a model that confidently produced a wrong, non-trap answer. The same root cause silently broke `gemini-flash-lite-latest` (gated out of the vision-capable allowlist), which is why both models reported 0% across the entire suite.

**What survives:**

- **`scale_dependent_rendering`** (mini-v2, 3.5pt footnote): Opus 4-7 + Sonnet 4-6 both 0/10. Real, replicates after the fix.
- **`zero_width_space_split`** (mini-v3): Opus 4-7 + Sonnet 4-6 + Gemini-Flash-Lite 0/10. Real, replicates after the fix.
- **`hidden_ocr_mismatch`** (mini-v1): GPT-4o still 0/10. Real, replicates after the fix.
- **Sonnet 4-6 underperforms Haiku 4-5 by 31 points** on mini-v4-sample (60.6% vs 91.2%). Real, replicates after the fix. The Anthropic-internal anomaly is the mid-tier model, not the premium one.

**What's retracted:**

- The "Opus 4-7 systematic blind spot across all 7 mini-v4 trap families" headline (and the corresponding 7-row failure table) is withdrawn.
- The "P under H₀ ≈ 5×10⁻⁷" calibration is withdrawn — Opus genuinely fails only 2 of the 7 v4 traps.
- The original `CONFIRMATION_REPORT.md` is superseded; preserved in git history at `a325ef3` for transparency.

### Fixes

- **`pdfhell.vision._anthropic_call`**: omits `temperature` for `claude-opus-4-7` and `claude-opus-5+`. Older Anthropic models still receive it.
- **`pdfhell.vision._VISION_CAPABLE`**: added `gemini-flash` and `gemini-flash-lite` family prefixes to the Google allowlist.

### Observability additions (so this can't silently happen again)

- **`pdfhell.scorer.CaseScore.api_error`**: new boolean distinguishing "provider call failed" from "model gave wrong answer".
- **`pdfhell.scorer.SuiteReport.api_error_rate`**: new aggregate field. Serialised into every run JSON.
- **`pdfhell.cli._print_report`**: prints a loud `⚠` warning + the first error message verbatim + "the pass rate above is unreliable" when `api_error_rate >= 10%`. Same warning would have caught this bug on day one.

### Added — local-HF provider via ollama

- **`ollama:` provider in `pdfhell.runner`**: routes through ollama's native `/api/chat` at `127.0.0.1:11434`. Supports `llama3.2-vision`, `gemma3`, `qwen2.5vl`, `minicpm-v`, `llava`, `moondream` (anything in ollama's vision-capable library). PDFs are rasterised to PNG via `pypdfium2` before sending.
- First local-model leaderboard rows land alongside the cloud models — see the regenerated [leaderboard](https://multivon.ai/leaderboard).

### Compatibility

- All `suite_hash` values unchanged. All four prior leaderboards (mini-v1, v2, v3, v4) remain valid suite specs; the only thing that changed is the published *numbers* for Opus 4-7 and Gemini-Flash-Lite, which are now derived from a runner that doesn't error out on those models.
- No breaking changes to the CLI, output JSON schema, or audit-pack format. New fields (`api_error_rate`, `api_error` per case) are additive.

## [0.5.0] — 2026-05-23

### Added — `mini-v4`: seven more agent-discovered traps + an emergent finding

The second autoresearch loop ran $43.97 / 115 candidates / ~3 hours wall clock and produced **seven additional trap families** (on top of mini-v3's four). All proposed by the same Opus 4-7 / GPT-5 / Gemini 2.5 Pro rotation; all passed the five validation gates; all defeat at least one model on the 8-model panel at 0%.

### The emergent finding

**Claude Opus 4-7 fails 0% on every single one of the seven new traps.** Haiku 4-5 — Anthropic's cheapest model — passes 100% on most of them.

| Trap | Opus 4-7 | Sonnet 4-6 | Haiku 4-5 |
|---|---:|---:|---:|
| `em_dash_minus_sign` | **0%** | 5% | 40% |
| `upside_down_amount` | **0%** | 0% | 100% |
| `checksum_validation_rule` | **0%** | 70% | 35% |
| `mirror_image_glyphs` | **0%** | 0% | 75% |
| `boldface_binding_rule` | **0%** | 100% | 100% |
| `shaded_box_binding_rule` | **0%** | 95% | 100% |
| `color_grounding_trap` | **0%** | 10% | 100% |

This is not noise — seven independently-proposed traps, three different researcher models, three different mechanism categories (typographic confusables, geometric transforms, rule-following), all converge on the same pattern. The premium Anthropic vision model has a systematic blind spot the cheaper sibling does not share. *Provisional hypothesis: Opus's longer thinking pass under-weights "follow the printed rule" instructions in favour of salience-driven extraction.* Worth deeper investigation.

### The seven new families

- **`em_dash_minus_sign`** (Opus 4-7) — em/en-dash (—, –) used where minus would be; a printed clause names which dash glyph binds. Anthropic-wide failure; OpenAI + Gemini-Pro fine.
- **`upside_down_amount`** (Opus 4-7) — 180-degree rotated binding amount in a labelled box. Opus + Sonnet + Lite all 0%; Haiku 100%.
- **`checksum_validation_rule`** (Opus 4-7) — printed rule says "pick the candidate whose digit-sum mod K equals N". Tests rule-following vs salience. Opus + Lite + GPT-4o all weak.
- **`mirror_image_glyphs`** (Opus 4-7) — horizontally mirrored glyphs in the binding amount. **5/8 models at 0%** — only OpenAI passes cleanly.
- **`boldface_binding_rule`** (GPT-5) — printed rule: "use the boldface amount". Visual property + rule. Opus + Lite at 0%.
- **`shaded_box_binding_rule`** (GPT-5) — printed rule: "use the amount in the shaded box". Layout property + rule. Opus 0%, rest 95-100%.
- **`color_grounding_trap`** (Gemini 2.5 Pro) — printed rule: "use the red amount". Visual semantic grounding. Opus 0%, broad Anthropic + Gemini struggle.

### `mini-v4` suite

`mini-v4` = `mini-v3` (10 families × 30 = 300 cases) + 7 new families × 30 = **510 cases total**. `mini-v1`, `mini-v2`, `mini-v3` `suite_hash` are unchanged — historical leaderboard rows remain comparable.

```bash
uvx pdfhell run --model anthropic:claude-opus-4-7 --suite mini-v4
```

### Research artifacts

Full audit trail at [`pdfhell/research/`](pdfhell/research/):
- `results.tsv` — 115 candidates explored (43 in this loop run + 72 prior)
- `keep/*.json` — all 11 survivors with code + per-model results + researcher rationale
- `budget.jsonl` — $43.97 in committed spend, every API call accounted for
- `METHODOLOGY.md` — formal methodology write-up

### Compatibility

- All prior `suite_hash` unchanged
- All CLI commands, output schemas, audit-pack format unchanged
- `pdfhell.runner`, `pdfhell.scorer`, `pdfhell.case` unchanged

## [0.4.0] — 2026-05-23

### Added — `mini-v3`: agent-discovered trap families

**The first pdfhell release where the new trap families were discovered by an autoresearch loop, not hand-authored.** All four are proposals from the rotation of three strong reasoning models (Opus 4-7, GPT-5, Gemini 2.5 Pro) running through [`pdfhell.research`](pdfhell/research/), filtered through five validation gates, and confirmed via panel evaluation across 8 models:

- **`unicode_confusable_total`** (proposed by **Claude Opus 4-7**) — Two visually-identical "TOTAL" rows. One uses ASCII "O", the other uses Cyrillic capital "О" (U+041E). A printed disambiguation clause names which codepoint is binding. Opus 4-7 fails 0/15 of its own trap. Haiku 4-5 passes 14/15. **The premium tier is not universally better at PDF reading.**

- **`zero_width_space_split`** (proposed by **Gemini 2.5 Pro**) — The binding total contains a U+200B zero-width space in the text layer, fragmenting it into smaller decoy substrings. Visually correct, but text-anchored pipelines parse the fragments. Defeats Sonnet 4-6, Opus 4-7, and Gemini-Flash-Lite at 0% each — three models at 0%, three different providers.

- **`currency_mismatch_conversion`** (proposed by **GPT-5**) — Invoice headlines a EUR total; a settlement clause requires USD payment at a stated FX rate. Models that grab the salient number without applying the conversion answer the EUR amount. Catches Opus 4-7 and Gemini-Flash-Lite.

- **`mirrored_footer_notice`** (proposed by **GPT-5**) — The binding amount appears only in a horizontally-mirrored footer notice. Vision-only OCR pipelines that don't internally un-mirror text fall back to the visible (non-binding) headline.

### Methodology

All four traps were:
1. Proposed by a single LLM call (different researcher each turn — rotation prevents single-model bias)
2. Filtered through five gates (parseable, deterministic, answerable, forbidden-clean, lint-clean)
3. Evaluated on a fixed 8-model panel (probe round + full round)
4. Promoted via human curation after eyeball + consistency check

Full audit trail in [`pdfhell/research/`](pdfhell/research/):
- `results.tsv` — every candidate ever proposed (40+ rows)
- `keep/*.json` — survivors with code + per-model results + researcher rationale
- `budget.jsonl` — every dollar spent
- `METHODOLOGY.md` — formal write-up of the methodology

### `mini-v3` suite

`mini-v3` = `mini-v2` (180 cases, 6 families × 30) + 4 new agent-discovered families × 30 seeds = **300 cases total**. `mini-v1` and `mini-v2` `suite_hash` are unchanged — historical leaderboard rows remain comparable.

```bash
uvx pdfhell run --model anthropic:claude-sonnet-4-6 --suite mini-v3
```

### Other improvements

- **`pdfhell.research.report`** — CLI summarising a research run (status counts, gate-fail breakdown, spend by researcher, theme convergence, keepers ranked)
- **`pdfhell.research.curate`** — Human-curator workflow (`--verify`, `--preview`, `--confirm`, `--confirm-all`, `--promotion-plan`)
- **`pdfhell.research.__main__`** — `python -m pdfhell.research` lists commands
- **43 unit tests for the research module** — `pytest tests/test_research_*.py`, all run in <0.5s with no API calls
- **Parseable gate** falls back to pdfplumber if pypdf rejects (catches reportlab annotation quirks)
- **Loose-equality fix** in answerable gate: `$18,400` correctly matches `$18,400.00`, handles currency-symbol variants, FX precision
- **Researcher prompt** includes top kept candidates as positive examples for calibration
- **Session dedupe** — agents can't re-propose the same trap_family name twice in one session
- **`flush=True`** on all loop prints — overnight runs are observable in real time
- **Fixed** an unused `import random` in `hidden_ocr_mismatch.py` (caught by the new ruff-clean check)

### Compatibility

- `mini-v1` and `mini-v2` `suite_hash` unchanged
- All existing CLI commands, output JSON schemas, audit-pack format unchanged
- `pdfhell.runner`, `pdfhell.scorer`, `pdfhell.case` unchanged — the research loop is read-only with respect to runtime contracts

## [0.3.0] — 2026-05-23

### Added — `pdfhell.research`: autoresearch-style discovery loop

A new subpackage that **discovers new adversarial PDF traps automatically**
by optimising for cross-model discrimination. Inspired by Karpathy's
[`autoresearch`](https://github.com/karpathy/autoresearch); same pattern,
ported from "minimise nanochat val_bpb" to "maximise pass-rate spread
across the eval panel."

```
propose → validate → probe (2 models) → full (8 models) → keep/revert
```

Three strong reasoning models rotate as the researcher:
`claude-opus-4-7`, `gpt-5`, `gemini-2.5-pro`. Each proposes one
candidate generator (full Python source) per turn. Candidates pass
through five validation gates (parseable, deterministic, answerable,
forbidden-clean, lint-clean) before any vision API spend is committed.

### First agent-discovered trap: `unicode_confusable_total`

The very first overnight run (10 candidates, $7 spend) produced
`unicode_confusable_total` — an invoice with two visually-identical
"TOTAL" rows where one label uses ASCII Latin "O" and the other uses
Cyrillic capital "О" (U+041E), with a printed disambiguation clause
specifying which codepoint is binding.

Discrimination across 8 models (15 cases each):

| Model | Pass | Spread |
|---|---:|---:|
| `openai:gpt-5` | 100% | |
| `anthropic:claude-haiku-4-5` | 93% | |
| `google:gemini-2.5-flash` | 87% | |
| `openai:gpt-4o` | 80% | |
| `google:gemini-2.5-pro` | 67% | |
| `anthropic:claude-sonnet-4-6` | 60% | |
| `anthropic:claude-opus-4-7` | **0%** | |
| `google:gemini-flash-lite-latest` | **0%** | spread = 1.00 |

**Headline:** Anthropic's most expensive model (Opus 4-7) fails 0/15
while Anthropic's cheap model (Haiku 4-5) passes 14/15. Same provider,
same vision pipeline class — different blind spots. The premium tier
is *not* universally better at document reading.

This trap is in `keep/` pending human review and will be merged into
`mini-v3` after a confirmation re-run.

### Methodology promise

Every overnight run produces:
- A new row in `results.tsv` for every candidate proposed (kept or
  reverted) — the research trail.
- A `keep/<id>.json` snapshot for every survivor: code, panel
  results, researcher rationale, novelty score, timestamp.
- A `budget.jsonl` audit log of every dollar spent.

These are sufficient to reproduce or critique the methodology. The
agent does not merge its own work — a human curator promotes
candidates from `keep/` into the next `mini-vN`.

### Not changed

- `mini-v1` and `mini-v2` `suite_hash` unchanged.
- All existing CLI commands, output JSON schemas, and audit-pack
  format unchanged.
- `pdfhell.runner`, `pdfhell.scorer`, `pdfhell.case` unchanged — the
  research loop is read-only with respect to runtime contracts.

## [0.2.0] — 2026-05-23

### Added — `mini-v2` adversarial suite (6 families × 30 cases = 180 cases)

Three new trap families designed to defeat the current frontier cluster
that had plateau'd at 90-97% on `mini-v1`. New families:

- **`scale_dependent_rendering`** — single-page invoice with a prominent
  "TOTAL DUE" decoy at 14pt; the binding amount lives in a 3.5pt
  footnote that blurs below the legibility threshold once a
  vision-language model rasterises the page at its working resolution.
  A naturalistic AP-clerk question ("how much does the company owe on
  invoice X from Y?") forces the model to either resolve the small
  print or return the wrong number.

- **`composite_trap`** — 3-page board pack stacking
  `hidden_ocr_mismatch` + `footnote_override` + `split_table_across_pages`
  in one document. A single question asks three sub-questions sharing
  the same target region / quarter / carveout scope.

- **`cross_page_coreference`** — ~20-page MSA defining Term Alpha, Beta,
  Gamma in §1.4 (page 1) and asking about a compound reference in §12.4
  (page 20). Stresses long-context attention against deliberately placed
  decoy clauses.

### Leaderboard at launch (mini-v2 / 180 cases / 2026-05-23)

| Model | Overall | h_ocr | foot | split | comp | scale | xpage |
|---|---|---|---|---|---|---|---|
| anthropic:claude-haiku-4-5 | **97%** | 100% | 83% | 100% | 100% | 100% | 100% |
| google:gemini-2.5-flash | 94% | 100% | 70% | 100% | 97% | 100% | 100% |
| anthropic:claude-sonnet-4-6 | 79% | 100% | 73% | 100% | 100% | **0%** | 100% |
| openai:gpt-4o | 78% | **0%** | 70% | 97% | 100% | 100% | 100% |

**Headline finding.** Claude Sonnet 4-6 fails `scale_dependent_rendering`
30/30 — it returns the prominent decoy total every single time. Every
other tested model (Haiku 4-5, Gemini 2.5 Flash, GPT-4o) passes 100%.
This is a model-specific blind spot in the premium-tier model: Sonnet's
vision pipeline appears to downscale aggressively enough that 3.5pt
type falls below its working resolution, while Haiku and Gemini-Flash
preserve enough resolution to resolve the footnote.

The `hidden_ocr_mismatch` v1 finding holds: GPT-4o fails 0/30, falling
for the invisible OCR layer 67% of the time. Every Anthropic and Google
model passes 100%.

### Added

- `mini_v2_suite()` in `pdfhell.suite` — 6 trap families × 30 cases each,
  non-overlapping seed ranges (1001-1030 / 2001-2030 / 3001-3030 /
  4001-4030 / 5001-5030 / 6001-6030).
- `SUITES["mini-v2"]` registered for `pdfhell build-suite --suite mini-v2`
  and `pdfhell run --suite mini-v2`.
- Three new generators registered in `pdfhell.generators.GENERATORS`:
  `composite_trap`, `scale_dependent_rendering`, `cross_page_coreference`.

### Compatibility

- `mini-v1` and its `suite_hash` are unchanged. Historical leaderboard
  rows tagged `mini-v1` remain directly comparable to fresh `mini-v1`
  runs on any machine. `mini-v2` is a strict superset suite, not a
  modification of v1.
- All existing CLI commands, output JSON schemas, and audit-pack format
  are unchanged.

## [0.1.3] — 2026-05-20

- `fix(scorer)`: currency-prefix tolerance (`$1,234.56` matches
  `1,234.56` and `USD 1,234.56`).
- `docs`: pyproject URL cleanup.

## [0.1.2] — 2026-05-19

- `feat`: `pdfhell discover --json` — capability catalog for non-MCP agents.

## [0.1.1] — 2026-05-18

- `chore`: ship `suite_version` / `suite_hash` / Wilson 95% CIs in run JSON.

## [0.1.0] — 2026-05-15

- Initial release: `mini-v1` suite with `hidden_ocr_mismatch`,
  `footnote_override`, `split_table_across_pages`. 30 cases.
- CLI: `make`, `build-suite`, `run`, `report`, `share-card`.
- Adapters via `multivon-eval`: Anthropic, OpenAI, Google.
