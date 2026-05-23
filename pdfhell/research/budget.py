"""Cost cap for the research loop.

We don't have a per-call usage stream from ``pdfhell.runner`` (the
runner is provider-agnostic and doesn't surface token counts). For the
research loop's purposes a *per-case price estimate* is good enough —
we're not billing customers, we're stopping a runaway agent. The
estimate is intentionally conservative: it should overstate cost
slightly so a $50 cap doesn't get blown by $2.

Pricing is hand-coded per model from the providers' public pricing
pages as of 2026-05. Update PRICING when models or rates change.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# ─── Pricing ────────────────────────────────────────────────────────────
#
# Per-case cost estimate. A single pdfhell case is a multi-modal call:
# typically ~3K input tokens (system + question) + ~1-3K image tokens
# (the rendered PDF) + ~100 output tokens. We collapse all of that into
# one per-case number so the loop doesn't have to model token-by-token
# pricing.
#
# Conservative side of each provider's published rates. These should be
# slightly higher than real for safety.

PER_CASE_USD: dict[str, float] = {
    # Anthropic
    "anthropic:claude-haiku-4-5": 0.005,
    "anthropic:claude-sonnet-4-6": 0.025,
    "anthropic:claude-opus-4-7": 0.090,
    # OpenAI
    "openai:gpt-4o": 0.015,
    "openai:gpt-4.1": 0.020,
    "openai:gpt-5": 0.035,
    "openai:gpt-5-mini": 0.008,
    "openai:gpt-5-pro": 0.080,
    "openai:o3": 0.040,
    "openai:o3-pro": 0.100,
    # Google
    "google:gemini-flash-lite-latest": 0.002,
    "google:gemini-2.5-flash": 0.004,
    "google:gemini-2.5-pro": 0.020,
    "google:gemini-3.0-pro": 0.025,
}

# Researcher-model proposal cost: a single ~3K-input ~2K-output call.
# Used by the loop when it dispatches a proposal; not by eval directly.
RESEARCHER_PER_PROPOSAL_USD: dict[str, float] = {
    "anthropic:claude-opus-4-7": 0.08,
    "openai:gpt-5": 0.05,
    "openai:gpt-5-pro": 0.12,
    "google:gemini-2.5-pro": 0.03,
    "google:gemini-3.0-pro": 0.04,
}


def estimate_run_cost(model: str, n_cases: int) -> float:
    """Estimated cost in USD for ``n_cases`` against ``model``."""
    return PER_CASE_USD.get(model, 0.03) * n_cases


def estimate_proposal_cost(model: str) -> float:
    return RESEARCHER_PER_PROPOSAL_USD.get(model, 0.05)


# ─── Budget ────────────────────────────────────────────────────────────


@dataclass
class Budget:
    """Process-local budget tracker with a JSONL audit log.

    Two-phase accounting: ``reserve()`` deducts the *estimate* before
    dispatch, ``commit(model, actual)`` is called with the realised cost
    after the run completes. Because we don't yet have per-call token
    accounting, ``actual`` equals the estimate today — but the API is
    here for the day we do.

    Thread-safe via a single lock.
    """

    cap_usd: float
    spent_usd: float = 0.0
    reserved_usd: float = 0.0
    log_path: Path | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def remaining(self) -> float:
        return self.cap_usd - self.spent_usd - self.reserved_usd

    def can_spend(self, amount: float) -> bool:
        with self._lock:
            return self.remaining >= amount

    def reserve(self, amount: float) -> bool:
        with self._lock:
            if self.remaining < amount:
                return False
            self.reserved_usd += amount
            return True

    def commit(self, label: str, amount: float) -> None:
        """Finalise a reserved spend.

        We deduct from ``reserved_usd`` and add to ``spent_usd``. If
        the realised amount differs from what was reserved, the
        difference returns to the budget (or comes out of remaining,
        if it overshot).
        """
        with self._lock:
            # We always reserve `amount` today. When real per-call
            # accounting lands, this might over- or under-shoot.
            self.reserved_usd = max(0.0, self.reserved_usd - amount)
            self.spent_usd += amount
        self._log("commit", label, amount)

    def cancel_reservation(self, amount: float) -> None:
        """Refund a reservation that was made but never consumed."""
        with self._lock:
            self.reserved_usd = max(0.0, self.reserved_usd - amount)
        self._log("cancel", "", amount)

    def _log(self, action: str, label: str, amount: float) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": action,
            "label": label,
            "amount": round(amount, 4),
            "spent": round(self.spent_usd, 4),
            "reserved": round(self.reserved_usd, 4),
            "remaining": round(self.remaining, 4),
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
