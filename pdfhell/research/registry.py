"""Dynamic registration of candidate generators.

The agent writes a new generator file to ``pdfhell/generators/<name>.py``
but the loop needs to register it in :data:`pdfhell.generators.GENERATORS`
*without* modifying ``pdfhell/generators/__init__.py`` (we want
agent-proposed traps to land via the merge process, not auto-merge).

This module does the temporary in-process registration. When the loop
ends, the agent's file is either kept (then a human curator edits
__init__.py to register it) or reverted (the file is deleted).
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _import_from_path(module_name: str, path: Path):
    """Import a module from an explicit filesystem path.

    Avoids relying on the package import machinery picking up files
    written *during* the same process.
    """
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@contextmanager
def temporary_register(trap_family: str, generator_path: Path):
    """Register a candidate generator for the duration of the with-block.

    On entry: import the file from ``generator_path`` and stash a
    reference in :data:`pdfhell.generators.GENERATORS[trap_family]`.

    On exit: pop the trap_family from GENERATORS (whether or not the
    block raised). The file on disk is *not* deleted — that decision
    belongs to the loop based on the score.
    """
    from pdfhell.generators import GENERATORS

    if not generator_path.exists():
        raise FileNotFoundError(f"generator file not found: {generator_path}")

    module_name = f"pdfhell.generators._research_{trap_family}"
    previous = GENERATORS.get(trap_family)
    mod = None
    try:
        mod = _import_from_path(module_name, generator_path)
        if not hasattr(mod, "generate"):
            raise AttributeError(
                f"{generator_path} does not define generate(seed); cannot register"
            )
        GENERATORS[trap_family] = mod.generate
        yield mod.generate
    finally:
        if previous is None:
            GENERATORS.pop(trap_family, None)
        else:
            GENERATORS[trap_family] = previous
        # Clean module from sys.modules so a re-register picks up edits.
        sys.modules.pop(module_name, None)


def materialise_candidate(
    proposal_code: str,
    trap_family: str,
    *,
    base_dir: Path | None = None,
) -> Path:
    """Write the proposal's ``code`` to disk and return the file path.

    ``base_dir`` defaults to ``pdfhell/generators/`` so the file lands
    where the runtime expects it.
    """
    base = base_dir or (REPO_ROOT / "pdfhell" / "generators")
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{trap_family}.py"
    path.write_text(proposal_code, encoding="utf-8")
    return path


def revert_candidate(generator_path: Path) -> None:
    """Delete a generator file that didn't survive scoring."""
    try:
        generator_path.unlink(missing_ok=True)
    except OSError:
        # Best-effort. If we can't delete, leave the file and let the
        # human curator deal with it.
        pass
