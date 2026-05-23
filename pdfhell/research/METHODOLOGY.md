# Discriminative Search for Adversarial Document Benchmarks

**Methodology note for `pdfhell.research`.**

> *Working draft. The numbers will change as overnight runs accumulate;
> the methodology will not.*

---

## Abstract

We adapt Andrej Karpathy's [`autoresearch`](https://github.com/karpathy/autoresearch)
single-objective optimization loop to the problem of **adversarial PDF
benchmark generation for vision-language models**. Instead of
minimising a training loss, we maximise a *discrimination score* over
a fixed eval panel of 8 frontier vision LLMs (Anthropic, OpenAI,
Google). Candidate trap-family generators are proposed by a rotation
of three strong reasoning models (Opus 4-7, GPT-5, Gemini 2.5 Pro),
pass through five fairness gates (parseable, deterministic,
answerable, forbidden-clean, lint-clean), and are scored on whether
their pass-rate distribution across the panel reveals a model-specific
blind spot.

In our first $7 demo run, the loop discovered
`unicode_confusable_total`: a trap that defeats Anthropic's most
expensive model (Opus 4-7) 0/15 of the time while passing on
Anthropic's cheapest (Haiku 4-5) 14/15 of the time. The trap was
proposed by Opus 4-7 itself acting as the researcher — same model
that fails it.

---

## 1 — Background and motivation

PDF Hell (`pdfhell`) ships hand-authored adversarial trap families
that stress-test how vision-language models read documents. As of
0.2.0 the benchmark covers six trap families: hidden OCR layers,
footnote overrides, split tables, composite traps, scale-dependent
rendering (3.5pt footnotes), and cross-page coreference.

Hand authoring has two failure modes:
1. **Coverage**: A trap family encodes one *kind* of mechanism. As
   models improve they patch specific mechanisms (e.g. GPT-5 has
   essentially eliminated the hidden-OCR vulnerability that GPT-4o
   failed 100% of). New mechanisms require new hand-authoring; the
   pace is bounded by human creativity.
2. **Pattern lock-in**: Our v1 traps lean on a few visual idioms
   (invoices, board packs, MSAs). Models trained on a static
   benchmark eventually pattern-match the document *style* rather
   than the *mechanism*.

Discriminative search addresses both: a population of researcher
models proposes diverse mechanisms, and the search objective rewards
**model disagreement** rather than absolute difficulty. A trap that
everyone fails is useless; a trap that 70% of the panel passes but
30% catastrophically fails is a *signal*.

---

## 2 — Method

### 2.1 The discrimination objective

For a candidate trap family $T$ with pass-rate vector $\mathbf{p}_T \in [0, 1]^{|M|}$ over panel $M$:

$$
\text{spread}(T) = \max_{m \in M} p_T(m) - \min_{m \in M} p_T(m)
$$

$$
\text{solvable}(T) = \mathbb{1}\left[\max_{m \in M} p_T(m) \geq 0.7\right]
$$

$$
\text{novelty}(T) = 1 - \max_{T' \in \mathcal{H}} \cos\left(\mathbf{p}_T, \mathbf{p}_{T'}\right)
$$

$$
\text{score}(T) = \text{spread}(T) \cdot \text{novelty}(T) \cdot \text{solvable}(T)
$$

where $\mathcal{H}$ is the set of previously-kept candidates (history)
and $\cos$ is the cosine similarity between pass-rate vectors. The
novelty term down-weights candidates that discriminate the *same*
models as existing keepers; a trap that splits the panel along a new
axis is more valuable than one that re-splits along an old axis.

The solvability gate at 0.7 is deliberate: a trap where the best
model is at chance (50%) is either unfair, ambiguous, or noise. We
require at least one model to demonstrably *understand* the case,
which proves the question is well-formed.

### 2.2 Researcher rotation

A single LLM-as-researcher is biased toward its own training
distribution: Claude proposes Anthropic-flavoured mechanisms, GPT-5
proposes OpenAI-flavoured ones. We rotate between three strong
reasoning models at each turn:

