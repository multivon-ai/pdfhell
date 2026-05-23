# `pdfhell-research` — the agent brief

You are a research agent. Your job is to discover new **adversarial PDF
trap families** that defeat current frontier vision-language models when
they're asked to read documents.

This file is the only one you should read to understand the goal. The
rest of the repo is the playground.

---

## The goal

Maximise the **discrimination score** of new trap families:

```
spread     = pass_rate_max - pass_rate_min     # across the eval panel
solvable   = pass_rate_max >= 0.7              # some model can do it
score      = spread if solvable else 0
```

In plain English: a *useful* trap is one where the best model in the
panel can usually answer correctly (≥70% of the time), and the worst
model usually can't (≤40% of the time). A trap where everyone passes is
useless. A trap where everyone fails is useless. **Models disagreeing
is the signal.**

Bonus: traps that discriminate **differently** from existing traps are
more valuable than traps that split the panel the same way.

---

## What you may modify

### Tier 1 — parameter tuning (safe)

You may edit any file under `pdfhell/generators/` *except*
`__init__.py` and `_common.py`. Tweak numeric parameters: font sizes,
page counts, decoy/real ratios, vendor name pools, paragraph templates.

### Tier 2 — new generators (powerful)

You may create new files under `pdfhell/generators/<your_name>.py` and
register them in `pdfhell/generators/__init__.py`. The contract is:

```python
def generate(seed: int) -> tuple[bytes, HellCase]: ...
```

Read `_common.py` first. It has the primitives:
- `rng_for(seed)` — deterministic RNG, **always use this, never `random`**
- `canvas_to_bytes(draw)` — produces byte-identical PDFs from a draw fn
- `draw_paragraph`, `draw_table`, `draw_invisible_text`, `fmt_money`
- `FontSpec`, `PAGE_WIDTH`, `PAGE_HEIGHT`

Every generator must:
1. Use `rng_for(seed)`, never global `random`
2. Produce byte-identical output from the same seed (asserted twice)
3. Return a valid `HellCase` with: `id`, `trap_family`, `seed`,
   `question`, `expected_answer`, `forbidden_answers`, `metadata`
4. Use `canvas_to_bytes(draw)` (this sets `invariant=True` for you)

### Tier 3 — off-limits

Do **not** touch:
- `pdfhell/scorer.py` — the scoring contract is sacred
- `pdfhell/case.py` — the data model is fixed
- `pdfhell/runner.py` — the eval harness
- `pdfhell/generators/__init__.py` register-list ordering for v1 traps
- This file (`program.md`)

You may add to `__init__.py` to register new generators, but never
remove or rename existing entries.

---

## Validation gates

Before any candidate is scored, **all five gates must pass**. If a gate
fails, the candidate is reverted and the failure is logged. You do not
get partial credit for "almost valid" PDFs.

1. **Parseable** — `pypdf.PdfReader(io.BytesIO(pdf_bytes))` succeeds
   and produces ≥1 page
2. **Deterministic** — `generate(seed)` called twice returns
   byte-identical PDFs
3. **Answerable** — an independent text-only LLM, given the document's
   extracted vector text plus the question, returns the expected answer.
   If 3/4 verifier calls don't agree on `expected_answer`, the case is
   ambiguous and rejected.
4. **Forbidden-clean** — none of the `forbidden_answers` appear as
   substrings of the expected answer or of a verbose correct response.
   The check: ask a strong text-only model to "answer the question
   verbosely, citing the source clause". If a forbidden_answer appears
   in that response, your gate fails — your `forbidden_answers` list
   is too broad.
5. **Lint-clean** — `ruff check` and `python -c "import <module>"`
   succeed.

---

## The eval panel

Probe round (cheap, 2 models × 10 cases):
- `anthropic:claude-haiku-4-5`
- `google:gemini-2.5-flash`

Full round (8 models × 30 cases, only if probe spread ≥ 0.3):
- `anthropic:claude-haiku-4-5`
- `anthropic:claude-sonnet-4-6`
- `anthropic:claude-opus-4-7`
- `openai:gpt-4o`
- `openai:gpt-5`
- `google:gemini-flash-lite-latest`
- `google:gemini-2.5-flash`
- `google:gemini-2.5-pro`

---

## Output format

After each candidate is evaluated, one row is appended to
`pdfhell/research/results.tsv` with columns:

```
timestamp  candidate_id  researcher_model  trap_family  status  score  spread  solvable  cost_usd  per_model_pass  rationale
```

