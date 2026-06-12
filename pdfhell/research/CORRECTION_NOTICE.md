# Correction notice — pdfhell 0.4.0 / 0.5.0

**Issued:** 2026-05-24
**Affects:** `pdfhell` releases 0.4.0 and 0.5.0; CONFIRMATION_REPORT.md (commit `a325ef3`); README leaderboard sections; multivon.ai pdfhell + leaderboard pages.

## What was wrong

The mini-v3 and mini-v4 leaderboards as originally published claimed that **Claude Opus 4-7 fails 0% on all four mini-v3 traps and all seven mini-v4 traps** (combined: 0/110 to 0/280 Opus calls, zero successes). We attached an "Opus 4-7 systematic blind spot" narrative to that data, validated it in `CONFIRMATION_REPORT.md` (which reported the same 0% per-trap numbers on a fresh-seed re-eval), and surfaced the finding in PyPI release notes for both 0.4.0 and 0.5.0.

**The finding was an evaluation artifact.** Every Opus 4-7 call across the discovery loop + the confirmation loop + the public leaderboard sample had failed at the API layer with:

```
BadRequestError: 400 - `temperature` is deprecated for this model
```

The runner in `pdfhell/vision.py` was passing `temperature=0.0` to `client.messages.create()` for all Anthropic models. Anthropic's reasoning-tier `claude-opus-4-7` rejects the parameter entirely. Our runner caught the exception, returned its string repr as the "model output", and the scorer matched that string against the expected answer, found no match, and recorded `pass=0%, fell-for-trap=0%, refused=0%` — externally indistinguishable from a model that confidently produced a wrong, non-trap answer.

The same bug affected `google:gemini-flash-lite-latest` for a different reason: it was incorrectly gated out of the vision-capable allowlist in `pdfhell.vision._is_vision_capable`, so every call raised `JudgeUnavailable: vision-capable judge required`. Same silent-error mechanism, same 0% report.

## Why this slipped through

The autoresearch loop's `pdfhell.research.researcher` module had its own direct-SDK workaround for the same temperature bug (see `_call_anthropic`), so the researcher's proposals worked fine. But the eval phase of the loop went through `pdfhell.runner` → `pdfhell.vision._anthropic_call`, which still passed `temperature`. The "0%" looked plausible because Opus genuinely does fail certain traps (e.g. `scale_dependent_rendering`, where Sonnet also fails at 0% — verified to still hold below). The pattern of "Opus fails everything new" then survived the fresh-seed confirmation run because the confirmation used the same buggy runner.

The `pdfhell.research.curate` `--confirm` flow ran into the same path. So the validation step we relied on — the entire premise of `CONFIRMATION_REPORT.md` — was also affected.

## The actual mini-v4-sample numbers (after the fix)

With the runner patched to omit `temperature` for Opus 4-7 and to recognise `gemini-flash-lite-latest` as vision-capable, here is the same 8-model panel evaluated on the same 170 cases:

| Model | Overall | Notable per-trap |
|---|---:|---|
| `openai:gpt-5` | 94.7% | — |
| `anthropic:claude-haiku-4-5` | 91.2% | — |
| `google:gemini-flash-lite-latest` | 88.8% | 0% on `zero_width_space_split` |
| `openai:gpt-4o` | 81.2% | 0% on `hidden_ocr_mismatch` (mini-v1 finding holds) |
| `anthropic:claude-opus-4-7` | **79.4%** | 0% on `scale_dependent_rendering` + `zero_width_space_split` |
| `google:gemini-2.5-pro` | 67.1% | 0% on `mirror_image_glyphs`, `mirrored_footer_notice`, `shaded_box_binding_rule` |
| `anthropic:claude-sonnet-4-6` | 60.6% | 0% on `mirror_image_glyphs`, `upside_down_amount`, `color_grounding_trap`, more |
| `google:gemini-2.5-flash` | 59.4% | 0% on `mirror_image_glyphs`, `em_dash_minus_sign`, `mirrored_footer_notice`, more |

## Findings that survive the correction

1. **`scale_dependent_rendering`** (3.5pt footnote, mini-v2): Opus 4-7 + Sonnet 4-6 both 0/10. This is the mini-v2 finding and it survives — Anthropic's reasoning + premium models fail the 3.5pt-footnote trap that Haiku 4-5 (10/10) and GPT-5 (10/10) handle fine. The shipped mini-v2 0.2.0 release notes for this trap are correct.

2. **`zero_width_space_split`** (mini-v3): Opus 4-7 + Sonnet 4-6 + Gemini-Flash-Lite all 0/10. This is the genuine zero-width-space blind spot, also catches Sonnet. The original v3 finding for this trap holds.

3. **`hidden_ocr_mismatch`** (mini-v1): GPT-4o still fails 0/10. The mini-v1 finding holds.

4. **Sonnet 4-6 underperforms Haiku 4-5 by ~30 points** on mini-v4-sample (60.6% vs 91.2%). This *is* a real Anthropic-internal anomaly — but in a different direction than originally claimed. The mid-tier model is weakest; the cheap and the premium tiers both beat it.

## Findings that DO NOT survive

The headline claim that **Claude Opus 4-7 has a systematic blind spot across all 7 mini-v4 trap families** is **retracted**. Opus genuinely fails only 2 of the 7 v4 traps (`zero_width_space_split` 0%, `mirror_image_glyphs` 60%). On the other 5 it scores 5-10/10.

