"""Test-wide safety net: never reach a real image backend.

Illustrative image generation talks to a live ComfyUI (and optionally a local
diffusers tool). A test that accidentally falls through to that path would
submit a real GPU render and hang for minutes -- which is exactly what happened
while this layer was being built. Rather than relying on every test
remembering to mock, the defaults are redirected process-wide to an
unroutable address and a non-existent tool, so any unmocked generation attempt
fails fast and loudly instead of quietly using the machine's GPU.
"""
import pytest

from reviewforge import images as images_mod


@pytest.fixture(autouse=True)
def _no_live_image_backend(monkeypatch):
    monkeypatch.setattr(images_mod, "DEFAULT_COMFYUI_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(
        images_mod, "DIFFUSERS_SCRIPT", "/nonexistent/diffusers_worker.py"
    )
    yield
