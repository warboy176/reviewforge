"""Image layer: real photos first, generic illustrative imagery as a fallback.

Priority order, highest first:

  1. **The business's own photos.** Supplied in ``business.json`` under
     ``photos`` (local paths or URLs). These are real work, so they get the
     hero slot and an "Our work" gallery.
  2. **Illustrative generic trade imagery**, synthesised locally. This is a
     last resort and is treated as a placeholder, never as portfolio: it is
     flagged in ``provenance.json``, disclosed in the page footer, excluded from the
     gallery, and physically unable to carry a caption claiming the business
     did the work (see ``models.SiteImage``).

Every PNG/JPEG written to the output directory has its embedded text metadata
removed (PNG tEXt/iTXt/zTXt/eXIf/tIME chunks; JPEG EXIF/XMP/IPTC/comment
segments). Generators such as ComfyUI embed their whole workflow in the PNG;
``provenance.json`` records the generation details instead.

Generation reuses an image generator you already run rather than shipping a
new pipeline:

  * ``ComfyUIBackend`` -- talks to a running ComfyUI over its HTTP API
    (``/prompt`` -> ``/history`` -> ``/view``) with nothing but the standard
    library. Defaults to ``http://127.0.0.1:8188``; point ``--comfyui`` /
    ``REVIEWFORGE_COMFYUI_URL`` at your own instance.
  * ``DiffusersScriptBackend`` -- optional adapter for your own local
    ``diffusers`` worker script. Set ``REVIEWFORGE_DIFFUSERS_SCRIPT`` to its
    path to enable it; unset (the default) it is simply reported unavailable.
    Never required.

A shared ComfyUI can also be restarted underneath a build, which silently drops
anything queued; see ``ComfyUIBackend`` for how that case is detected and
retried rather than waited out.

If no backend is reachable the build still succeeds, with no imagery at all.
We would rather ship a plain page than invent a picture.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from reviewforge.llm import describe_endpoint
from reviewforge.models import ORIGIN_GENERATED, SiteImage

DEFAULT_COMFYUI_URL = os.environ.get("REVIEWFORGE_COMFYUI_URL", "http://127.0.0.1:8188")
DEFAULT_CHECKPOINT = os.environ.get(
    "REVIEWFORGE_IMAGE_CHECKPOINT", "sd_xl_base_1.0.safetensors"
)
#: Optional path to a local ``diffusers`` worker script exposing a
#: ``generate_image()`` function. Empty by default, so a plain checkout never
#: depends on one -- set ``REVIEWFORGE_DIFFUSERS_SCRIPT`` to point at yours.
DIFFUSERS_SCRIPT = os.environ.get("REVIEWFORGE_DIFFUSERS_SCRIPT", "")

HERO_SIZE = (1344, 768)
SERVICE_SIZE = (768, 768)

#: Hard constraints on every generated image. The point is imagery that could
#: not be mistaken for a photo of a specific property or a specific crew.
NEGATIVE_PROMPT = (
    "text, words, letters, lettering, caption, watermark, signature, logo, "
    "brand, branding, trademark, company name, signage, street sign, house "
    "number, address, number plate, license plate, phone number, "
    "recognisable face, close-up face, portrait, celebrity, named person, "
    "landmark, famous building, map, document, "
    "deformed, extra limbs, extra fingers, mutated hands, distorted, blurry, "
    "low quality, jpeg artifacts, oversaturated, cartoon, illustration, "
    "painting, 3d render, cgi, collage, frame, border"
)

_PROMPT_SUFFIX = (
    "natural daylight, realistic documentary photograph, 35mm, shallow depth of "
    "field, no text, no signage, no logos, unbranded, anonymous generic "
    "location, professional stock photography"
)


@dataclass(frozen=True)
class ImagePlan:
    """One image we intend to generate."""

    role: str  # "hero" | "service"
    slug: str
    prompt: str
    alt: str
    width: int
    height: int


# ---------------------------------------------------------------------------
# Category prompt library
# ---------------------------------------------------------------------------
# Each entry is (hero, [service scenes]). Scenes are deliberately generic:
# materials, tools and distant, unidentifiable work -- no addresses, no
# readable signage, no identifiable individuals, nothing that could be mistaken
# for a specific customer's property.
_TRADE_SCENES: dict[str, dict[str, Any]] = {
    "roofing": {
        "hero": (
            "a freshly finished asphalt shingle roof on an anonymous suburban "
            "house seen from a low angle against a clear sky, clean straight "
            "shingle courses, new ridge cap",
            "A newly shingled roofline against a clear sky",
        ),
        "services": [
            (
                "a neat arrangement of roofing tools on bare plywood decking, "
                "nail gun, chalk line, flat pry bar, bundle of shingles",
                "Roofing tools laid out on roof decking",
            ),
            (
                "a standing seam metal roof panel detail in soft daylight, "
                "clean ribs and fasteners, close abstract crop",
                "Close detail of a standing seam metal roof",
            ),
            (
                "two roofing workers in hard hats and harnesses seen from a "
                "long distance as small silhouettes on a rooftop, faces not "
                "visible, wide establishing shot",
                "Roofing workers seen at a distance on a rooftop",
            ),
            (
                "a clean new seamless aluminium gutter and downspout along a "
                "plain fascia board, soft morning light",
                "A newly installed gutter and downspout",
            ),
        ],
    },
    "plumbing": {
        "hero": (
            "clean copper and PEX pipework neatly installed in a plain utility "
            "room, new shut-off valves, soft daylight",
            "Neatly installed copper and PEX pipework",
        ),
        "services": [
            ("a set of plumbing wrenches and pipe cutters arranged on a clean "
             "workbench", "Plumbing tools on a workbench"),
            ("a modern tankless water heater mounted on a plain wall in a "
             "utility space", "A wall-mounted tankless water heater"),
            ("a clean modern bathroom sink and chrome faucet, neutral tiling, "
             "no branding", "A clean modern sink and faucet"),
            ("an open trench with a new pvc drain pipe section laid on gravel "
             "bedding, no people, overcast daylight",
             "A new drain pipe section in an open trench"),
        ],
    },
    "electrical": {
        "hero": (
            "a tidy residential electrical panel with neatly dressed wiring and "
            "labelled breakers, no readable text, soft light",
            "A tidy residential electrical panel with neat wiring",
        ),
        "services": [
            ("insulated electrician hand tools and a multimeter on a clean "
             "surface", "Electrician's tools and a multimeter"),
            ("recessed ceiling lights glowing in a plain empty modern room",
             "Recessed ceiling lighting in a plain room"),
            ("a generic electric vehicle charging unit on a plain garage wall, "
             "unbranded", "An unbranded EV charging unit on a garage wall"),
            ("a row of new white wall outlets and switches on a freshly "
             "painted wall, close crop", "New wall outlets and switches"),
        ],
    },
    "hvac": {
        "hero": (
            "a clean new outdoor air conditioning condenser unit on a concrete "
            "pad beside a plain wall, unbranded, soft daylight",
            "A new outdoor air conditioning condenser unit",
        ),
        "services": [
            ("clean new furnace ductwork in a plain basement, bright even light",
             "New ductwork in a plain basement"),
            ("a clean pleated air filter and gauges on a workbench",
             "An air filter and service gauges on a workbench"),
            ("a wall thermostat with a blank unreadable display in a plain room",
             "A wall thermostat in a plain room"),
            ("a ductless mini split indoor unit high on a plain white wall, "
             "unbranded", "A ductless mini-split unit on a wall"),
        ],
    },
    "landscaping": {
        "hero": (
            "a freshly mown lawn with crisp clean edges and tidy planting beds "
            "in anonymous suburban surroundings, golden hour",
            "A freshly mown lawn with tidy planting beds",
        ),
        "services": [
            ("a clean paver patio laid in a running bond pattern, no furniture, "
             "no house visible", "A newly laid paver patio"),
            ("garden hand tools and fresh mulch bags on grass",
             "Garden tools and bags of mulch on grass"),
            ("a trimmed hedge row along a plain path in even daylight",
             "A neatly trimmed hedge along a path"),
            ("young shrubs freshly planted in dark mulch beside a plain path",
             "Young shrubs planted in fresh mulch"),
        ],
    },
    "painting": {
        "hero": (
            "a plain freshly painted interior wall with crisp clean trim lines, "
            "paint roller and drop cloth in frame, bright daylight",
            "A freshly painted interior wall with crisp trim",
        ),
        "services": [
            ("paint rollers brushes and unlabelled paint cans on a drop cloth",
             "Rollers, brushes and paint cans on a drop cloth"),
            ("a painter's taped edge detail on plain trim, macro crop",
             "Close detail of a taped paint edge on trim"),
            ("an empty room mid-repaint with drop cloths and a step ladder",
             "An empty room being repainted"),
            ("a freshly painted plain exterior wall and white window trim "
             "in daylight, close crop", "Freshly painted exterior trim"),
        ],
    },
    "cleaning": {
        "hero": (
            "a spotless empty modern kitchen with gleaming clean surfaces, "
            "bright natural light, no clutter",
            "A spotless empty modern kitchen",
        ),
        "services": [
            ("neatly arranged cleaning supplies in a caddy, unbranded bottles",
             "Unbranded cleaning supplies in a caddy"),
            ("a streak-free window with clean daylight coming through",
             "A clean streak-free window"),
            ("a freshly vacuumed carpet with clean track lines in an empty room",
             "A freshly vacuumed carpet in an empty room"),
            ("a gleaming clean bathroom with white tiles and chrome fixtures, "
             "empty, bright light", "A clean, empty bathroom"),
        ],
    },
    "auto": {
        "hero": (
            "a clean well-lit generic auto repair bay with a vehicle on a lift "
            "seen from behind, no badges, no plates, no signage",
            "A clean auto repair bay with a vehicle on a lift",
        ),
        "services": [
            ("a neat set of mechanic's wrenches and sockets on a clean tool "
             "chest", "Mechanic's wrenches and sockets on a tool chest"),
            ("a new brake rotor and caliper detail on a workbench, macro crop",
             "A new brake rotor and caliper on a workbench"),
            ("a diagnostic scan tool with a blank unreadable screen on a clean "
             "surface", "A vehicle diagnostic scan tool"),
            ("a new tyre being balanced on a wheel balancing machine, close "
             "crop, no branding", "A tyre on a wheel balancing machine"),
        ],
    },
    "generic": {
        "hero": (
            "clean professional hand tools neatly arranged on a plain workbench "
            "in warm daylight, unbranded, no text",
            "Professional hand tools arranged on a workbench",
        ),
        "services": [
            ("a tidy, well-organised workshop wall of unbranded tools",
             "A tidy workshop wall of tools"),
            ("a clipboard and tape measure on a clean workbench, no readable "
             "writing", "A clipboard and tape measure on a workbench"),
            ("a work van side panel in plain unbranded white, parked on an "
             "anonymous street, no plate, no lettering",
             "A plain unbranded work van"),
            ("work gloves and safety glasses resting on a clean workbench",
             "Work gloves and safety glasses on a workbench"),
        ],
    },
}

#: Map words that appear in a free-text category onto a scene set.
_CATEGORY_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("roof", "shingle", "gutter", "siding"), "roofing"),
    (("plumb", "drain", "sewer", "septic", "water heater"), "plumbing"),
    (("electric", "electrician", "wiring", "solar"), "electrical"),
    (("hvac", "heating", "cooling", "air condition", "furnace", "ac "), "hvac"),
    (("landscap", "lawn", "garden", "tree", "yard", "hardscap"), "landscaping"),
    (("paint", "decorat", "drywall"), "painting"),
    (("clean", "janitor", "maid", "housekeep", "carpet"), "cleaning"),
    (("auto", "mechanic", "car repair", "tire", "tyre", "collision"), "auto"),
]


def scene_key_for_category(category: str) -> str:
    """Pick a scene set from a free-text business category."""
    cat = f" {(category or '').lower().strip()} "
    for keywords, key in _CATEGORY_KEYWORDS:
        if any(k in cat for k in keywords):
            return key
    return "generic"


def plan_illustrative_images(category: str, count: int = 3) -> list[ImagePlan]:
    """Build the list of illustrative images to generate for a category.

    ``count`` is the number of *service* images; a hero is always planned.
    """
    scenes = _TRADE_SCENES[scene_key_for_category(category)]
    hero_prompt, hero_alt = scenes["hero"]
    plans = [
        ImagePlan(
            role="hero",
            slug="hero",
            prompt=f"{hero_prompt}, {_PROMPT_SUFFIX}",
            alt=hero_alt,
            width=HERO_SIZE[0],
            height=HERO_SIZE[1],
        )
    ]
    for i, (prompt, alt) in enumerate(scenes["services"][: max(0, count)]):
        plans.append(
            ImagePlan(
                role="service",
                slug=f"service-{i + 1}",
                prompt=f"{prompt}, {_PROMPT_SUFFIX}",
                alt=alt,
                width=SERVICE_SIZE[0],
                height=SERVICE_SIZE[1],
            )
        )
    return plans


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
class ImageBackendUnavailable(RuntimeError):
    """Raised when a backend cannot be reached or is not usable."""


class ImageBackend:
    """Renders an ImagePlan to a PNG on disk."""

    name = "abstract"

    def health(self) -> dict:  # pragma: no cover - interface
        raise NotImplementedError

    def render(self, plan: ImagePlan, out_path: str, seed: int) -> dict:  # pragma: no cover
        raise NotImplementedError


class ComfyUIBackend(ImageBackend):
    """Generate via a running ComfyUI instance over its documented HTTP API.

    Standard library only -- ``urllib`` POSTs a prompt graph to ``/prompt``,
    polls ``/history/<id>`` until the job reports outputs, then pulls the PNG
    from ``/view``. Nothing is installed and no ComfyUI custom nodes are
    needed: the graph uses only core nodes (CheckpointLoaderSimple,
    CLIPTextEncode, EmptyLatentImage, KSampler, VAEDecode, SaveImage).
    """

    name = "comfyui"

    def __init__(
        self,
        url: Optional[str] = None,
        checkpoint: Optional[str] = None,
        *,
        steps: int = 28,
        cfg: float = 6.5,
        sampler: str = "dpmpp_2m",
        scheduler: str = "karras",
        timeout: float = 1800.0,
        poll_interval: float = 2.0,
    ):
        # Resolved late (not as an argument default) so a caller -- or a test
        # -- can redirect the whole process by setting the module constant.
        self.url = (url or DEFAULT_COMFYUI_URL).rstrip("/")
        self.checkpoint = checkpoint or DEFAULT_CHECKPOINT
        self.steps = steps
        self.cfg = cfg
        self.sampler = sampler
        self.scheduler = scheduler
        # Wide on purpose: a shared ComfyUI may be queued behind someone
        # else's long job, and a cold checkpoint load on a busy box can take
        # many minutes before sampling even starts. A job that has actually
        # disappeared is caught separately and fails in seconds, so a long
        # window costs nothing in the common failure case.
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.client_id = f"reviewforge-{os.getpid()}-{int(time.time())}"

    # -- HTTP helpers -----------------------------------------------------
    def _get(self, path: str, timeout: float = 20.0) -> bytes:
        try:
            with urllib.request.urlopen(f"{self.url}{path}", timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise ImageBackendUnavailable(f"GET {path} failed: {exc}") from exc

    def _post_json(self, path: str, payload: dict, timeout: float = 60.0) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:600]
            except Exception:  # noqa: BLE001
                pass
            raise ImageBackendUnavailable(
                f"POST {path} rejected by ComfyUI ({exc.code}): {detail}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ImageBackendUnavailable(f"POST {path} failed: {exc}") from exc

    # -- API --------------------------------------------------------------
    def health(self) -> dict:
        stats = json.loads(self._get("/system_stats").decode("utf-8"))
        sysinfo = stats.get("system", {})
        # Count only, never device names: this dict is published verbatim in
        # provenance.json, and GPU model strings identify the host's hardware.
        device_count = len(stats.get("devices", []))
        return {
            "backend": self.name,
            "url": describe_endpoint(self.url),
            "comfyui_version": sysinfo.get("comfyui_version"),
            "device_count": device_count,
            "checkpoint": self.checkpoint,
        }

    def available_checkpoints(self) -> list[str]:
        info = json.loads(
            self._get("/object_info/CheckpointLoaderSimple").decode("utf-8")
        )
        names = (
            info.get("CheckpointLoaderSimple", {})
            .get("input", {})
            .get("required", {})
            .get("ckpt_name", [[]])[0]
        )
        return list(names or [])

    def _workflow(self, plan: ImagePlan, seed: int, prefix: str) -> dict:
        return {
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": self.checkpoint},
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": plan.width,
                    "height": plan.height,
                    "batch_size": 1,
                },
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": plan.prompt, "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": NEGATIVE_PROMPT, "clip": ["4", 1]},
            },
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": self.steps,
                    "cfg": self.cfg,
                    "sampler_name": self.sampler,
                    "scheduler": self.scheduler,
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": prefix, "images": ["8", 0]},
            },
        }

    def _in_queue(self, prompt_id: str) -> bool:
        """True if ComfyUI still has this prompt running or pending."""
        try:
            q = json.loads(self._get("/queue").decode("utf-8") or "{}")
        except (ImageBackendUnavailable, json.JSONDecodeError):
            # Server unreachable right now (restarting?). Don't call it gone
            # on the strength of a failed poll alone -- let the strike count
            # and the overall deadline decide.
            return True
        for key in ("queue_running", "queue_pending"):
            for item in q.get(key) or []:
                if len(item) > 1 and item[1] == prompt_id:
                    return True
        return False

    def cancel(self, prompt_id: str) -> str:
        """Withdraw our own prompt after giving up on it.

        Without this, a prompt that timed out behind someone else's long job
        stays queued and renders later for nobody -- and the retry queues a
        duplicate behind it. Only ever touches *this* prompt: it is deleted
        from the pending queue, and the running job is interrupted only if
        the running job is ours.
        """
        try:
            q = json.loads(self._get("/queue").decode("utf-8") or "{}")
        except (ImageBackendUnavailable, json.JSONDecodeError):
            return "could not read the queue to cancel it"
        running = any(len(i) > 1 and i[1] == prompt_id for i in q.get("queue_running") or [])
        pending = any(len(i) > 1 and i[1] == prompt_id for i in q.get("queue_pending") or [])
        try:
            if pending:
                self._post_json("/queue", {"delete": [prompt_id]})
                return "withdrawn from the queue"
            if running:
                self._post_json("/interrupt", {})
                return "interrupted"
        except ImageBackendUnavailable as exc:
            return f"cancel failed: {exc}"
        return "no longer queued"

    def wait_until_ready(self, timeout: float = 180.0) -> bool:
        """Block until the server answers /system_stats, or give up.

        Useful right after a restart: the HTTP port opens before the backend
        is willing to accept a prompt.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.health()
                return True
            except ImageBackendUnavailable:
                time.sleep(3.0)
        return False

    def submit(self, plan: ImagePlan, seed: int) -> str:
        """Queue one image and return its prompt id (does not wait)."""
        prefix = f"reviewforge/{plan.slug}"
        graph = self._workflow(plan, seed, prefix)
        resp = self._post_json("/prompt", {"prompt": graph, "client_id": self.client_id})
        prompt_id = resp.get("prompt_id")
        if not prompt_id:
            raise ImageBackendUnavailable(f"ComfyUI returned no prompt_id: {resp!r}")
        return prompt_id

    def render(self, plan: ImagePlan, out_path: str, seed: int) -> dict:
        return self.collect(self.submit(plan, seed), plan, out_path, seed)

    def collect(self, prompt_id: str, plan: ImagePlan, out_path: str, seed: int) -> dict:
        """Wait for a submitted prompt, then download its image to ``out_path``.

        Any failure after submission withdraws the prompt (see :meth:`cancel`)
        so nothing is left queued to render for nobody.
        """
        deadline = time.time() + self.timeout
        images: list[dict] = []
        # A restart of ComfyUI silently drops whatever was queued -- and on
        # this fleet a guard script restarts it on purpose when it bloats. So
        # "not in history" is not enough to keep waiting: if the job is also
        # absent from the queue several checks in a row, it is gone and we say
        # so immediately instead of burning the whole timeout.
        missing_strikes = 0
        while time.time() < deadline:
            time.sleep(self.poll_interval)
            try:
                raw = self._get(f"/history/{urllib.parse.quote(prompt_id)}")
            except ImageBackendUnavailable:
                # A busy server (loading a large model for someone else) can
                # miss a poll. That is not a failed render; the deadline and
                # the vanished-job check decide.
                continue
            hist = json.loads(raw.decode("utf-8") or "{}").get(prompt_id)
            if not hist:
                if self._in_queue(prompt_id):
                    missing_strikes = 0
                else:
                    missing_strikes += 1
                    if missing_strikes >= 3:
                        raise ImageBackendUnavailable(
                            f"ComfyUI job {prompt_id} vanished from both the "
                            "queue and the history (the server most likely "
                            "restarted mid-render)"
                        )
                continue
            missing_strikes = 0
            status = (hist.get("status") or {}).get("status_str")
            if status == "error":
                raise ImageBackendUnavailable(
                    f"ComfyUI job {prompt_id} failed: "
                    f"{json.dumps(hist.get('status'))[:500]}"
                )
            for node_out in (hist.get("outputs") or {}).values():
                images.extend(node_out.get("images") or [])
            if images:
                break
        if not images:
            cancelled = self.cancel(prompt_id)
            raise ImageBackendUnavailable(
                f"ComfyUI job {prompt_id} produced no image within "
                f"{self.timeout:.0f}s ({cancelled})"
            )

        img = images[0]
        query = urllib.parse.urlencode(
            {
                "filename": img.get("filename", ""),
                "subfolder": img.get("subfolder", ""),
                "type": img.get("type", "output"),
            }
        )
        data = self._get(f"/view?{query}", timeout=120.0)
        if not data.startswith(b"\x89PNG"):
            raise ImageBackendUnavailable(
                f"ComfyUI /view returned {len(data)} bytes that are not a PNG"
            )
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(data)
        return {
            "backend": self.name,
            "endpoint": describe_endpoint(self.url),
            "model": self.checkpoint,
            "prompt": plan.prompt,
            "negative_prompt": NEGATIVE_PROMPT,
            "seed": seed,
            "steps": self.steps,
            "cfg": self.cfg,
            "sampler": f"{self.sampler}/{self.scheduler}",
            "comfyui_prompt_id": prompt_id,
        }