| Researcher | Anthropic | OpenAI | Google |
|---|---|---|---|
| Opus 4-7 | ✓ | | |
| GPT-5 | | ✓ | |
| Gemini 2.5 Pro | | | ✓ |

This diversifies the exploration. Empirically, we observe **convergent
signals**: when multiple researchers independently propose similar
mechanisms (e.g., both Opus and GPT-5 went after "mirrored text" in
the first demo run), the underlying failure mode is robust evidence
of a real blind spot.

### 2.3 Validation gates

Five gates filter candidates before any expensive vision-API spend is
committed:

1. **Lint-clean** — `ruff check` + `python -c 'import <module>'`
   succeed. Catches syntax errors and import-time bugs.
2. **Parseable** — The generated PDF opens in either `pypdf` (strict)
   or `pdfplumber` (lax). Either parser is sufficient because both
   are used in production document pipelines.
3. **Deterministic** — `generate(seed)` returns byte-identical PDFs
   on two consecutive calls. Determinism is non-negotiable: the
   leaderboard's reproducibility promise depends on it.
4. **Answerable** — 3 of 4 independent text-only LLM verifiers, given
   the PDF's extracted vector text plus the question, return an
   answer that contains the expected answer. If text-extraction +
   reasoning cannot recover the answer, the trap is excluded (we
   currently restrict to traps answerable from both image and text).
5. **Forbidden-clean** — A strong text-only LLM, asked to answer
   verbosely with source citations, does not include any of the
   `forbidden_answers` in its correct response. This catches a
   specific failure mode (which we hit in pdfhell 0.2.0's
   `cross_page_coreference`): over-broad forbidden lists that
   false-positive against correct-but-verbose answers.

Gates 1-3 are local (no API cost). Gates 4 and 5 cost ~$0.02 per
candidate. The full gate suite runs in ~30 seconds.

### 2.4 The loop

```
while budget_remaining and not_converged:
    researcher = next(rotation)
    proposal   = researcher.propose(state)
    if proposal.trap_family in tried_names: continue  # dedupe
    materialise(proposal)
    if not validate(proposal):                continue  # gate fail
    probe = evaluate(proposal, [haiku, gem-flash], 10 cases)
    if probe.spread < 0.3:                    continue  # no signal
    full  = evaluate(proposal, FULL_PANEL_8_MODELS, 30 cases)
    if full.score > best_for_family:
        commit(proposal); log(keep)
    else:
        revert();         log(revert)
```

The probe round runs the cheapest 2 models on 10 cases (~$0.05). If
the spread doesn't clear 0.3 we revert without spending on the full
round. This cuts ~70% of false positives before they cost real money;
in our first demo run, 5 of 10 candidates were eliminated at probe.

### 2.5 The state the researcher sees

Each proposal call hands the researcher:
- `program.md` — the brief (rules + scoring + hints)
- `_common.py` — the primitive APIs available (reportlab helpers,
  deterministic RNG, byte-stable canvas)
- A reference generator (one of the v1/v2 traps) as a worked example
- The last 30 rows of `results.tsv` — what's been tried, what worked
- The top-2 *kept* candidates' full source code as positive examples
- An explicit list of trap_family names already attempted this
  session — names that must not be re-used

