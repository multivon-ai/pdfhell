"""``python -m pdfhell.research`` — directory of available commands.

This is a small dispatcher so ``python -m pdfhell.research`` works
without arguments (showing what's available) instead of erroring out
on the user.
"""
from __future__ import annotations

import sys


_HELP = """\
pdfhell.research — autoresearch-style loop for adversarial trap discovery

Subcommands:

  python -m pdfhell.research.loop --budget 50           Run the discovery loop
  python -m pdfhell.research.report                     Summarise the research trail
  python -m pdfhell.research.report --json              Same, as JSON
  python -m pdfhell.research.curate                     List kept candidates
  python -m pdfhell.research.curate --verify            Check keep/ consistency
  python -m pdfhell.research.curate --promotion-plan    Emit markdown for next mini-vN
  python -m pdfhell.research.curate --preview <id>      Render PDFs from a keeper
  python -m pdfhell.research.curate --confirm <id>      Re-eval a keeper (~\\$3)

Docs:
  pdfhell/research/program.md     — the agent brief
  pdfhell/research/README.md      — feature overview
  pdfhell/research/METHODOLOGY.md — methodology write-up

Requires: ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY in the env
for the loop and confirmation runs (no API needed for report / curate
--verify / --preview / --promotion-plan).
"""


def main() -> int:
    print(_HELP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
