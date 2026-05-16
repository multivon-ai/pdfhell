"""Vision-call dispatch for the three supported providers.

Each provider's vision API has a slightly different content-block
shape (Anthropic wants ``image`` + ``document`` blocks; OpenAI wants
``image_url`` + ``file``; Google wants inline ``Part.from_bytes``). We
dispatch on :attr:`JudgeConfig.provider` and let the per-provider
helpers do the format conversion. Errors surface as
:class:`JudgeUnavailable` so the runner can treat upstream failures as
refusals and still produce a complete report.
"""
from __future__ import annotations

import base64
import mimetypes
import pathlib
import re
from typing import Iterable

from multivon_eval import JudgeConfig
from multivon_eval.exceptions import JudgeUnavailable


# Models we know support vision input. Conservative: when in doubt we
# don't gate (rely on the provider API to surface a real error).
_VISION_CAPABLE = {
    "anthropic": {
        "claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-7",
        "claude-3-5-sonnet", "claude-3-5-haiku", "claude-3-opus",
    },
    "openai": {
        "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-5", "gpt-5-mini",
        "gpt-5.5", "gpt-5.5-mini",
    },
    "google": {
        "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
        "gemini-1.5-pro", "gemini-1.5-flash",
    },
}


def _is_vision_capable(judge: JudgeConfig) -> bool:
    model = (judge.model or "").lower()
    if not model:
        return True
    for known in _VISION_CAPABLE.get(judge.provider, set()):
        if model.startswith(known.lower()):
            return True
    return judge.provider not in _VISION_CAPABLE


def _image_to_data_uri(src: str) -> tuple[str, str, str]:
    """Return ``(uri_or_url, mime_type, base64_data)`` for an image source.

    ``src`` may be ``http(s)://``, ``data:``, or a local filesystem path.
    Local paths are read and inlined as base64.
    """
    if src.startswith("data:"):
        match = re.match(r"data:([^;]+);base64,(.+)$", src)
        if not match:
            raise ValueError(f"unrecognised data URI: {src[:60]}")
        return src, match.group(1), match.group(2)
    if src.startswith("http://") or src.startswith("https://"):
        mime = mimetypes.guess_type(src)[0] or "image/jpeg"
        return src, mime, ""
    path = pathlib.Path(src).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {src}")
    # PDFs are valid input to most vision APIs (they accept PDF mime
    # types via the same image content blocks). We honour the actual
    # extension rather than forcing image/jpeg.
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        mime = "application/pdf"
    else:
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}", mime, data


def call_vision(
    prompt: str,
    sources: list[str],
    judge: JudgeConfig,
    max_tokens: int = 2048,
) -> str:
    """Call a vision-capable judge with a text prompt + one or more image
    sources (paths, URLs, or data URIs). Returns the raw text answer.

    Raises :class:`JudgeUnavailable` if the SDK is missing, an API key
    isn't set, or the model is text-only.
    """
    if not _is_vision_capable(judge):
        raise JudgeUnavailable(
            f"vision-capable judge required; {judge.provider}/{judge.model} "
            "is text-only. Try google:gemini-2.5-flash (cheap), "
            "anthropic:claude-haiku-4-5, or openai:gpt-4o-mini."
        )
    provider = judge.provider
    if provider == "anthropic":
        return _anthropic_call(prompt, sources, judge, max_tokens)
    if provider == "openai":
        return _openai_call(prompt, sources, judge, max_tokens)
    if provider == "google":
        return _google_call(prompt, sources, judge, max_tokens)
    raise JudgeUnavailable(
        f"provider {provider!r} is not wired for vision; use "
        "anthropic, openai, or google."
    )


def _anthropic_call(
    prompt: str, sources: list[str], judge: JudgeConfig, max_tokens: int
) -> str:
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as exc:
        raise JudgeUnavailable(
            "anthropic SDK not installed. Install with `pip install 'pdfhell[anthropic]'` "
            "or `pip install anthropic`."
        ) from exc
    content: list[dict] = []
    for src in sources:
        _, mime, b64 = _image_to_data_uri(src)
        # PDF inputs use document content blocks on Anthropic; image
        # inputs use image content blocks. Both encode as base64.
        if mime == "application/pdf":
            content.append({
                "type": "document",
                "source": {"type": "base64", "media_type": mime, "data": b64},
            })
        elif b64:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": b64},
            })
        else:
            content.append({"type": "image", "source": {"type": "url", "url": src}})
    content.append({"type": "text", "text": prompt})
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=judge.model,
        max_tokens=max_tokens,
        temperature=judge.temperature,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _openai_call(
    prompt: str, sources: list[str], judge: JudgeConfig, max_tokens: int
) -> str:
    try:
        import openai  # type: ignore[import-not-found]
    except ImportError as exc:
        raise JudgeUnavailable(
            "openai SDK not installed. Install with `pip install 'pdfhell[openai]'` "
            "or `pip install openai`."
        ) from exc
    parts: list[dict] = [{"type": "text", "text": prompt}]
    for src in sources:
        data_uri, mime, _ = _image_to_data_uri(src)
        if mime == "application/pdf":
            # OpenAI accepts PDFs via the file input type since GPT-4o
            # (April 2025). The API expects an inline base64 data URI in
            # the file part.
            parts.append({"type": "file", "file": {"filename": pathlib.Path(src).name, "file_data": data_uri}})
        else:
            parts.append({"type": "image_url", "image_url": {"url": data_uri}})
    client = openai.OpenAI(
        base_url=judge.base_url if judge.base_url else None,
    )
    resp = client.chat.completions.create(
        model=judge.model,
        max_tokens=max_tokens,
        temperature=judge.temperature,
        messages=[{"role": "user", "content": parts}],
    )
    return resp.choices[0].message.content or ""


def _google_call(
    prompt: str, sources: list[str], judge: JudgeConfig, max_tokens: int
) -> str:
    try:
        from google import genai  # type: ignore[import-not-found]
        from google.genai import types as genai_types  # type: ignore[import-not-found]
    except ImportError as exc:
        raise JudgeUnavailable(
            "google-genai SDK not installed. Install with `pip install 'pdfhell[google]'` "
            "or `pip install google-genai`."
        ) from exc
    contents: list = []
    for src in sources:
        _, mime, b64 = _image_to_data_uri(src)
        if b64:
            contents.append(
                genai_types.Part.from_bytes(data=base64.b64decode(b64), mime_type=mime)
            )
        else:
            raise JudgeUnavailable(
                "google-genai requires local files or data URIs for image input; "
                f"got remote URL: {src}"
            )
    contents.append(prompt)
    client = genai.Client()
    resp = client.models.generate_content(
        model=judge.model,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            temperature=judge.temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return resp.text or ""


__all__ = ["call_vision", "JudgeUnavailable"]
