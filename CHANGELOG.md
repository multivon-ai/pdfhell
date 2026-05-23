# Changelog

All notable changes to pdfhell. Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