class DiffusersScriptBackend(ImageBackend):
    """Optional adapter for your own local ``diffusers`` worker script.

    Enabled only when ``REVIEWFORGE_DIFFUSERS_SCRIPT`` (or the ``tool_path``
    argument) names an existing file, so a plain checkout of this repo never
    depends on one. The script is loaded by file path (not imported as a
    package) and driven through a ``generate_image(prompt, model=, negative=,
    seed=, out_path=, autonomous=)`` function it is expected to expose. It may
    also expose ``VENV_PY``, the interpreter its environment was provisioned
    into, which is checked before use.
    """

    name = "diffusers_script"

    def __init__(self, tool_path: Optional[str] = None, model: str = "sdxl"):
        self.tool_path = tool_path or DIFFUSERS_SCRIPT
        self.model = model
        self._mod = None

    def _load(self):
        if self._mod is not None:
            return self._mod
        if not self.tool_path:
            raise ImageBackendUnavailable(
                "no diffusers script configured "
                "(set REVIEWFORGE_DIFFUSERS_SCRIPT)"
            )
        if not os.path.exists(self.tool_path):
            raise ImageBackendUnavailable(f"{self.tool_path} not present")
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "reviewforge_diffusers_script", self.tool_path
        )
        if spec is None or spec.loader is None:
            raise ImageBackendUnavailable(f"cannot load {self.tool_path}")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:  # noqa: BLE001
            raise ImageBackendUnavailable(f"loading {self.tool_path} failed: {exc}") from exc
        self._mod = mod
        return mod

    def health(self) -> dict:
        mod = self._load()
        venv = getattr(mod, "VENV_PY", None)
        if not venv or not os.path.exists(venv):
            raise ImageBackendUnavailable(
                f"the script's diffusers environment is not provisioned ({venv})"
            )
        return {"backend": self.name, "tool": self.tool_path, "model": self.model}

    def render(self, plan: ImagePlan, out_path: str, seed: int) -> dict:
        mod = self._load()
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        res = mod.generate_image(
            plan.prompt,
            model=self.model,
            negative=NEGATIVE_PROMPT,
            seed=seed,
            out_path=out_path,
            autonomous=False,
        )
        if not res.get("ok"):
            raise ImageBackendUnavailable(
                f"{self.name} failed: {res.get('error')!r}"
            )
        return {
            "backend": self.name,
            "tool": self.tool_path,
            "model": self.model,
            "prompt": plan.prompt,
            "negative_prompt": NEGATIVE_PROMPT,
            "seed": res.get("seed", seed),
        }


