"""Formwork command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import yaml

from . import __version__
from .bundle import parse_bundle
from .canvas import Canvas
from .catalogue import parse_discovery
from .dsl import DslError, compile_page
from .generator import (
    generate_apply_script,
    generate_discover_script,
    generate_extract_script,
)
from .preview import build_preview, render_preview
from .refs import REPORT_ONLY_KINDS, apply_plan, build_plan, scan, scan_canvas


def _cmd_gen_extract(_args: argparse.Namespace) -> int:
    print(generate_extract_script())
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    bundle = parse_bundle(_read_json(args.bundle))
    canvas = Canvas.parse(bundle.canvas_html or "")
    refs = scan_canvas(canvas)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "kind": r.kind,
                        "location": r.location,
                        "value": r.value,
                        "webPartTitle": r.web_part_title,
                    }
                    for r in refs
                ],
                indent=2,
            )
        )
        return 0
    web_parts = len(canvas.web_part_controls())
    print(f"page: {bundle.source.page_path}  ({web_parts} web parts)")
    print(f"{'kind':<8} {'web part':<20} location")
    for r in refs:
        print(f"{r.kind:<8} {r.web_part_title:<20} {r.location} = {str(r.value)[:60]}")
    report_only = sum(1 for r in refs if r.kind in REPORT_ONLY_KINDS)
    print(
        f"\n{len(refs)} site-bound refs found"
        + (f" ({report_only} link/image: detected, not rewritten)." if report_only else ".")
    )
    return 0


def _cmd_process(args: argparse.Namespace) -> int:
    bundle = parse_bundle(_read_json(args.bundle))
    refs = scan(bundle)
    mapping = _read_json(args.mapping) if args.mapping else {}
    plan = build_plan(refs, mapping)
    result = apply_plan(bundle, plan)

    payload = {
        "schema": "formwork.payload/v1",
        "sourcePage": bundle.source.page_path,
        "title": args.page_name or bundle.page.get("Title", "Formwork copy"),
        "canvas": result.canvas_html,
        "unresolved": [
            {"kind": r.kind, "location": r.location, "value": r.value}
            for r in plan.unresolved
        ],
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    print(
        f"payload written: {args.out} "
        f"({len(result.canvas_html)} chars of canvas, "
        f"{len(plan.applied)} refs resolved, {len(result.rewritten)} control(s) rewritten, "
        f"{len(plan.unresolved)} unresolved)"
    )
    if plan.unresolved:
        print("unresolved site-bound values (left as extracted):", file=sys.stderr)
        for r in plan.unresolved:
            note = "  (report-only)" if r.kind in REPORT_ONLY_KINDS else ""
            print(f"  - [{r.kind}] {r.location} = {str(r.value)[:60]}{note}", file=sys.stderr)
        print(
            "resolve them by adding 'lists' / 'textOverrides' entries to the "
            "mapping file, or accept them and copy the apply script. link and "
            "image values are report-only: detected, not rewritten (no mapping "
            "key is measured for them).",
            file=sys.stderr,
        )
    return 0


def _cmd_gen_discover(_args: argparse.Namespace) -> int:
    print(generate_discover_script())
    return 0


def _cmd_components(args: argparse.Namespace) -> int:
    cat = parse_discovery(_read_json(args.discovery))
    placeable = [c for c in cat.components if c.component_type == 1 and not c.hidden]
    hidden = [c for c in cat.components if c.hidden]
    if args.json:
        print(json.dumps([c.__dict__ for c in cat.components], indent=2))
        return 0
    print(
        f"site: {len(cat.components)} components "
        f"({len(placeable)} placeable, {len(hidden)} hidden)"
    )
    for c in placeable:
        print(f"  {c.alias:<40} {c.title}")
    if cat.text_controls:
        kept = sum(1 for sample in cat.text_controls if sample.persisted is not None)
        print(f"text controls: {len(cat.text_controls)} placed, {kept} persisted")
    return 0


def _cmd_preview(args: argparse.Namespace) -> int:
    spec = _read_yaml(args.spec)
    cat = parse_discovery(_read_json(args.discovery)) if args.discovery else None
    document = render_preview(build_preview(spec, cat))
    if not args.out:
        sys.stdout.write(document)
        return 0
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(document)
    print(f"preview written: {args.out}")
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    cat = parse_discovery(_read_json(args.discovery))
    spec = _read_yaml(args.spec)
    result = compile_page(spec, cat)
    payload = {
        "schema": "formwork.payload/v1",
        "sourcePage": "(compiled from spec)",
        "title": result.title,
        "canvas": result.canvas,
        "unresolved": [],
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(
        f"payload written: {args.out} ({len(result.canvas)} chars of canvas, "
        f"{len(result.parts)} parts)"
    )
    for part in result.parts:
        emphasis = part.get("emphasis") or {}
        styled = f", zoneEmphasis {emphasis['zoneEmphasis']}" if emphasis else ""
        print(
            f"  section {part['section']}, column {part['column']}: "
            f"{part['component']} ({part['title']}{styled})"
        )
    return 0


def _read_yaml(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _cmd_gen_apply(args: argparse.Namespace) -> int:
    payload = _read_json(args.payload)
    print(
        generate_apply_script(
            page_name=args.name,
            canvas_payload=json.dumps(payload),
            promoted_state=args.promoted_state,
        )
    )
    return 0


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formwork",
        description="SharePoint page copier: extract, process, apply.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("gen", help="generate console paste-in scripts")
    gen_sub = gen.add_subparsers(dest="gen_command", required=True)
    gen_extract = gen_sub.add_parser(
        "extract", help="script that downloads the source page bundle"
    )
    gen_extract.set_defaults(func=_cmd_gen_extract)
    gen_discover = gen_sub.add_parser(
        "discover",
        help="script that discovers placeable components via a scratch page",
    )
    gen_discover.set_defaults(func=_cmd_gen_discover)
    gen_apply = gen_sub.add_parser(
        "apply", help="script that creates the page on the target site"
    )
    gen_apply.add_argument("payload", help="payload.json produced by 'process'")
    gen_apply.add_argument("--name", required=True, help="title for the new page")
    gen_apply.add_argument(
        "--promoted-state",
        type=int,
        default=0,
        choices=(0, 1),
        help="0 = site page, 1 = news post",
    )
    gen_apply.set_defaults(func=_cmd_gen_apply)

    inspect_p = sub.add_parser(
        "inspect", help="list the site-bound references in a bundle"
    )
    inspect_p.add_argument("bundle", help="formwork-bundle.json from 'gen extract'")
    inspect_p.add_argument("--json", action="store_true", help="emit JSON")
    inspect_p.set_defaults(func=_cmd_inspect)

    components_p = sub.add_parser(
        "components", help="list placeable components from a discovery document"
    )
    components_p.add_argument(
        "discovery", help="formwork-discovery.json from 'gen discover'"
    )
    components_p.add_argument("--json", action="store_true", help="emit JSON")
    components_p.set_defaults(func=_cmd_components)

    compile_p = sub.add_parser(
        "compile",
        help="compile a page spec (YAML) to an apply payload against a catalogue",
    )
    compile_p.add_argument("spec", help="page spec YAML")
    compile_p.add_argument(
        "discovery", help="formwork-discovery.json from 'gen discover'"
    )
    compile_p.add_argument(
        "--out", default="formwork-payload.json", help="where to write the payload"
    )
    compile_p.set_defaults(func=_cmd_compile)

    preview_p = sub.add_parser(
        "preview",
        help="render a page spec as a standalone HTML page (no SharePoint calls)",
    )
    preview_p.add_argument("spec", help="page spec YAML")
    preview_p.add_argument(
        "--discovery",
        help="formwork-discovery.json: resolves part titles and descriptions "
        "(without it, titles are the aliases in the spec)",
    )
    preview_p.add_argument("--out", help="where to write the HTML (default: stdout)")
    preview_p.set_defaults(func=_cmd_preview)

    process_p = sub.add_parser(
        "process",
        help="rewrite a bundle for the target site and emit an apply payload",
    )
    process_p.add_argument("bundle", help="formwork-bundle.json from 'gen extract'")
    process_p.add_argument(
        "--mapping",
        help="target mapping JSON: baseUrl, siteId, webId, lists, textOverrides",
    )
    process_p.add_argument("--page-name", help="title for the new page")
    process_p.add_argument(
        "--out", default="formwork-payload.json", help="where to write the payload"
    )
    process_p.set_defaults(func=_cmd_process)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Refusals are written for people (TextError/DslError name lines and
    # say what to do); reach the operator as one error line, not a
    # traceback (review P3-6, 2026-09-06).
    try:
        result: int = args.func(args)
    except (DslError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
