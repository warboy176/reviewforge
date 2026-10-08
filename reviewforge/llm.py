"""Minimal, robust ollama client (stdlib only).

Talks to an ollama endpoint via /api/generate. Designed to fail
gracefully: a timeout, a connection error, or an empty model response raises
``LLMUnavailable`` so the generator can fall back to a deterministic template.

Gotcha handled here: any ``qwen3*`` model MUST be sent ``think:false`` in
the options or it returns empty output. We detect that automatically, but you
can also force it per call.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:32b"
DEFAULT_TIMEOUT = 120.0


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def describe_endpoint(url: str) -> str:
    """How an endpoint is recorded in published output (provenance.json).

    A loopback URL is recorded as-is. Anything else is a host on somebody's
    network, and an internal address has no business in a public web page, so
    only the fact that a non-local endpoint was used is recorded.
    """
    import urllib.parse

    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        host = ""
    if host in _LOCAL_HOSTS:
        return url
    return "non-local endpoint (address not recorded)"


class LLMUnavailable(RuntimeError):
    """Raised when the model cannot be reached or returns nothing usable."""


def _needs_think_false(model: str) -> bool:
    return "qwen3" in model.lower()


def generate(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT,
    system: str | None = None,
    options: dict | None = None,
    fmt: str | None = "json",
) -> str:
    """Call ollama /api/generate and return the raw completion text.

    Raises LLMUnavailable on any failure (network, HTTP, empty output).
    """
    opts = {"temperature": 0.3, "num_ctx": 8192}
    if options:
        opts.update(options)

    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": opts,
    }
    if system:
        payload["system"] = system
    if fmt:
        # Ask ollama to constrain output to JSON when we want structured data.
        payload["format"] = fmt
    if _needs_think_false(model):
        # Known issue: qwen3 returns empty unless thinking is disabled.
        payload["think"] = False

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMUnavailable(f"ollama request failed: {exc}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"ollama returned non-JSON envelope: {exc}") from exc

    text = (parsed.get("response") or "").strip()
    if not text:
        raise LLMUnavailable(
            "ollama returned empty output"
            + (" (qwen3 needs think:false)" if _needs_think_false(model) else "")
        )
    return text


def health(endpoint: str = DEFAULT_ENDPOINT, timeout: float = 10.0) -> list[str]:
    """Return the list of model names the endpoint serves (for diagnostics)."""
    req = urllib.request.Request(f"{endpoint.rstrip('/')}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise LLMUnavailable(f"could not list models: {exc}") from exc
    return [m.get("name", "") for m in parsed.get("models", [])]
