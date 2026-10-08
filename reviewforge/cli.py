"""Command-line interface for ReviewForge.

Usage:
    reviewforge build --input business.json --out out/
    python -m reviewforge build --input business.json --out out/

Imagery:
    # Preferred: the business's own photos, listed in business.json.
    reviewforge build -i business.json -o out/

    # No photos supplied? Generate generic illustrative trade imagery on a
    # local ComfyUI instead (disclosed on the page and in provenance.json).
    reviewforge build -i business.json -o out/ --images illustrative \\
        --comfyui http://127.0.0.1:8188

    # Never show imagery we cannot attribute to the business:
    reviewforge build -i business.json -o out/ --images own-only
"""
from __future__ import annotations

import argparse
import json
import sys

from reviewforge import __version__, images as images_mod, llm
from reviewforge.generator import ImageConfig, generate_site_content
from reviewforge.models import LegalRequirementError
from reviewforge.renderer import write_site
from reviewforge.sources import ManualSource


def _image_config(args: argparse.Namespace) -> ImageConfig:
    return ImageConfig(
        mode=args.images,
        backend=args.image_backend,
        comfyui_url=args.comfyui,
        checkpoint=args.image_checkpoint,
        service_count=args.service_images,
        seed=args.image_seed,
        timeout=args.image_timeout,
    )


def _cmd_build(args: argparse.Namespace) -> int:
    source = ManualSource(args.input)
    try:
        business = source.load()
    except (OSError, ValueError) as exc:
        print(f"error: could not load business: {exc}", file=sys.stderr)
        return 2

    print(f"Loaded '{business.name}' ({business.category}, {business.city}) "
          f"with {business.review_count} reviews and "
          f"{len(business.photos)} supplied photo(s).")
    for warning in business.legal_warnings():
        print(f"WARNING: {warning}", file=sys.stderr)

    try:
        content = generate_site_content(
            business,
            model=args.model,
            endpoint=args.endpoint,
            timeout=args.timeout,
            out_dir=args.out,
            image_config=_image_config(args),
            on_progress=lambda msg: print(f"  {msg}"),
        )
    except (FileNotFoundError, LegalRequirementError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Copy source: {content.provenance['copy_source']} "
          f"({content.provenance['note']})")
    print(f"Testimonials selected: {len(content.testimonials)} "
          f"(from {business.review_count} supplied reviews)")

    iset = content.images
    img_info = content.provenance["image_resolution"]
    print(f"Imagery: {img_info.get('source', 'n/a')} "
          f"({len(iset.all_images)} image(s), mode={img_info.get('mode')})")
    if img_info.get("note"):
        print(f"  note: {img_info['note']}")
    for failure in img_info.get("generation_failures", []):
        print(f"  WARN image '{failure['slug']}' failed: {failure['error']}",
              file=sys.stderr)
    if iset.uses_illustrative:
        print("  ILLUSTRATIVE imagery in use -> disclosed in the page footer and flagged in provenance.json")
    stripped = [i for i in iset.all_images if i.rejected_caption or i.rejected_alt]
    for img in stripped:
        print(f"  stripped ownership-claiming text from illustrative image "
              f"{img.src}: {img.rejected_caption or img.rejected_alt!r}")

    paths = write_site(content, args.out)
    print("REVIEW BEFORE PUBLISHING: the copy is machine-drafted. Read every "
          "line against the facts (see the pre-launch checklist in the README).")
    print("Wrote:")
    for label, path in paths.items():
        print(f"  {label}: {path}")
    for img in iset.all_images:
        flag = "illustrative" if img.illustrative else img.origin
        print(f"  image ({flag}): {img.src}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    rc = 0
    try:
        models = llm.health(args.endpoint)
    except llm.LLMUnavailable as exc:
        print(f"LLM endpoint unreachable: {exc}", file=sys.stderr)
        rc = 1
    else:
        print(f"Endpoint {args.endpoint} serves {len(models)} models.")
        target = args.model
        print(f"Target model '{target}': {'FOUND' if target in models else 'NOT FOUND'}")

    backend, info = images_mod.resolve_backend(
        args.image_backend, comfyui_url=args.comfyui,
        checkpoint=args.image_checkpoint, timeout=args.image_timeout,
    )
    if backend is None:
        print("Image backend: NONE reachable (illustrative imagery unavailable; "
              "builds will be text-only unless the business supplies photos)",
              file=sys.stderr)
        for attempt in info.get("attempts", []):
            print(f"  {attempt['backend']}: {attempt.get('error')}", file=sys.stderr)
    else:
        print(f"Image backend: {info['selected']}")
        print(json.dumps(info, indent=2)[:1500])
    return rc


def _add_image_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--images",
        choices=["auto", "own-only", "illustrative", "off"],
        default="auto",
        help="auto: the business's own photos, generated illustrative imagery "
             "only if it supplied none (default). own-only: never show "
             "imagery the business did not supply. illustrative: force "
             "generation. off: no imagery.",
    )
    parser.add_argument(
        "--image-backend",
        choices=["auto", "comfyui", "diffusers"],
        default="auto",
        help="generation backend for illustrative imagery (diffusers requires "
             "REVIEWFORGE_DIFFUSERS_SCRIPT set to a local worker script)",
    )
    parser.add_argument(
        "--comfyui",
        default=images_mod.DEFAULT_COMFYUI_URL,
        help="base URL of a running ComfyUI instance",
    )
    parser.add_argument(
        "--image-checkpoint",
        default=images_mod.DEFAULT_CHECKPOINT,
        help="ComfyUI checkpoint filename to generate with",
    )
    parser.add_argument(
        "--service-images", type=int, default=3,
        help="how many illustrative service images to generate",
    )
    parser.add_argument(
        "--image-seed", type=int, default=None,
        help="seed for reproducible illustrative imagery",
    )
    parser.add_argument(
        "--image-timeout", type=float, default=None,
        help="seconds to wait for one generated image (default 1800; a shared "
             "ComfyUI may be queued behind another job)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reviewforge",
        description="Turn a local business's own customer reviews into a clean, "
                    "honest one-page website it owns.",
    )
    parser.add_argument("--version", action="version", version=f"reviewforge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common_llm = dict(
        model=dict(default=llm.DEFAULT_MODEL, help="ollama model name"),
        endpoint=dict(default=llm.DEFAULT_ENDPOINT, help="ollama base URL"),
    )

    p_build = sub.add_parser("build", help="build a site from a business JSON file")
    p_build.add_argument("--input", "-i", required=True, help="path to business.json")
    p_build.add_argument("--out", "-o", required=True, help="output directory")
    p_build.add_argument("--model", **common_llm["model"])
    p_build.add_argument("--endpoint", **common_llm["endpoint"])
    p_build.add_argument("--timeout", type=float, default=llm.DEFAULT_TIMEOUT,
                         help="LLM request timeout in seconds")
    _add_image_args(p_build)
    p_build.set_defaults(func=_cmd_build)

    p_check = sub.add_parser(
        "check", help="check the LLM endpoint and the image backend")
    p_check.add_argument("--model", **common_llm["model"])
    p_check.add_argument("--endpoint", **common_llm["endpoint"])
    _add_image_args(p_check)
    p_check.set_defaults(func=_cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