`status` is one of `keep` `revert` `crash` `gate_fail:<gate>`.

You should **read recent rows of results.tsv** before each proposal so
you don't repeat failed approaches. Successful patterns from the log
are fair to extend; failed patterns are dead.

---

## The experiment loop

This is what runs:

```
while budget_remaining and not_converged:
    researcher = next(rotation)                    # Opus → GPT-5 → Gemini-3.0-Pro
    proposal   = researcher.propose(generators, results_tsv, program_md)
    if not validate(proposal): log(gate_fail); revert(); continue
    probe = eval(proposal, [haiku, gem-flash], 10_cases)
    if probe.spread < 0.3: log(revert); revert(); continue
    full  = eval(proposal, FULL_PANEL, 30_cases)
    if full.score > best_score_for_family:
        commit(proposal, msg=auto_describe(full))
        log(keep)
        update_best_score
    else:
        log(revert); revert()
```

`not_converged` means: at least one candidate kept in the last 50
attempts. If 50 attempts in a row produce no improvement, the loop
exits — we've saturated the design space within current researcher
capacity.

---

## Simplicity criterion

All else being equal, **simpler is better**. A trap that achieves the
same discrimination with a shorter generator and fewer parameters is
preferred. A 30-line generator that defeats Sonnet is more valuable
than a 200-line generator with the same discrimination. We are
building a benchmark, not a Rube Goldberg machine.

If your candidate's `generate()` function exceeds 250 lines, you must
include a `rationale` field on the proposal explaining what each
non-obvious section does and why it can't be shorter.

---

## Trap-design hints (read once, then think for yourself)

These are *examples* of the kind of mechanic that produces real
discrimination. They are not the menu. The mini-v1 + mini-v2 traps
already cover:
- invisible OCR layer (hidden_ocr_mismatch)
- footnote override (footnote_override)
- split tables across pages (split_table_across_pages)
- composite stacking (composite_trap)
- sub-legibility footnotes (scale_dependent_rendering)
- long-range coreference (cross_page_coreference)

Productive directions that are *not yet implemented* and seem to
exploit current frontier blind spots:

- **Unicode confusables**: glyphs that render as one character but
  encode another in the text layer (Cyrillic vs Latin lookalikes)
- **Multi-column reading-order traps**: vendor-of-record in column A,
  delivery-of-record in column B; layout-naive readers conflate them
- **Annotation override**: PDF `/Annot` objects (sticky notes,
  highlights) that contradict the body text
- **Form-field default override**: AcroForm fields with computed
  defaults that contradict the rendered text
- **Stamped redactions**: a "REDACTED" black-box overlay that is
  vector-only — text underneath is intact in the PDF stream
- **Right-to-left injection**: Hebrew/Arabic glyphs that re-order
  surrounding Latin text when rendered, vs literal order in the stream
- **Watermark interference**: a "DRAFT" watermark that has different
  text than the headline value, model averages them
- **Date format ambiguity**: 03/04/2026 (UK vs US) where the context
  clause disambiguates 50 pages later
- **Currency mismatch**: line items in EUR, total claimed in USD; the
  binding amount only resolves after FX conversion noted in a footnote

These are *seeds for thought*, not specifications. Invent your own.
The agent rotation guarantees diversity: if Opus and GPT-5 keep
proposing similar mechanics, Gemini-3.0-Pro will break the pattern.

---

## Logging your reasoning

Each proposal must include a `rationale` field (≤ 500 chars) explaining:
- the underlying model failure mechanism you're targeting
- why this mechanism isn't covered by existing traps
- which model in the panel you expect to fail and why

This rationale is recorded in `results.tsv`. It is not used for
scoring, but a strong rationale that turns out to be correct is the
seed of the next paper. Bad rationales that produce high-scoring
traps are also interesting (the field needs to know).

---

## Stop condition

The loop stops when one of:
- Daily budget exhausted ($50/day cap by default)
- 24h wall clock since `loop.py` started
- 50 consecutive candidates produced no keep
- User-signalled stop (`touch pdfhell/research/STOP`)

When the loop stops, the human reviewer (a person, not an LLM)
audits the `keep/` directory. Surviving traps that pass human review
get merged into `pdfhell/generators/` and registered in the next
`mini-vN` suite.

The agent does not get to merge its own work. The agent gets to
*propose*. The benchmark stays grounded.