def resolve_backend(
    kind: str = "auto",
    *,
    comfyui_url: Optional[str] = None,
    checkpoint: Optional[str] = None,
    timeout: Optional[float] = None,
) -> tuple[Optional[ImageBackend], dict]:
    """Pick a usable image backend.

    Returns ``(backend_or_None, info)``. ``info`` always explains the outcome,
    so a build that produced no imagery says *why* in ``provenance.json``.
    """
    attempts: list[dict] = []
    candidates: list[ImageBackend] = []
    if kind in ("auto", "comfyui"):
        kw = {"timeout": timeout} if timeout else {}
        candidates.append(ComfyUIBackend(comfyui_url, checkpoint, **kw))
    if kind in ("auto", "diffusers"):
        candidates.append(DiffusersScriptBackend())

    for backend in candidates:
        try:
            health = backend.health()
        except ImageBackendUnavailable as exc:
            attempts.append({"backend": backend.name, "ok": False, "error": str(exc)})
            continue
        if isinstance(backend, ComfyUIBackend):
            try:
                names = backend.available_checkpoints()
            except ImageBackendUnavailable as exc:
                attempts.append(
                    {"backend": backend.name, "ok": False, "error": str(exc)}
                )
                continue
            if names and backend.checkpoint not in names:
                # Be helpful instead of failing: take the first SDXL-looking
                # checkpoint the server actually has.
                fallback = next((n for n in names if "xl" in n.lower()), names[0])
                health["requested_checkpoint"] = backend.checkpoint
                backend.checkpoint = fallback
                health["checkpoint"] = fallback
            # The server's full checkpoint inventory is deliberately NOT
            # recorded: this dict is published verbatim in provenance.json.
        attempts.append({"backend": backend.name, "ok": True, **health})
        return backend, {"selected": backend.name, "attempts": attempts, **health}

    return None, {"selected": None, "attempts": attempts}