The conditional "Anthropic-wide" pattern described in CONFIRMATION_REPORT.md's Opus summary table is also retracted; it was an artifact of the same bug consistently affecting Opus on every trap.

## What we've fixed and shipped

1. **`pdfhell.vision._anthropic_call`** — omit `temperature` for claude-opus-4-7 and the reasoning tier. Other Anthropic models still receive it.
2. **`pdfhell.vision._VISION_CAPABLE`** — added `gemini-flash` and `gemini-flash-lite` to the Google allowlist.
3. **`pdfhell.scorer.CaseScore`** — new `api_error` field that distinguishes "the provider call failed" from "the model gave a wrong answer".
4. **`pdfhell.scorer.SuiteReport`** — new `api_error_rate` field aggregated across cases.
5. **`pdfhell.cli._print_report`** — loud `⚠` warning when `api_error_rate >= 10%`, prints the first error verbatim, says "pass rate above is unreliable". Direct mitigation: the next time this class of bug occurs the report will scream about it instead of looking like a model failure.
6. **`pdfhell.runner`** — new `ollama:` provider routing through `127.0.0.1:11434` for locally-hosted vision models. Independent of any cloud API.

These ship in `pdfhell` 0.5.1 (patch release covering the bug fix + observability).

## Re-published artifacts

- `pdfhell/README.md` — leaderboard section rewritten with the corrected numbers.
- `pdfhell/CHANGELOG.md` — 0.5.1 entry documents the bug + retraction.
- `pdfhell/research/CONFIRMATION_REPORT.md` — superseded by this notice; the original is preserved in git history at commit `a325ef3` for transparency.
- `multivon-ai/multivon-web/public/data/pdfhell-runs/mini-v4-sample-*.json` — regenerated with the fixed runner. Old JSONs preserved under `v1/` for historical reference.
- `multivon-ai/multivon-web/src/app/leaderboard/page.tsx` — Headline-finding copy rewritten.
- `multivon-ai/multivon-web/src/app/pdfhell/page.tsx` — HeadlineFinding section rewritten.
- `multivon-ai/multivon-web/src/app/page.tsx` — homepage pitch card + proof strip rewritten.

## Why we're publishing this notice

Anyone who saw the original claim — whether from the GitHub README, the multivon.ai site, the 0.4.0 / 0.5.0 PyPI release pages, or downstream blog coverage — deserves to know we got it wrong, exactly how, and what stays true. Retractions are how a benchmark project builds trust over time; quietly editing numbers and hoping nobody noticed is how it loses it.

If you cited the original "Opus 4-7 blind spot" finding, please link to or quote from this notice instead.

— pdfhell maintainers, 2026-05-24

---

## Addendum — 2026-06-12 (pdfhell 0.6.1, issue [#8](https://github.com/multivon-ai/pdfhell/issues/8))

Item 2 of "Findings that survive the correction" above must be reinterpreted. The historical text is preserved unchanged; this addendum is the authoritative reading.

- **The ≤0.6.0 `zero_width_space_split` implementation never contained a working zero-width space.** Helvetica/WinAnsi has no U+200B glyph, so the page rendered a visible tofu box (`Grand Total: $99■,051.90`) and the extracted text carried a substitute character, never a U+200B. The 0/10 rows above for Opus 4-7, Sonnet 4-6, and Gemini-Flash-Lite measured response to *visibly corrupted text*, not an invisible-character trap — the "genuine zero-width-space blind spot" wording is withdrawn in that form. The bug was found by the pixels-only modality (0.6.0, `--pixels`) on its first run.
- **`unicode_confusable_total` had the same bug class:** its "visually identical" Cyrillic О decoy rendered as `T■TAL:`.
- **Both families were redesigned in 0.6.1** — `zero_width_space_split` now fragments the total into two adjacent text runs (pixel-identical, broken to extractors); `unicode_confusable_total` now uses a digit-zero confusable (`T0TAL:` vs `TOTAL:`). A sixth validation gate (`glyph_clean`) pins the no-substitution-glyph invariant. Same-seed PDFs for the two families differ between ≤0.6.0 and ≥0.6.1.
- **The redesigned families were measured 2026-06-12** (8-model PDF-modality panel, n=10/family/model, zero API errors; raw JSONs in [`published_runs/2026-06-12-redesigned-families/`](../../published_runs/2026-06-12-redesigned-families/)). The redesign separated a real blind spot from an artifact:
  - `zero_width_space_split` (now adjacent-text-run fragmentation): **Opus 4-7 remains 0/10** — its published blind spot is real and survives clean methodology. Every other model scores 100%, including Gemini Flash Lite, whose old 0% therefore measured the tofu-box artifact, not a capability gap. The Flash-Lite half of the original claim is withdrawn; the Opus half is confirmed.
  - `unicode_confusable_total` (now digit-zero `T0TAL`/`TOTAL`): new spread — Gemini 2.5 Pro 20%, Gemini 2.5 Flash 60%, Haiku/gpt-4o 70%, GPT-5/Flash-Lite/Opus/Sonnet 100%.
  - Note: these subset runs use the 0.6.1 builds and are published separately; the main leaderboard's full-suite columns still reflect the pre-redesign builds until the next full panel.
