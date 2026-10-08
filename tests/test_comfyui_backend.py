"""ComfyUI backend tests, served by a throwaway HTTP server on localhost.

No GPU and no real ComfyUI: a tiny stdlib handler imitates the three endpoints
the backend uses (``/system_stats``, ``/prompt``, ``/history/<id>``, ``/view``,
``/queue``). The cases that matter are the failure ones -- a restart that
silently drops a queued prompt cost a full 10-minute timeout per image before
this was handled.
"""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from reviewforge import images as images_mod

_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/x8AAwMB/6gBnQAAAABJRU5ErkJggg=="
)


class _State:
    def __init__(self, behaviour="ok"):
        self.behaviour = behaviour
        self.prompts = []
        self.posts = []
        self.flaky_left = 3


def _make_server(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/system_stats"):
                return self._json({"system": {"comfyui_version": "test"},
                                   "devices": [{"name": "cpu"}]})
            if self.path.startswith("/object_info/CheckpointLoaderSimple"):
                return self._json({"CheckpointLoaderSimple": {"input": {"required": {
                    "ckpt_name": [["sd_xl_base_1.0.safetensors", "other.safetensors"]]}}}})
            if self.path.startswith("/queue"):
                if state.behaviour == "vanish":
                    return self._json({"queue_running": [], "queue_pending": []})
                if state.behaviour == "stuck":
                    return self._json({"queue_running": [[0, "other-job", {}]],
                                       "queue_pending": [[1, "p1", {}]]})
                return self._json({"queue_running": [[0, "p1", {}]],
                                   "queue_pending": []})
            if self.path.startswith("/history/"):
                if state.behaviour == "flaky" and state.flaky_left > 0:
                    state.flaky_left -= 1
                    return self._json({"error": "busy"}, 500)
                if state.behaviour in ("ok", "flaky"):
                    return self._json({"p1": {"status": {"status_str": "success"},
                                              "outputs": {"9": {"images": [
                                                  {"filename": "x.png",
                                                   "subfolder": "reviewforge",
                                                   "type": "output"}]}}}})
                if state.behaviour == "error":
                    return self._json({"p1": {"status": {
                        "status_str": "error",
                        "messages": [["execution_error", {"exception_message": "boom"}]]}}})
                return self._json({})
            if self.path.startswith("/view"):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(_PNG_1x1)))
                self.end_headers()
                self.wfile.write(_PNG_1x1)
                return
            self._json({}, 404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            state.prompts.append(payload)
            state.posts.append((self.path, payload))
            if self.path != "/prompt":
                return self._json({})
            if state.behaviour == "reject":
                body = json.dumps({"error": "bad graph"}).encode()
                self.send_response(400)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._json({"prompt_id": "p1"})

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv


@pytest.fixture
def comfy():
    state = _State()
    srv = _make_server(state)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield state, url
    srv.shutdown()


def _backend(url, **kw):
    kw.setdefault("poll_interval", 0.01)
    kw.setdefault("timeout", 5.0)
    return images_mod.ComfyUIBackend(url, "sd_xl_base_1.0.safetensors", **kw)


def test_health_and_checkpoint_listing(comfy):
    _state, url = comfy
    b = _backend(url)
    assert b.health()["comfyui_version"] == "test"
    assert "sd_xl_base_1.0.safetensors" in b.available_checkpoints()


def test_render_writes_a_png_and_reports_provenance(comfy, tmp_path):
    state, url = comfy
    b = _backend(url)
    plan = images_mod.plan_illustrative_images("Roofing Contractor")[0]
    out = str(tmp_path / "hero.png")
    detail = b.render(plan, out, 4242)
    assert open(out, "rb").read().startswith(b"\x89PNG")
    assert detail["seed"] == 4242
    assert detail["model"] == "sd_xl_base_1.0.safetensors"
    assert detail["negative_prompt"] == images_mod.NEGATIVE_PROMPT
    # The graph uses only core ComfyUI nodes -- no custom node dependency.
    graph = state.prompts[0]["prompt"]
    kinds = {n["class_type"] for n in graph.values()}
    assert kinds == {
        "CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
        "KSampler", "VAEDecode", "SaveImage",
    }


def test_vanished_prompt_fails_fast_not_after_the_whole_timeout(comfy, tmp_path):
    """A ComfyUI restart drops the queue; we must notice in seconds."""
    state, url = comfy
    state.behaviour = "vanish"
    b = _backend(url, timeout=60.0)  # would hang for a minute without the fix
    plan = images_mod.plan_illustrative_images("Roofing Contractor")[0]
    import time

    t0 = time.time()
    with pytest.raises(images_mod.ImageBackendUnavailable, match="vanished"):
        b.render(plan, str(tmp_path / "hero.png"), 1)
    assert time.time() - t0 < 10.0


def test_job_error_is_reported(comfy, tmp_path):
    state, url = comfy
    state.behaviour = "error"
    b = _backend(url)
    plan = images_mod.plan_illustrative_images("Roofing Contractor")[0]
    with pytest.raises(images_mod.ImageBackendUnavailable, match="failed"):
        b.render(plan, str(tmp_path / "hero.png"), 1)


def test_rejected_graph_surfaces_the_server_message(comfy, tmp_path):
    state, url = comfy
    state.behaviour = "reject"
    b = _backend(url)
    plan = images_mod.plan_illustrative_images("Roofing Contractor")[0]
    with pytest.raises(images_mod.ImageBackendUnavailable, match="rejected"):
        b.render(plan, str(tmp_path / "hero.png"), 1)


def test_unknown_checkpoint_falls_back_to_one_the_server_has(comfy):
    _state, url = comfy
    backend, info = images_mod.resolve_backend(
        "comfyui", comfyui_url=url, checkpoint="not-installed.safetensors"
    )
    assert backend is not None
    assert info["selected"] == "comfyui"
    assert info["requested_checkpoint"] == "not-installed.safetensors"
    assert backend.checkpoint == "sd_xl_base_1.0.safetensors"


def test_resolve_backend_reports_why_nothing_is_available():
    backend, info = images_mod.resolve_backend(
        "auto", comfyui_url="http://127.0.0.1:1"
    )
    assert backend is None
    assert info["selected"] is None
    assert [a["backend"] for a in info["attempts"]] == ["comfyui", "diffusers_script"]
    assert all(a["ok"] is False for a in info["attempts"])


def test_retry_recovers_after_a_transient_failure(comfy, tmp_path):
    """One dropped render must not cost the rest of the image set."""
    _state, url = comfy

    class Flaky(images_mod.ImageBackend):
        name = "flaky"

        def __init__(self):
            self.n = 0
            self.real = _backend(url)

        def health(self):
            return {"backend": self.name}

        def render(self, plan, out_path, seed):
            self.n += 1
            if self.n == 1:
                raise images_mod.ImageBackendUnavailable("vanished")
            return self.real.render(plan, out_path, seed)

    flaky = Flaky()
    imgs, failures = images_mod.generate_illustrative_images(
        "Roofing Contractor", str(tmp_path / "images"), backend=flaky,
        service_count=1, attempts=2,
    )
    assert failures == []
    assert len(imgs) == 2
    assert flaky.n == 3  # 1 failure + retry + the second plan


def test_timed_out_prompt_is_withdrawn_not_left_queued(comfy, tmp_path):
    """Queued behind someone else's long job: on timeout we delete OUR prompt
    from the queue (so the retry does not stack a duplicate) and never
    interrupt the other job."""
    state, url = comfy
    state.behaviour = "stuck"
    b = _backend(url, timeout=0.3)
    plan = images_mod.plan_illustrative_images("Roofing Contractor")[0]
    with pytest.raises(images_mod.ImageBackendUnavailable, match="withdrawn"):
        b.render(plan, str(tmp_path / "hero.png"), 1)
    paths = [p for p, _ in state.posts]
    assert ("/queue", {"delete": ["p1"]}) in state.posts
    assert "/interrupt" not in paths


def test_a_missed_history_poll_is_not_a_failed_render(comfy, tmp_path):
    """A busy server can time out a poll; that must not abort (and duplicate)
    a job that is still queued."""
    state, url = comfy
    state.behaviour = "flaky"
    b = _backend(url)
    plan = images_mod.plan_illustrative_images("Roofing Contractor")[0]
    detail = b.render(plan, str(tmp_path / "hero.png"), 7)
    assert detail["seed"] == 7
    assert sum(1 for p, _ in state.posts if p == "/prompt") == 1


def test_whole_image_set_is_queued_before_waiting(tmp_path):
    """On a shared server the set must be queued as one block."""
    events = []

    class Recorder(images_mod.ImageBackend):
        name = "recorder"

        def submit(self, plan, seed):
            events.append(("submit", plan.slug))
            return f"id-{plan.slug}"

        def collect(self, prompt_id, plan, out_path, seed):
            events.append(("collect", plan.slug))
            open(out_path, "wb").write(_PNG_1x1)
            return {"backend": self.name, "seed": seed}

        def render(self, plan, out_path, seed):  # pragma: no cover - unused
            raise AssertionError("render() should not be needed")

    imgs, failures = images_mod.generate_illustrative_images(
        "Roofing", str(tmp_path), backend=Recorder(), service_count=3)
    assert not failures and len(imgs) == 4
    kinds = [k for k, _ in events]
    assert kinds == ["submit"] * 4 + ["collect"] * 4
