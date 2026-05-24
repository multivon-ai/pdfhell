"""Vision-call dispatch — thin shim over :mod:`multivon_eval.vision`.

As of pdfhell 0.5.2, vision dispatch lives in multivon-eval (>=0.9.1)
so that any multivon-eval consumer can grade documents/images using
the same per-provider plumbing. This module is kept for backwards
compatibility — existing imports of ``pdfhell.vision.call_vision``
continue to work, they just resolve to the upstream implementation.

Provider support (delegated to ``multivon_eval.vision``):
  - ``anthropic``: claude-haiku-4-5, claude-sonnet-4-6, claude-opus-4-7
                   (temperature omitted for reasoning tier), older
                   claude-3 / claude-3-5 variants
  - ``openai``: gpt-4o, gpt-4.1, gpt-5 (reasoning-tier param handling)
  - ``google``: gemini-1.5+, gemini-2.5, gemini-3+, gemini-flash[-lite]
  - ``ollama``: locally-served VLMs (llama3.2-vision, gemma3, qwen2.5vl,
                minicpm-v, llava, moondream); PDFs rasterised via pypdfium2

The shim exists rather than a straight re-export so older code that
imports private helpers (``_anthropic_call``, ``_image_to_data_uri``,
etc.) still resolves to the same symbols. We re-export both the public
``call_vision`` + ``JudgeUnavailable`` and the private helpers
intentionally — pdfhell's own integration tests reach into them.
"""
from __future__ import annotations

from multivon_eval.vision import (
    call_vision,
    _is_vision_capable,
    _image_to_data_uri,
    _anthropic_call,
    _openai_call,
    _google_call,
    _ollama_call,
    _pdf_to_png_b64,
    _VISION_CAPABLE,
)
from multivon_eval.exceptions import JudgeUnavailable


__all__ = ["call_vision", "JudgeUnavailable"]