# ---------------------------------------------------------------------------
# Generation entry point
# ---------------------------------------------------------------------------
def generate_illustrative_images(
    category: str,
    asset_dir: str,
    *,
    backend: ImageBackend,
    rel_prefix: str = "images",
    service_count: int = 3,
    seed: Optional[int] = None,
    attempts: int = 2,
    on_progress: Optional[Callable[[str], None]] = None,
) -> tuple[list[SiteImage], list[dict]]:
    """Generate the illustrative image set for a business category.

    Every returned :class:`SiteImage` has ``origin=generated``, which makes it
    permanently illustrative: :class:`~reviewforge.models.SiteImage` derives
    ``is_business_own`` from the origin and strips ownership-claiming captions
    and alt text on construction. Captions are never set here at all.

    Returns ``(images, failures)``. Partial success is fine -- a hero image and
    two service images still beats a text-only page, and the failures are
    recorded in provenance.
    """
    rng = random.Random(seed if seed is not None else 20261008)
    os.makedirs(asset_dir, exist_ok=True)
    images: list[SiteImage] = []
    failures: list[dict] = []

    plans = plan_illustrative_images(category, count=service_count)
    seeds = [rng.randrange(1, 2**31 - 1) for _ in plans]

    # On a shared server, queue the whole set up front so it renders as one
    # contiguous block, instead of each image waiting behind whatever other
    # job arrived while the previous one was rendering.
    submitted: dict[str, str] = {}
    submit = getattr(backend, "submit", None)
    collect = getattr(backend, "collect", None)
    if callable(submit) and callable(collect):
        for plan, plan_seed in zip(plans, seeds):
            try:
                submitted[plan.slug] = submit(plan, plan_seed)
            except ImageBackendUnavailable:
                pass  # rendered (and retried) individually below
        if on_progress and submitted:
            on_progress(f"queued {len(submitted)} image(s)")

    for plan, plan_seed in zip(plans, seeds):
        filename = f"{plan.slug}.png"
        out_path = os.path.join(asset_dir, filename)
        if on_progress:
            on_progress(f"generating {plan.role} image '{plan.slug}' ...")
        detail = None
        last_error = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                pid = submitted.pop(plan.slug, None)
                if pid is not None:
                    detail = collect(pid, plan, out_path, plan_seed)
                else:
                    detail = backend.render(plan, out_path, plan_seed)
                break
            except ImageBackendUnavailable as exc:
                last_error = str(exc)
                if attempt >= max(1, attempts):
                    break
                if on_progress:
                    on_progress(
                        f"  attempt {attempt} for '{plan.slug}' failed "
                        f"({last_error}); retrying"
                    )
                waiter = getattr(backend, "wait_until_ready", None)
                if callable(waiter):
                    waiter()
        if detail is not None:
            removed = strip_metadata(out_path)
            detail["embedded_metadata_removed"] = removed
        if detail is None:
            failures.append(
                {"slug": plan.slug, "role": plan.role, "error": last_error}
            )
            continue
        images.append(
            SiteImage(
                src=f"{rel_prefix}/{filename}" if rel_prefix else filename,
                alt=plan.alt,
                caption=None,  # illustrative imagery is never captioned
                origin=ORIGIN_GENERATED,
                role=plan.role,
                width=plan.width,
                height=plan.height,
                generation=detail,
            )
        )
    return images, failures