Including the kept candidates' source as positive examples is
important: with rationale-only information, researchers explored
broadly but rarely landed near the winning configuration. With
positive examples in the prompt, exploration becomes more goal-
directed without collapsing into duplication (the explicit "don't
duplicate the mechanism" instruction handles the latter).

---

## 3 — Empirical results

### 3.1 First demo run

| Parameter | Value |
|---|---|
| Budget | $10 cap, $6.71 actual |
| Candidates evaluated | 10 |
| Wall clock | ~2 hours |
| Eval panel | 8 models, 15 cases per full round |

Outcomes by status:

| Status | Count |
|---|---:|
| `keep` | 2 |
| `revert_probe` (no spread signal) | 4 |
| `gate_fail:forbidden_clean` | 2 |
| `gate_fail:lint` | 1 |
| `gate_fail:parseable` | 1 |

The gates collectively prevented 4 invalid candidates from reaching
the expensive full-eval round, saving ~$8 in panel-call cost.

### 3.2 The first discovery: `unicode_confusable_total`

Proposed by **Claude Opus 4-7** (anthropic). Verbatim rationale:

> Targets a gap between vector-text codepoint awareness and pixel-only
> reading. Two identical-looking 'TOTAL' rows differ only by ASCII O
> vs Cyrillic U+041E; a printed clause says which codepoint is
> binding. Models that read raw text (or strong reasoners) resolve
> it; vision-only or weaker models can't tell the labels apart and
> guess.

8-model panel, 15 cases each:

| Model | Pass | Notes |
|---|---:|---|
| `openai:gpt-5` | 100% | flawless |
| `anthropic:claude-haiku-4-5` | 93% | cheapest Anthropic, near-flawless |
| `google:gemini-2.5-flash` | 87% | |
| `openai:gpt-4o` | 80% | |
| `google:gemini-2.5-pro` | 67% | |
| `anthropic:claude-sonnet-4-6` | 60% | |
| `anthropic:claude-opus-4-7` | **0%** | premium Anthropic, total failure |
| `google:gemini-flash-lite-latest` | **0%** | cheapest Google, total failure |

spread = 1.00, novelty = 1.00, score = 1.00.

**The premium tier is not universally better.** Opus 4-7 (Anthropic's
most expensive vision model) fails 0/15 while Haiku 4-5 (Anthropic's
cheapest) passes 14/15. Same provider, same architectural lineage,
diverging blind spots.

The trap was **proposed by Opus 4-7 itself**, which means the model
demonstrated meta-awareness of a failure mode that it cannot itself
solve. Opus's rationale predicted Gemini Flash and GPT-4o would fail
— but the actual blind spot was Opus's own.

### 3.3 The second discovery: `currency_mismatch_conversion`

Proposed by GPT-5. Mechanism: invoice headlines a EUR total; a clear
settlement clause requires USD payment at a stated FX rate.

| Model | Pass |
|---|---:|
| `anthropic:claude-sonnet-4-6` | 100% |
| `google:gemini-2.5-pro` | 100% |
| `openai:gpt-5` | 100% |
| `google:gemini-2.5-flash` | 93% |
| `openai:gpt-4o` | 87% |
| `anthropic:claude-haiku-4-5` | 80% |
| `anthropic:claude-opus-4-7` | **0%** |
| `google:gemini-flash-lite-latest` | **0%** |

spread = 1.00, novelty = 0.02, score = 0.02.

Note the **identical model-failure pattern**: Opus 4-7 and Gemini
Flash Lite both at 0%, everyone else high. The novelty term correctly
identifies this as a *different mechanism* (FX/policy reasoning vs
Unicode-codepoint awareness) that *catches the same failure mode*.
Such candidates are useful for robustness — patching either trap
alone wouldn't help; you'd need to fix the root cause.

---

## 4 — Discussion

### 4.1 What this generalises to

The pattern is not specific to document AI. Any benchmark whose
ground truth can be procedurally generated, and any model class
that admits an automated eval, can be plugged in:

- Code completion → procedurally-generated function specs
- Math reasoning → procedurally-generated proof obligations
- Tool use → procedurally-generated API specs with adversarial schema

The two requirements: (a) deterministic ground-truth generation
(no LLM-as-judge in the scoring loop), (b) a diverse eval panel
that's expected to disagree.

### 4.2 Cost-effectiveness

At ~$0.30 per candidate (probe + occasional full eval), 100 candidates
cost ~$30. A keeper rate of 10-20% means $30 buys 10-20 discriminative
traps, or roughly $1.50-3.00 per high-quality benchmark case. Hand-
authoring a single trap family takes a senior engineer ~0.5-2 days
including iteration. The cross-over point is well below 10 traps.

### 4.3 Why discrimination, not absolute difficulty

Optimising for "lowest minimum pass rate" rewards unfair questions:
typos, ambiguous prompts, edge-of-distribution inputs. These break
the benchmark's procedural-ground-truth promise — if no model can
solve it, we can't verify the question is well-formed.

Optimising for spread *and* requiring solvability sidesteps this:
the best model must demonstrate the question is answerable; the
worst model's failure is then a meaningful signal rather than a
shared confusion.

### 4.4 The "agent doesn't merge its own work" principle

Every kept candidate sits in `keep/` until a human curator promotes
it via `python -m pdfhell.research.curate --confirm <id>`. The
confirmation re-run uses fresh seeds and asks: does the spread hold?

This is the methodology's safety rail. An agent that's optimising
the score can find loopholes — over-fit forbidden lists, exploit
verifier weaknesses, exploit specific seed values. The
seed-disjoint confirmation rerun + per-model delta inspection
catches over-fit traps before they get registered as part of the
permanent leaderboard.

---

## 5 — Limitations

### 5.1 Vision-only traps are excluded

The `answerable` gate requires that a *text-only* verifier (reading
the PDF's extracted vector text) can derive the answer. This excludes
trap mechanisms where the answer lives only in visual features —
checkbox states, color coding, position, spatial layout. Such traps
*are* real failure modes in vision-language pipelines, but our
current verifier setup cannot validate question fairness for them.

Adding a vision-capable verifier creates a circularity: the verifier
shares an architecture class with the eval panel, so verifier
agreement doesn't independently confirm answer derivability. A
proper fix probably requires non-LLM verifiers (e.g., OCR
ground-truth from rasterized output) and is out of scope here.

### 5.2 Researcher convergence on one provider's blind spot

In the first run, multiple researchers from multiple providers
converged on traps that catch Opus 4-7 + Gemini Flash Lite. This is
informative (those models genuinely have correlated failure modes)
but it also reflects an exploration bias: once a researcher sees
the kept-example showing this pattern, it gravitates there. The
novelty term partly addresses this, but not fully. Mitigations:
periodically restart with kept-examples redacted, run separate
loops per researcher, sample candidates randomly from the rotation
rather than cycling.

### 5.3 Probe-round false negatives

The probe panel uses Haiku 4-5 and Gemini Flash. A trap that
discriminates only the *highest-tier* models (Opus, GPT-5, Gemini
Pro) but not the probe-tier ones will be incorrectly reverted at
probe. We accept this trade-off because the alternative (always
running the full panel) costs 50x more per candidate.

### 5.4 The metric rewards solvable + discriminative; nothing else

The score does *not* directly reward generalisation to real-world
PDFs. A trap optimal under our metric might be a synthetic gotcha
that wouldn't appear in production documents. Human curation
(`pdfhell.research.curate`) is the corrective: a survivor must look
plausible as a document a real user might encounter before it gets
registered in a mini-vN suite.

---

## 6 — Related work

- **Karpathy, A. (2026)** —
  [`autoresearch`](https://github.com/karpathy/autoresearch). The
  architectural pattern we adapted. Their loop runs a single LLM
  agent against a single training script with a single metric; ours
  rotates researchers, runs against a panel, and gates harder on
  fairness because the artifacts are released to the public.
- **Lu et al. (2024)** — *AI Scientist* (Sakana AI). A larger-scope
  agentic research loop that drafts whole papers. We focus narrowly
  on benchmark-case generation, which is a more constrained sub-
  problem with cleaner success metrics.
- **OpenAI MMMU, Google DocVQA, Anthropic AgentBench** — standard
  benchmarks for vision-language document understanding. None
  procedurally generates ground truth; all use human-annotated test
  sets. pdfhell is complementary, not a replacement.
- **OpenReview / NeurIPS papers on red-teaming via LLM agents** —
  similar pattern of "LLMs propose challenges to other LLMs" applied
  to safety rather than performance benchmarking.

---

## 7 — Reproducing the results

```bash
git clone https://github.com/multivon-ai/pdfhell
cd pdfhell
pip install -e '.[research]'

export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...

python -m pdfhell.research.loop --budget 50 --max-candidates 200
```

The full audit trail of every run produced for this methodology
note is in `pdfhell/research/`:
- `results.tsv` — every candidate ever proposed
- `keep/*.json` — every survivor's full provenance
- `keep/*.py` — the agent-generated source code
- `budget.jsonl` — every dollar spent

These are sufficient to reproduce or critique the work. We welcome
PRs that improve gates, find loopholes, or extend the methodology to
adjacent domains.
