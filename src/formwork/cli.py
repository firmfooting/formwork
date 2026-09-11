"""Formwork command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .bundle import parse_bundle
from .canvas import Canvas
from .catalogue import parse_discovery
from .dsl import DslError, compile_page
from .findings import (
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_PATH,
    Registry,
    load_findings,
    load_findings_if_present,
    stale_findings,
)
from .generator import (
    generate_apply_script,
    generate_discover_script,
    generate_extract_script,
    generate_findprobe_script,
)
from .multipage import (
    PageOptions,
    TemplateVars,
    compile_pages,
    find_specs,
    page_vars_path,
    read_spec,
)
from .preview import build_preview, render_preview
from .provenance import (
    PAYLOAD_KEY,
    payload_stamp,
    process_stamp,
    provenance,
    template_provenance,
)
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
        # Version-bound, not web-bound: a copy is bound by its mapping, so the
        # apply guard runs its version check on this and skips the site check.
        PAYLOAD_KEY: process_stamp(Path(args.bundle).name),
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


def _registry_for(args: argparse.Namespace) -> Registry | None:
    """The findings registry a command consults.

    ``--findings`` names it explicitly and must exist. Without the flag the
    lookup is FINDINGS.md in the working directory, and its absence is
    silence, not an error: a spec compiles the same with or without a
    registry; the registry only adds warnings.
    """
    if args.findings is None:
        return load_findings_if_present(DEFAULT_PATH)
    try:
        return load_findings(args.findings)
    except FileNotFoundError:
        raise ValueError(
            f"no findings registry at {args.findings}: run from the repository root"
            " or pass --findings"
        ) from None


def _cmd_gen_findprobe(args: argparse.Namespace) -> int:
    registry = _registry_for(args)
    if registry is None:
        raise ValueError(
            f"no findings registry at {DEFAULT_PATH}: run from the repository root"
            " or pass --findings"
        )
    print(generate_findprobe_script(registry))
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
    spec = _read_spec_text(args.spec, args)
    cat = parse_discovery(_read_json(args.discovery)) if args.discovery else None
    document = render_preview(build_preview(spec, cat))
    if not args.out:
        sys.stdout.write(document)
        return 0
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(document)
    print(f"preview written: {args.out}")
    return 0


def _read_spec_text(path: str, args: argparse.Namespace) -> Any:
    """Read a spec file through the one read_spec path shared with
    compile-pages (review 2026-09-08 P2-3). Rendering is keyed on operator
    intent — did they pass --vars/--set — never on the resolved map, so a
    stub vars file cannot bake literal {{ }} into a page (P2-2)."""
    flags_given = getattr(args, "vars", None) or getattr(args, "set", None)
    return read_spec(
        Path(path),
        TemplateVars(vars_path=getattr(args, "vars", None), set_pairs=getattr(args, "set", None)),
    ) if flags_given else read_spec(Path(path), None)


def _cmd_compile(args: argparse.Namespace) -> int:
    registry = _registry_for(args)
    # The stamp hashes the discovery file's exact bytes, so read them once and
    # parse those: _read_json would decode and lose the byte identity.
    discovery_bytes = Path(args.discovery).read_bytes()
    discovery = json.loads(discovery_bytes)
    cat = parse_discovery(discovery)
    spec = _read_spec_text(args.spec, args)
    result = compile_page(spec, cat)
    stamp = payload_stamp(
        provenance(discovery_bytes, discovery),
        Path(args.spec).name,
        template=template_provenance(
            getattr(args, "vars", None),
            getattr(args, "set", None),
            own_vars_path=page_vars_path(Path(args.spec)),
        ),
    )
    payload = {
        "schema": "formwork.payload/v1",
        "sourcePage": "(compiled from spec)",
        "title": result.title,
        "canvas": result.canvas,
        "unresolved": [],
        PAYLOAD_KEY: stamp.as_dict(),
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(
        f"payload written: {args.out} ({len(result.canvas)} chars of canvas, "
        f"{len(result.parts)} parts)"
    )
    print(stamp.one_liner())
    for part in result.parts:
        emphasis = part.get("emphasis") or {}
        styled = f", zoneEmphasis {emphasis['zoneEmphasis']}" if emphasis else ""
        print(
            f"  section {part['section']}, column {part['column']}: "
            f"{part['component']} ({part['title']}{styled})"
        )
    # Staleness is a warning, never a refusal: evidence ages, it does not
    # vanish. Each line names the check-id and the command that re-derives it.
    if registry is not None:
        for entry in stale_findings(spec, cat, registry, max_age_days=args.findings_max_age):
            print(f"warning: {entry.message(args.findings_max_age)}", file=sys.stderr)
    return 0


def _cmd_compile_pages(args: argparse.Namespace) -> int:
    specs = find_specs(args.specs)
    if not specs:
        raise ValueError(f"no *.yaml specs under {args.specs}")
    registry = _registry_for(args)
    manifest = compile_pages(
        specs,
        args.discovery,
        args.out_dir,
        PageOptions(
            registry=registry,
            max_age_days=args.findings_max_age,
            template_vars=TemplateVars(vars_path=args.vars, set_pairs=args.set),
        ),
    )
    built = sum(1 for result in manifest.results if result.ok)
    header = manifest.provenance
    print(
        f"compiled {built} of {len(manifest.results)} pages against {args.discovery}"
        f" (web {header.discovery_web_id or '?'}, sha256 {header.discovery_sha256[:12]}):"
        f" manifest {manifest.path}"
    )
    # One line per page, failures and successes alike: a failed page is a
    # row, not an abort, and the other payloads are on disk.
    for result in manifest.results:
        if result.ok:
            plural = "" if result.parts == 1 else "s"
            print(
                f"  ok    {result.spec} -> {result.payload}"
                f" ({result.title}, {result.parts} part{plural})"
            )
        else:
            print(f"  FAIL  {result.spec}: {result.error}")
        for warning in result.warnings:
            print(f"warning: {result.spec}: {warning}", file=sys.stderr)
    return 0 if manifest.ok else 1


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


def _add_findings_args(parser: argparse.ArgumentParser) -> None:
    """The findings-registry flags shared by compile and compile-pages."""
    parser.add_argument(
        "--findings",
        help="the findings registry to judge the spec's evidence by (default:"
        f" {DEFAULT_PATH} in the working directory; silent when absent)",
    )
    parser.add_argument(
        "--findings-max-age",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        metavar="DAYS",
        help="warn when a relied-on measurement is older than this many days"
        f" (default {DEFAULT_MAX_AGE_DAYS})",
    )


def _add_template_args(parser: argparse.ArgumentParser) -> None:
    """The M10 template flags, shared by compile, compile-pages, preview."""
    parser.add_argument(
        "--vars",
        metavar="FILE",
        help="YAML mapping of template variables for the spec file(s);"
        " values are data, the file is safe_load-only",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=None,
        metavar="NAME=VALUE",
        help="one template variable, overriding --vars; repeatable",
    )




def _add_gen_parsers(gen_sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """The `formwork gen *` family (paste-in script generators)."""
    gen_extract = gen_sub.add_parser(
        "extract", help="script that downloads the source page bundle"
    )
    gen_extract.set_defaults(func=_cmd_gen_extract)
    gen_discover = gen_sub.add_parser(
        "discover",
        help="script that discovers placeable components via a scratch page",
    )
    gen_discover.set_defaults(func=_cmd_gen_discover)
    gen_findprobe = gen_sub.add_parser(
        "findprobe",
        help="script that re-runs every measurement FINDINGS.md records and diffs the results",
    )
    gen_findprobe.add_argument(
        "--findings",
        help="the findings registry to re-probe "
        f"(default: {DEFAULT_PATH} in the working directory)",
    )
    gen_findprobe.set_defaults(func=_cmd_gen_findprobe)
    gen_apply = gen_sub.add_parser(
        "apply", help="script that creates the page on the target site"
    )
    gen_apply.add_argument(
        "payload",
        help="payload.json from 'compile', 'compile-pages' or 'process'; its provenance"
        " stamp is what the script checks against the web it runs on",
    )
    gen_apply.add_argument("--name", required=True, help="title for the new page")
    gen_apply.add_argument(
        "--promoted-state",
        type=int,
        default=0,
        choices=(0, 1),
        help="0 = site page (default), 1 = news post. Sent inside the sitepages/pages create"
        " body, where PromotedState 1 persisted (FINDINGS page.promoted-state.create-is-effective,"
        " measured 2026-09-06 beside the Article layout); the post-create item MERGE apply"
        " used before 0.5.0 read back 0 on the Home layout (page.page-state.promoted-state)",
    )
    gen_apply.set_defaults(func=_cmd_gen_apply)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formwork",
        description="SharePoint page copier: extract, process, apply.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("gen", help="generate console paste-in scripts")
    gen_sub = gen.add_subparsers(dest="gen_command", required=True)
    _add_gen_parsers(gen_sub)
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
    _add_findings_args(compile_p)
    _add_template_args(compile_p)
    compile_p.set_defaults(func=_cmd_compile)

    compile_pages_p = sub.add_parser(
        "compile-pages",
        help="compile every *.yaml spec in a directory (or glob) against one discovery"
        " document: one payload per spec plus a manifest",
    )
    compile_pages_p.add_argument(
        "specs", help="directory of page specs, or a glob such as pages/*.yaml"
    )
    compile_pages_p.add_argument(
        "discovery", help="formwork-discovery.json from 'gen discover'"
    )
    compile_pages_p.add_argument(
        "--out-dir",
        default=".",
        help="where to write <spec>.payload.json per spec and formwork-pages.json",
    )
    _add_findings_args(compile_pages_p)
    _add_template_args(compile_pages_p)
    compile_pages_p.set_defaults(func=_cmd_compile_pages)

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
    _add_template_args(preview_p)
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