def probe_image_size(path: str) -> Optional[tuple[int, int]]:
    """Read pixel dimensions of a PNG/JPEG/GIF with the standard library only.

    Used so supplied photos get explicit ``width``/``height`` attributes and
    the page does not shift as images load. Returns ``None`` when the format is
    not recognised -- the renderer then simply omits the attributes.
    """
    import struct

    try:
        with open(path, "rb") as fh:
            head = fh.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
            if head[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", head[6:10])
                return int(w), int(h)
            if head[:2] == b"\xff\xd8":
                fh.seek(2)
                while True:
                    marker = fh.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    if marker[1] in (0xD8, 0xD9) or 0xD0 <= marker[1] <= 0xD7:
                        continue
                    seg = fh.read(2)
                    if len(seg) < 2:
                        return None
                    (length,) = struct.unpack(">H", seg)
                    if marker[1] in (
                        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
                    ):
                        body = fh.read(5)
                        if len(body) < 5:
                            return None
                        h, w = struct.unpack(">HH", body[1:5])
                        return int(w), int(h)
                    fh.seek(length - 2, 1)
    except (OSError, struct.error):
        return None
    return None


def stage_supplied_photos(
    photos: list[SiteImage],
    asset_dir: str,
    *,
    rel_prefix: str = "images",
    name_prefix: str = "photo",
) -> list[SiteImage]:
    """Copy local supplied photo files into the output dir, rewriting ``src``.

    Remote URLs are left untouched: we do not download a business's photos
    behind its back. Staged copies have embedded text metadata (EXIF, XMP,
    PNG text chunks) removed -- phone photos often carry GPS coordinates.
    """
    staged: list[SiteImage] = []
    os.makedirs(asset_dir, exist_ok=True)
    for i, photo in enumerate(photos):
        src = photo.src
        if src.startswith(("http://", "https://", "data:")):
            # Referenced as-is; we do not fetch a business's images behind
            # its back.
            staged.append(photo)
            continue
        if not os.path.exists(src):
            raise FileNotFoundError(
                f"photo #{i} not found: {src!r}. ReviewForge will not substitute "
                "a generated image for a missing real photo -- fix the path or "
                "remove the entry."
            )
        ext = os.path.splitext(src)[1].lower() or ".jpg"
        filename = f"{name_prefix}-{i + 1}{ext}"
        dest = os.path.join(asset_dir, filename)
        shutil.copyfile(src, dest)
        strip_metadata(dest)
        if not (photo.width and photo.height):
            size = probe_image_size(dest)
            if size:
                photo.width, photo.height = size
        photo.src = f"{rel_prefix}/{filename}" if rel_prefix else filename
        staged.append(photo)
    return staged


# ---------------------------------------------------------------------------
# Metadata stripping (standard library only)
# ---------------------------------------------------------------------------
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
#: Ancillary PNG chunks that carry free text or capture details. ComfyUI writes
#: its full prompt graph into tEXt; other tools use iTXt/zTXt/eXIf.
PNG_STRIP_CHUNKS = frozenset({b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME"})
#: JPEG segments removed: APP1 (EXIF, XMP), APP13 (IPTC/Photoshop), COM.
#: APP0 (JFIF), APP2 (ICC colour profile) and APP14 (Adobe colour transform)
#: are kept because dropping them changes how the image renders.
_JPEG_STRIP_MARKERS = frozenset({0xE1, 0xED, 0xFE})


def strip_png_text(data: bytes) -> tuple[bytes, list[str]]:
    """Return ``data`` without text/metadata chunks, plus the chunk types removed."""
    if not data.startswith(_PNG_SIG):
        raise ValueError("not a PNG")
    out = [_PNG_SIG]
    removed: list[str] = []
    pos = len(_PNG_SIG)
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise ValueError("truncated PNG chunk")
        if ctype in PNG_STRIP_CHUNKS:
            removed.append(ctype.decode("ascii"))
        else:
            out.append(data[pos:end])
        pos = end
        if ctype == b"IEND":
            break
    return b"".join(out), removed


def strip_jpeg_metadata(data: bytes) -> tuple[bytes, list[str]]:
    """Return ``data`` without EXIF/XMP/IPTC/comment segments.

    Note: EXIF also carries the orientation flag; rotate photos upright
    before supplying them.
    """
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("not a JPEG")
    out = [b"\xff\xd8"]
    removed: list[str] = []
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise ValueError("malformed JPEG segment")
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker == 0xDA or marker == 0xD9:  # start of scan / end: copy rest
            out.append(data[pos:])
            return b"".join(out), removed
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out.append(data[pos:pos + 2])
            pos += 2
            continue
        (length,) = struct.unpack(">H", data[pos + 2:pos + 4])
        end = pos + 2 + length
        if marker in _JPEG_STRIP_MARKERS:
            removed.append(f"APP{marker - 0xE0}" if marker != 0xFE else "COM")
        else:
            out.append(data[pos:end])
        pos = end
    out.append(data[pos:])
    return b"".join(out), removed


def strip_metadata(path: str) -> list[str]:
    """Strip embedded text metadata from a PNG or JPEG file in place.

    Returns the list of chunk/segment types removed. Other formats are left
    untouched (and an empty list returned).
    """
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        if data.startswith(_PNG_SIG):
            clean, removed = strip_png_text(data)
        elif data.startswith(b"\xff\xd8"):
            clean, removed = strip_jpeg_metadata(data)
        else:
            return []
    except (ValueError, struct.error):
        return []
    if removed:
        with open(path, "wb") as fh:
            fh.write(clean)
    return removed
