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
# Prefix-match — "gpt-5" catches gpt-5, gpt-5-mini, gpt-5.1, gpt-5.4, etc.
_VISION_CAPABLE = {
    "anthropic": {
        "claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-7",
        "claude-3-5-sonnet", "claude-3-5-haiku", "claude-3-opus",
    },
    "openai": {
        "gpt-4o", "gpt-4.1", "gpt-5",
    },
    "google": {
        # All Gemini variants since 1.5 are vision-capable. The
        # `-flash-lite` and `-flash-lite-latest` family was added to
        # the allowlist after the mini-v4 leaderboard run revealed it
        # was being incorrectly gated out as text-only despite
        # successfully handling PDF input via the genai SDK.
        "gemini-1.5", "gemini-2.5", "gemini-3", "gemini-3.1",
        "gemini-flash", "gemini-flash-lite",
    },
    # ollama serves any locally-pulled GGUF/GGML model via an OpenAI-
    # compatible API at 127.0.0.1:11434. Vision support depends on the
    # underlying model — we list known vision-capable model-name prefixes
    # here. Add more as new VLMs land in the ollama library.
    "ollama": {
        "llama3.2-vision", "llama4-vision", "gemma3", "qwen2.5vl",
        "qwen2-vl", "minicpm-v", "llava", "bakllava", "moondream",
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
    if provider == "ollama":
        return _ollama_call(prompt, sources, judge, max_tokens)
    raise JudgeUnavailable(
        f"provider {provider!r} is not wired for vision; use "
        "anthropic, openai, google, or ollama."
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

    # Anthropic's reasoning-tier models (claude-opus-4-7 and successors)
    # deprecated the `temperature` parameter — they reject the request
    # with a 400 if it's present. Detect those by name and omit the
    # field; the model uses its own default (effectively deterministic
    # for reasoning models). Older models (haiku, sonnet, opus-3, opus-4)
    # still accept and honour temperature, so we keep it for them.
    model_lc = (judge.model or "").lower()
    reasoning_tier = model_lc.startswith("claude-opus-4-7") or model_lc.startswith("claude-opus-5")
    kwargs: dict = {
        "model": judge.model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    if not reasoning_tier:
        kwargs["temperature"] = judge.temperature

    msg = client.messages.create(**kwargs)
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

    # GPT-5.x and the o-series reasoning models deprecated `max_tokens`
    # in favour of `max_completion_tokens`, and they reject the legacy
    # name with a 400. They also reserve some of the output budget for
    # internal "thinking" tokens, so we double the cap for reasoning
    # models to leave room for both reasoning and answer.
    model = (judge.model or "").lower()
    is_reasoning_model = model.startswith("gpt-5") or model.startswith("o1") or model.startswith("o3") or model.startswith("o4")
    kwargs: dict = {
        "model": judge.model,
        "messages": [{"role": "user", "content": parts}],
    }
    if is_reasoning_model:
        kwargs["max_completion_tokens"] = max_tokens * 2
        # Reasoning models reject temperature != 1 with a 400. Omit the
        # param entirely; the model picks its own default.
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = judge.temperature

    resp = client.chat.completions.create(**kwargs)
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


def _ollama_call(
    prompt: str, sources: list[str], judge: JudgeConfig, max_tokens: int
) -> str:
    """Call a locally-running ollama model via its native /api/chat endpoint.

    ollama exposes a native chat API at 127.0.0.1:11434 (configurable via
    OLLAMA_HOST) that accepts inline base64 images directly. We use the
    native API rather than the OpenAI-compatible shim because the
    OpenAI shim doesn't support PDF inputs (only image URLs), but
    ollama's native API can convert PDFs to images server-side via the
    "images" field with PDF bytes for vision-capable models.

    Models are referenced by their ollama tag, e.g. ``ollama:llama3.2-vision``
    or ``ollama:gemma3:4b`` (the colon-suffix variant is rare; we
    accept it by passing the model field through unchanged).

    For PDF input, we rasterise to images locally via pypdf2image since
    ollama's vision API expects images not PDFs. If pdf2image isn't
    installed we fall back to passing the PDF bytes directly and let
    ollama decide.
    """
    try:
        import httpx  # noqa: F401 — used by anthropic/openai SDKs, present in env
    except ImportError:
        pass
    try:
        import urllib.request
        import json as _json
    except ImportError as exc:  # pragma: no cover — stdlib
        raise JudgeUnavailable(f"stdlib import failed: {exc}") from exc

    import os as _os
    host = _os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

    # Build the images list. ollama's /api/chat accepts base64-encoded
    # raw bytes (no data: prefix) in the message's `images` field.
    images: list[str] = []
    for src in sources:
        _, mime, b64 = _image_to_data_uri(src)
        if not b64:
            raise JudgeUnavailable(
                "ollama provider requires local files or data URIs for image input; "
                f"got remote URL: {src}"
            )
        if mime == "application/pdf":
            # Rasterise PDF → image so vision models can read it.
            png_b64 = _pdf_to_png_b64(b64)
            images.append(png_b64)
        else:
            images.append(b64)

    payload = {
        "model": judge.model,
        "messages": [
            {"role": "user", "content": prompt, "images": images},
        ],
        "stream": False,
        "options": {
            "temperature": judge.temperature,
            "num_predict": max_tokens,
        },
    }

    req = urllib.request.Request(
        f"{host}/api/chat",
        data=_json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = _json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise JudgeUnavailable(
            f"ollama request failed: {type(exc).__name__}: {exc}. "
            f"Is ollama running at {host}? (`ollama serve`)"
        ) from exc

    return (body.get("message", {}).get("content", "") or "").strip()


def _pdf_to_png_b64(pdf_b64: str) -> str:
    """Rasterise the first page of a base64-encoded PDF to a PNG and
    return that PNG as base64. Used by the ollama provider since
    vision-capable ollama models expect images, not PDFs.

    Uses pypdf + reportlab if available; falls back to a single-page
    minimal rendering via pypdfium2 (more reliable for arbitrary PDFs).
    """
    import base64
    raw = base64.b64decode(pdf_b64)
    try:
        # pypdfium2 is the best default — pure-Python wheels, no
        # poppler dep, handles most reportlab-generated PDFs cleanly.
        import pypdfium2  # type: ignore[import-not-found]
        pdf = pypdfium2.PdfDocument(raw)
        page = pdf[0]
        # 2x scale = ~150 DPI for a Letter page. Good enough for the
        # vision pipelines we're testing against (Claude rasterises to
        # ~1568px, GPT to 768px tiles — so feeding them ~1700px on the
        # long side keeps detail without bloating bytes).
        bitmap = page.render(scale=2.0)
        pil_image = bitmap.to_pil()
        import io
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except ImportError as exc:
        raise JudgeUnavailable(
            "PDF→PNG conversion needs pypdfium2 for the ollama provider. "
            "Install with `pip install pypdfium2 Pillow`."
        ) from exc


__all__ = ["call_vision", "JudgeUnavailable"]
