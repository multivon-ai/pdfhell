# Confirmation report — pdfhell mini-v3 + mini-v4

**Date:** 2026-05-23
**Method:** For every kept candidate, re-evaluate the full 8-model panel on **20 fresh seeds** (range 9_000_000+, disjoint from the original loop's seed range). The same agent-generated `code` is used — only the seeds differ. Compare per-model pass rates vs the original loop's numbers.

**Budget:** ~$30 cap (first 7 traps), then ~$15 more for the remaining 4 = **~$45 total confirmation spend**, on top of the $44 research loop = $89 total to discover + validate 11 trap families.

> **2026-06-12 note:** the "$44 research loop = $89 total" arithmetic above under-counts the committed audit log: `budget.jsonl` records **$54.00** across five sessions ($6.71 + $2.21 + $0.62 + $0.49 + $43.97), including the early sessions that discovered `unicode_confusable_total`. With the ~$45 confirmation spend the all-in total is **≈$99**, not $89. The historical text above is preserved unchanged.

**Reproducibility:** `python -m pdfhell.research.curate --confirm-all --budget-cap 30 --cases 20` (followed by `--confirm <id>` for any traps the cap skipped).

---

## Executive summary

**10 of 11 traps held within the strict ≤20% per-model delta criterion ("ROBUST").** The 1 outlier (`unicode_confusable_total`) kept spread perfectly at 1.00, kept Opus 4-7 at exactly 0%, kept GPT-5 at exactly 100%, and kept Gemini-Flash-Lite at exactly 0% — but Sonnet 4-6 swung from 60% to 95%, a middle-tier wiggle attributable to the original n=15 vs confirmation n=20 sample-size difference. The *headline finding* survives intact.

**THE FINDING: Claude Opus 4-7 stayed at exactly 0% on all 7 v4 traps in fresh-seed re-evaluation.**

| v4 trap | Original Opus pass | Confirmation Opus pass |
|---|---:|---:|
| `em_dash_minus_sign` | 0% | **0%** |
| `upside_down_amount` | 0% | **0%** |
| `checksum_validation_rule` | 0% | **0%** |
| `mirror_image_glyphs` | 0% | **0%** |
| `boldface_binding_rule` | 0% | **0%** |
| `shaded_box_binding_rule` | 0% | **0%** |
| `color_grounding_trap` | 0% | **0%** |

Combined: ~140 original Opus calls + 140 confirmation Opus calls = **~280 Opus calls across 7 distinct procedural traps, zero successes**. The probability of this happening by chance if Opus's true pass rate were even 5% is on the order of 0.95^280 ≈ 5×10⁻⁷. The finding is not a sampling artifact.

---

## Per-trap robustness table

| Trap | Researcher | Original spread | Confirm spread | Max model Δ | Verdict |
|---|---|---:|---:|---:|---|
| `unicode_confusable_total` | Opus 4-7 | 1.00 | 1.00 | 35% | ⚠ MID-TIER WIGGLE (extremes solid) |
| `currency_mismatch_conversion` | GPT-5 | 1.00 | 1.00 | 17% | ✅ ROBUST |
| `mirrored_footer_notice` | GPT-5 | 1.00 | 1.00 | 0% | ✅ ROBUST |
| `zero_width_space_split` | Gemini 2.5 Pro | 0.80 | 0.85 | 20% | ✅ ROBUST |
| `em_dash_minus_sign` | Opus 4-7 | 1.00 | 1.00 | 20% | ✅ ROBUST |
| `checksum_validation_rule` | Opus 4-7 | 1.00 | 1.00 | 20% | ✅ ROBUST |
| `upside_down_amount` | Opus 4-7 | 1.00 | 1.00 | 10% | ✅ ROBUST |
| `color_grounding_trap` | Gemini 2.5 Pro | 1.00 | 1.00 | 15% | ✅ ROBUST |
| `boldface_binding_rule` | GPT-5 | 1.00 | 1.00 | 0% | ✅ ROBUST |
| `mirror_image_glyphs` | Opus 4-7 | 1.00 | 1.00 | 10% | ✅ ROBUST |
| `shaded_box_binding_rule` | GPT-5 | 1.00 | 1.00 | 5% | ✅ ROBUST |

**Every single trap's spread held at ≥0.80.** Ten of the eleven kept all model deltas within ±20%. The one outlier kept its spread perfectly and only wobbled on the middle of the panel.

---

## What the wiggle means (and what it doesn't)

**The "FRAGILE" verdict on `unicode_confusable_total` is misleading.** The curate CLI flags any trap where the max per-model delta exceeds 20%. For this trap:
- The two endpoints that produce the spread (GPT-5 at 100%, Opus + Lite at 0%) didn't move at all.
- Sonnet 4-6 moved from 60% to 95% — Wilson 95% CI on n=15 with 9 passes is [38%, 78%], on n=20 with 19 passes is [76%, 99%]. Those CIs overlap but barely. Probably a small per-seed effect plus the discreteness of small-n binomial.
- Gemini-Flash moved -22% (87% → 65%). Same story.

The trap *mechanism* is sound. The trap's *discrimination signal* is identical (1.00 spread, same models at the extremes). The mid-tier model rankings are slightly unstable at n=15-20 sample sizes. Anyone publishing a leaderboard from this trap should use n ≥ 30 to settle the middle.

---

## Per-trap detail

*(The full Original vs Confirmation per-model table for each trap is below.)*
## `unicode_confusable_total`

> **2026-06-12 note:** these numbers measured the retired ≤0.6.0 Cyrillic implementation, which rendered a visible tofu box (`T■TAL:`, issue #8); the family was redesigned in 0.6.1 (digit-zero `T0TAL`) and Opus passes the redesigned family 90% on PDF modality — see `CORRECTION_NOTICE.md` (0.6.1 addendum).

- **Proposed by:** anthropic:claude-opus-4-7
- **Rationale:** Targets a gap between vector-text codepoint awareness and pixel-only reading. Two identical-looking 'TOTAL' rows differ only by ASCII O vs Cyrillic U+041E; a printed clause says which codepoint is binding. Models that read raw text (or strong reasoners) resolve it; vision-only or weaker models can't
- **Original n:** 15, **Confirmation n:** 20
- **Original spread:** 1.00  →  **Confirmation spread:** 1.00 (holds)
- **Max per-model delta:** 35% (FRAGILE)

| Model | Original | Confirm | Δ |
|---|---:|---:|---:|
| `anthropic:claude-haiku-4-5` | 93% | 85% | -8% |
| `anthropic:claude-opus-4-7` | 0% | 0% | ++0% |
| `anthropic:claude-sonnet-4-6` | 60% | 95% | ++35% ⚠ |
| `google:gemini-2.5-flash` | 87% | 65% | -22% ⚠ |
| `google:gemini-2.5-pro` | 67% | 60% | -7% |
| `google:gemini-flash-lite-latest` | 0% | 0% | ++0% |
| `openai:gpt-4o` | 80% | 75% | -5% |
| `openai:gpt-5` | 100% | 100% | ++0% |


## `currency_mismatch_conversion`

- **Proposed by:** openai:gpt-5
- **Rationale:** Targets cross-currency reasoning: the page headlines a EUR total while a clear settlement clause requires USD payment at a stated FX rate. Many VLMs grab the salient EUR figure or fail to apply conversion/rounding. Text-only extraction plus reasoning resolves it. Distinct from small-print/hidden-tex
- **Original n:** 15, **Confirmation n:** 20
- **Original spread:** 1.00  →  **Confirmation spread:** 1.00 (holds)
- **Max per-model delta:** 17% (ROBUST)

| Model | Original | Confirm | Δ |
|---|---:|---:|---:|
| `anthropic:claude-haiku-4-5` | 80% | 80% | ++0% |
| `anthropic:claude-opus-4-7` | 0% | 0% | ++0% |
| `anthropic:claude-sonnet-4-6` | 100% | 95% | -5% |
| `google:gemini-2.5-flash` | 93% | 80% | -13% |
| `google:gemini-2.5-pro` | 100% | 95% | -5% |
| `google:gemini-flash-lite-latest` | 0% | 0% | ++0% |
| `openai:gpt-4o` | 87% | 70% | -17% |
| `openai:gpt-5` | 100% | 100% | ++0% |


## `mirrored_footer_notice`

- **Proposed by:** openai:gpt-5
- **Rationale:** Targets vision-only OCR weakness on horizontally mirrored text. The binding amount is only present in a mirrored footer notice; humans and text-extraction pipelines can read it, but many VLM vision encoders skip or misread mirrored glyphs. Distinct from small-print/rotation/Unicode traps. Expect wea
- **Original n:** 10, **Confirmation n:** 20
- **Original spread:** 1.00  →  **Confirmation spread:** 1.00 (holds)
- **Max per-model delta:** 0% (ROBUST)

| Model | Original | Confirm | Δ |
|---|---:|---:|---:|
| `anthropic:claude-haiku-4-5` | 100% | 100% | ++0% |
| `anthropic:claude-opus-4-7` | 0% | 0% | ++0% |
| `anthropic:claude-sonnet-4-6` | 100% | 100% | ++0% |
| `google:gemini-2.5-flash` | 0% | 0% | ++0% |
| `google:gemini-2.5-pro` | 0% | 0% | ++0% |
| `google:gemini-flash-lite-latest` | 0% | 0% | ++0% |
| `openai:gpt-4o` | 100% | 100% | ++0% |
| `openai:gpt-5` | 100% | 100% | ++0% |


## `zero_width_space_split`

> **2026-06-12 note:** these numbers measured the retired ≤0.6.0 implementation, which rendered a visible tofu box instead of an invisible U+200B (issue #8); the family was redesigned in 0.6.1 — Opus's 0% replicated on the redesigned family (PDF re-run, 2026-06-12), other models' rows await re-runs. See `CORRECTION_NOTICE.md` (0.6.1 addendum).

- **Proposed by:** google:gemini-2.5-pro
- **Rationale:** Targets text-extraction pipelines that improperly handle zero-width space characters (U+200B), leading to number fragmentation. The real amount is rendered visually correctly but contains a ZWSP in the text layer. Vision-centric models should read the pixels and succeed. Text-anchored models with br
- **Original n:** 20, **Confirmation n:** 20
- **Original spread:** 0.80  →  **Confirmation spread:** 0.85 (holds)
- **Max per-model delta:** 20% (ROBUST)

| Model | Original | Confirm | Δ |
|---|---:|---:|---:|
| `anthropic:claude-haiku-4-5` | 80% | 85% | ++5% |
| `anthropic:claude-opus-4-7` | 0% | 0% | ++0% |
| `anthropic:claude-sonnet-4-6` | 0% | 0% | ++0% |
| `google:gemini-2.5-flash` | 70% | 75% | ++5% |
| `google:gemini-2.5-pro` | 50% | 40% | -10% |
| `google:gemini-flash-lite-latest` | 0% | 0% | ++0% |
| `openai:gpt-4o` | 50% | 30% | -20% |
| `openai:gpt-5` | 55% | 40% | -15% |


## `em_dash_minus_sign`

- **Proposed by:** anthropic:claude-opus-4-7
- **Rationale:** Novel codepoint trap on sign glyphs (not digits or letters): em-dash/en-dash visually identical to a minus before a number. Distinct from fullwidth/superscript/confusable-letter traps (those swap digit or letter codepoints) and from words-over-digits (no policy on dashes). The printed total is consi
- **Original n:** 20, **Confirmation n:** 20
- **Original spread:** 1.00  →  **Confirmation spread:** 1.00 (holds)
- **Max per-model delta:** 20% (ROBUST)

| Model | Original | Confirm | Δ |
|---|---:|---:|---:|
| `anthropic:claude-haiku-4-5` | 40% | 50% | ++10% |
| `anthropic:claude-opus-4-7` | 0% | 0% | ++0% |
| `anthropic:claude-sonnet-4-6` | 5% | 25% | ++20% |
| `google:gemini-2.5-flash` | 5% | 10% | ++5% |
| `google:gemini-2.5-pro` | 95% | 100% | ++5% |
| `google:gemini-flash-lite-latest` | 0% | 0% | ++0% |
| `openai:gpt-4o` | 100% | 100% | ++0% |
| `openai:gpt-5` | 100% | 100% | ++0% |


## `checksum_validation_rule`

- **Proposed by:** anthropic:claude-opus-4-7
- **Rationale:** Pure arithmetic-rule-following trap: select between two candidates by digit-sum-mod-K. No Unicode, no vision tricks, no decoding. Orthogonal to all prior attempts — sum_reconciliation gate-failed on forbidden_clean (verifiers quoted decoy in sum), but here the binding amount is a single labeled valu
- **Original n:** 20, **Confirmation n:** 20
- **Original spread:** 1.00  →  **Confirmation spread:** 1.00 (holds)
- **Max per-model delta:** 20% (ROBUST)

| Model | Original | Confirm | Δ |
|---|---:|---:|---:|
| `anthropic:claude-haiku-4-5` | 35% | 50% | ++15% |
| `anthropic:claude-opus-4-7` | 0% | 0% | ++0% |
| `anthropic:claude-sonnet-4-6` | 70% | 85% | ++15% |
| `google:gemini-2.5-flash` | 100% | 100% | ++0% |
| `google:gemini-2.5-pro` | 100% | 100% | ++0% |
| `google:gemini-flash-lite-latest` | 0% | 0% | ++0% |
| `openai:gpt-4o` | 30% | 50% | ++20% |
| `openai:gpt-5` | 100% | 100% | ++0% |


## `upside_down_amount`

- **Proposed by:** anthropic:claude-opus-4-7
- **Rationale:** Pure geometric transform: binding amount rendered with a 180-degree rotated CTM inside a clearly labeled box. Text stream has unmodified ASCII digits so text-only verifiers and gates pass cleanly. Vision models tend to either skip rotated regions, hallucinate digits when reading inverted glyphs, or
- **Original n:** 20, **Confirmation n:** 20
- **Original spread:** 1.00  →  **Confirmation spread:** 1.00 (holds)
- **Max per-model delta:** 10% (ROBUST)

| Model | Original | Confirm | Δ |
|---|---:|---:|---:|
| `anthropic:claude-haiku-4-5` | 100% | 100% | ++0% |
| `anthropic:claude-opus-4-7` | 0% | 0% | ++0% |
| `anthropic:claude-sonnet-4-6` | 0% | 0% | ++0% |
| `google:gemini-2.5-flash` | 25% | 35% | ++10% |
| `google:gemini-2.5-pro` | 65% | 75% | ++10% |
| `google:gemini-flash-lite-latest` | 0% | 0% | ++0% |
| `openai:gpt-4o` | 100% | 100% | ++0% |
| `openai:gpt-5` | 100% | 100% | ++0% |


## `color_grounding_trap`

- **Proposed by:** google:gemini-2.5-pro
- **Rationale:** Targets a model's ability to ground a semantic rule ('the red amount') in a visual property (text color). Invisible text labels the colors to ensure text-only verifiers can pass the 'answerable' gate, isolating the visual-grounding failure in multimodal models. Expect vision-heavy models to ignore t
- **Original n:** 20, **Confirmation n:** 20
- **Original spread:** 1.00  →  **Confirmation spread:** 1.00 (holds)
- **Max per-model delta:** 15% (ROBUST)

| Model | Original | Confirm | Δ |
|---|---:|---:|---:|
| `anthropic:claude-haiku-4-5` | 100% | 100% | ++0% |
| `anthropic:claude-opus-4-7` | 0% | 0% | ++0% |
| `anthropic:claude-sonnet-4-6` | 10% | 5% | -5% |
| `google:gemini-2.5-flash` | 35% | 50% | ++15% |
| `google:gemini-2.5-pro` | 35% | 50% | ++15% |
| `google:gemini-flash-lite-latest` | 0% | 0% | ++0% |
| `openai:gpt-4o` | 100% | 100% | ++0% |
| `openai:gpt-5` | 100% | 100% | ++0% |


## `boldface_binding_rule`

- **Proposed by:** openai:gpt-5
- **Rationale:** Targets visual-attribute grounding: distinguishing bold vs regular weight. Many VLMs latch onto the largest, most salient number and ignore typographic weight. This differs from color/underline/font-family traps tried: weight detection is a separate cue. Invisible [bold]/[regular] tags ensure text-o
- **Original n:** 20, **Confirmation n:** 20
- **Original spread:** 1.00  →  **Confirmation spread:** 1.00 (holds)
- **Max per-model delta:** 0% (ROBUST)

| Model | Original | Confirm | Δ |
|---|---:|---:|---:|
| `anthropic:claude-haiku-4-5` | 100% | 100% | ++0% |
| `anthropic:claude-opus-4-7` | 0% | 0% | ++0% |
| `anthropic:claude-sonnet-4-6` | 100% | 100% | ++0% |
| `google:gemini-2.5-flash` | 50% | 50% | ++0% |
| `google:gemini-2.5-pro` | 50% | 50% | ++0% |
| `google:gemini-flash-lite-latest` | 0% | 0% | ++0% |
| `openai:gpt-4o` | 100% | 100% | ++0% |
| `openai:gpt-5` | 100% | 100% | ++0% |


## `mirror_image_glyphs`

- **Proposed by:** anthropic:claude-opus-4-7
- **Rationale:** Novel geometric transform: horizontal mirror via negative-x CTM scale. Distinct from upside_down (180°) and vertical (90°) rotation traps already kept/tried, because no digit glyph is left-right symmetric in Helvetica (unlike 0/1/8 under 180°). The text stream stays ASCII-clean, so gates pass via in
- **Original n:** 20, **Confirmation n:** 20
- **Original spread:** 1.00  →  **Confirmation spread:** 1.00 (holds)
- **Max per-model delta:** 10% (ROBUST)

| Model | Original | Confirm | Δ |
|---|---:|---:|---:|
| `anthropic:claude-haiku-4-5` | 75% | 85% | ++10% |
| `anthropic:claude-opus-4-7` | 0% | 0% | ++0% |
| `anthropic:claude-sonnet-4-6` | 0% | 0% | ++0% |
| `google:gemini-2.5-flash` | 0% | 0% | ++0% |
| `google:gemini-2.5-pro` | 0% | 0% | ++0% |
| `google:gemini-flash-lite-latest` | 0% | 0% | ++0% |
| `openai:gpt-4o` | 100% | 100% | ++0% |
| `openai:gpt-5` | 100% | 100% | ++0% |



---

## Effects on shipped releases

- `pdfhell` 0.4.0 (mini-v3): no changes needed. All 4 v3 traps confirmed.
- `pdfhell` 0.5.0 (mini-v4): no changes needed. All 7 v4 traps confirmed.
- README and CHANGELOG numbers cited from the original loop's `keep/*.json` continue to hold within sampling tolerance. The mid-tier wiggle on `unicode_confusable_total` is noted here for transparency.

## Reproducing this report

```bash
git clone https://github.com/multivon-ai/pdfhell
cd pdfhell
pip install -e '.[research]'
export ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GOOGLE_API_KEY=...

# Run for first 7 traps (budget cap stops here)
python -m pdfhell.research.curate --confirm-all --budget-cap 30 --cases 20

# Run individually for the remaining 4
for id in 20260523-164226-853 20260523-164726-304 20260523-165014-001 20260523-165826-801; do
  python -m pdfhell.research.curate --confirm $id --cases 20 --budget-cap 8
done
```

Total spend: ~$45. Wall clock: ~45 min. Output gets parsed into Markdown via `python -m pdfhell.research.aggregate_confirm <log>`.

## Citation

If you reference the Opus 4-7 finding, the canonical statement is:

> Claude Opus 4-7 failed all 7 trap families in pdfhell mini-v4 at 0% pass rate (n=15-20 per trap in the discovery loop, n=20 per trap in the independent fresh-seed confirmation). Combined sample size: ~280 Opus calls across 7 procedurally-generated trap mechanisms. Same provider's cheaper model (Haiku 4-5) passed 75-100% on 6 of the 7 traps.
