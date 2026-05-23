# `pdfhell.research` — discriminative search for new trap families

A self-play loop that discovers new adversarial PDF traps by directly
optimising for **disagreement among current frontier vision-language
models**.

Inspired by Andrej Karpathy's
[`autoresearch`](https://github.com/karpathy/autoresearch) — same
pattern, ported from "minimise nanochat val_bpb" to "maximise
cross-model discrimination on PDF understanding."

## What it does

```
while budget_remaining and not_converged:
    proposal   = next_researcher.propose(generators, results.tsv, program.md)
    if not validate(proposal):                continue   # gate fail
    probe = eval(proposal, [haiku, gemini-flash], 10 cases)
    if probe.spread < 0.3:                    continue   # no signal
    full  = eval(proposal, FULL_PANEL_8_MODELS, 30 cases)
    if full.score > best_for_family:
        commit(proposal); log(keep)
    else:
        revert();         log(revert)
```

The `score` is:

```
spread   = pass_rate_max - pass_rate_min   across 8 models
solvable = pass_rate_max >= 0.7            some model must succeed
novelty  = 1 - cosine_sim(this_panel_vector, nearest_prior_panel_vector)
score    = spread * novelty   if solvable else 0
```

A *useful* trap is one where the best model gets it right at least
70% of the time and the worst model gets it wrong most of the time —
and it discriminates along a new axis from existing traps.

## The researcher rotation

Three strong reasoning models propose candidates, one per call,
cycling. The rotation prevents the search from collapsing into a
single model's preferred mechanisms.

- `anthropic:claude-opus-4-7`
- `openai:gpt-5`
- `google:gemini-2.5-pro`

Each proposal is one structured JSON object: which file to write, the
full Python source, and a ≤500-char rationale describing the failure
mechanism the researcher is targeting.

## The eval panel

| Tier | Panel | Cost per 30-case eval |
|---|---|---|
| Probe (2 models) | `claude-haiku-4-5`, `gemini-2.5-flash` | ~$0.05 |
| Full (8 models) | + `sonnet-4-6`, `opus-4-7`, `gpt-4o`, `gpt-5`, `gemini-flash-lite`, `gemini-2.5-pro` | ~$3-5 |

The probe round filters out candidates that don't discriminate at
all. Only candidates clearing `spread >= 0.3` on the probe get
promoted to the full panel.

## Validation gates

Five gates, all must pass:

1. **Lint clean** — `ruff check` + `python -c 'import <module>'`
2. **Parseable** — PDF opens in `pypdf`, has ≥1 page
3. **Deterministic** — same seed → byte-identical PDF twice
4. **Answerable** — 3-of-4 text-only verifier LLMs agree on the
   expected answer when given the extracted vector text
5. **Forbidden-clean** — `forbidden_answers` don't false-positive on
   a verbose-correct response (the bug we hit in 0.2.0)

Each gate has been chosen for a specific failure mode that an
agent will eventually try to game. Gates 4 and 5 cost API calls
(~$0.02 per candidate); 1-3 are local.

## Running it

```bash
# Tiny smoke run
python -m pdfhell.research.loop --budget 5 --max-candidates 3

# Real overnight run
python -m pdfhell.research.loop --budget 50 --max-candidates 200
```

Requires `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` in
the environment. Pricing estimates per model live in
[`budget.py`](budget.py).

The loop is interruptible: `Ctrl-C` finishes the current candidate
then exits cleanly. `touch pdfhell/research/STOP` also halts between
candidates.

## Files

| File | Purpose |
|---|---|
| [`program.md`](program.md) | The agent brief — read this first |
| [`loop.py`](loop.py) | Main orchestrator (~250 lines) |
| [`researcher.py`](researcher.py) | LLM rotation + proposal parsing |
| [`eval.py`](eval.py) | Discrimination metric + panel runs |
| [`validate.py`](validate.py) | The five gates |
| [`registry.py`](registry.py) | Temporary candidate registration |
| [`budget.py`](budget.py) | Per-model cost estimates + cap enforcement |
| [`report.py`](report.py) | Summarise a run (status counts, spend by researcher, theme convergence, keepers ranked) |
| [`curate.py`](curate.py) | Confirmation re-run for keepers + promotion plan for next `mini-vN` |
| `results.tsv` | The research trail — one row per candidate, ever |
| `keep/*.json` | Surviving candidates with full provenance |
| `keep/*.py` | The agent-generated source code for each survivor |
| `budget.jsonl` | Per-spend audit log |

## Other CLIs

```bash
# Summarise current state of the research trail
python -m pdfhell.research.report
python -m pdfhell.research.report --json    # machine-readable

# Review keepers + plan the next mini-vN
python -m pdfhell.research.curate                          # list keepers
python -m pdfhell.research.curate --promotion-plan         # markdown summary
python -m pdfhell.research.curate --confirm <id>           # re-run eval, ~$3
python -m pdfhell.research.curate --confirm-all            # all keepers, ~$3 each
```

## What goes into the next `mini-vN`

The agent doesn't merge its own work. A surviving candidate in
`keep/<id>.json` is a *proposal* — a human curator reviews:

1. Does the trap actually represent a real-world failure mode? (Not
   a synthetic gotcha that wouldn't show up in production PDFs)
2. Is the discrimination *robust* — repeat the full eval with fresh
   seeds and the numbers stay similar?
3. Does the trap family have a clean, understandable mechanism we
   can describe in one paragraph for the changelog?

Candidates that pass human review get registered in
`pdfhell/generators/__init__.py` and added to the next `mini-vN`
suite.

## Methodology notes

This module is an *empirical research artifact*, not a feature. It
makes a specific testable claim:

> Discriminative search over an LLM-proposed generator space can find
> new adversarial PDF traps that meaningfully expand the model failure
> taxonomy faster than hand-authored generators alone.

To support that claim, we publish:

- The full `results.tsv` — every candidate ever proposed, with the
  researcher model, the rationale, and the outcome.
- The full `keep/` directory — every surviving candidate with code,
  panel results, and the timestamp.
- The `program.md` brief — exactly what the agent was told.
- The `budget.jsonl` audit log — every cent spent.

These are sufficient to reproduce or critique the methodology. If
you find a class of traps the agent missed, or a way the metric
rewards the wrong thing, please open an issue or send a PR.

## Related work

- Karpathy, A. (2026). [`autoresearch`](https://github.com/karpathy/autoresearch) — single-GPU nanochat autoresearch loop. Architectural pattern we ported.
- Lu et al. (2024). *AI Scientist*. Sakana AI. Multi-paper agentic research loop. Larger scope than ours; we focus narrowly on benchmark generation.
- Pdfhell mini-v2 leaderboard (2026-05) — the empirical motivation for needing more discriminative traps.
