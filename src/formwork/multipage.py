"""Multi-page compilation (M7): many specs, one discovery document.

``formwork compile-pages <dir-or-glob> <discovery>`` compiles every
``*.yaml`` spec under a directory (or matching a glob) against ONE discovery
document. The choices, each pinned by tests/test_multipage.py:

* **One payload per spec, not one combined payload.** Each spec becomes
  ``<stem>.payload.json`` in exactly the shape ``formwork compile`` writes
  (``formwork.payload/v1``), so ``formwork gen apply`` consumes it unchanged
  and one page can be re-applied without the others. A combined payload
  would need a new payload schema and an apply script that creates several
  pages in one paste-in, which nothing has measured.
* **One manifest carries the shared provenance header.** ``formwork-pages.json``
  records the formwork version, the discovery document's sha256, its web id,
  web URL and ``discoveredAt`` once for the run, then one row per spec: ok or
  the error, the payload name, the part count and the staleness warnings.
  Each payload carries the same header plus its spec name and the run's
  compile time under ``provenance`` (M8, :mod:`formwork.provenance`): the
  stamp the apply paste-in checks before it creates anything.
* **Per-page isolation.** A spec that fails (unreadable YAML, a DSL refusal,
  an unknown component) fails alone: its row records the error, no payload is
  written for it, and every other spec still builds. The command exits 1 when
  any page failed.
* **No transaction, no cross-page ordering.** Specs compile in name order
  and are applied one paste-in at a time; nothing links their outcomes.
* **No link resolution.** A text part may link to another page by its
  site-relative URL, and that href is emitted as written. Nothing checks it
  resolves: the file name SharePoint assigns to the target is a page-state
  measurement (the discover probe's ``pageState.samples`` ``fileName``
  topic), not a compile-time fact.
* ``navigation`` on any page is refused by
  :data:`formwork.dsl.UNMEASURED_PAGE_KEYS` with the cited reason.
* **One section model.** Every page goes through
  :func:`formwork.dsl.compile_page`, so its geometry is the section tree of
  :mod:`formwork.sections` (M9); nothing here re-derives a column.
"""

from __future__ import annotations

import glob
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .catalogue import Catalogue, parse_discovery
from .dsl import DslError, compile_page
from .findings import DEFAULT_MAX_AGE_DAYS, Registry, stale_findings
from .provenance import (
    PAYLOAD_KEY,
    Provenance,
    now_iso,
    payload_stamp,
    provenance,
    template_provenance,
)
from .spec_templates import (
    _first_line,
    load_vars,
    parse_set_overrides,
    resolve_variables,
)
from .spec_templates import (
    render_spec_text as render_spec,
)

#: The manifest's schema tag; the payloads keep ``compile``'s.
MANIFEST_SCHEMA = "formwork.pages/v1"


@dataclass(frozen=True)
class TemplateVars:
    """The template layer of a compile-pages run (M10): a shared vars file
    and ``--set`` pairs, resolved once and handed to every spec."""

    vars_path: Path | str | None = None
    set_pairs: Sequence[str] | None = None


@dataclass(frozen=True)
class PageOptions:
    """Everything optional about a compile-pages run: the findings registry
    (plus its staleness age) and the M10 template layer."""

    registry: Registry | None = None
    max_age_days: int = DEFAULT_MAX_AGE_DAYS
    template_vars: TemplateVars | None = None
PAYLOAD_SCHEMA = "formwork.payload/v1"
MANIFEST_NAME = "formwork-pages.json"
#: What a directory argument expands to (its own files only; no recursion).
SPEC_GLOB = "*.yaml"


@dataclass(frozen=True)
class PageResult:
    """One spec's outcome: a payload on disk, or the reason there is none."""

    spec: str
    stem: str
    title: str
    payload_path: Path | None
    parts: int
    canvas_chars: int
    error: str | None
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def payload(self) -> str | None:
        return self.payload_path.name if self.payload_path is not None else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec,
            "title": self.title,
            "payload": self.payload,
            "parts": self.parts,
            "canvasChars": self.canvas_chars,
            "ok": self.ok,
            "error": self.error,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class Manifest:
    provenance: Provenance
    results: tuple[PageResult, ...]
    path: Path

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.results)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "compiledWith": self.provenance.as_dict(),
            "pages": [result.as_dict() for result in self.results],
        }


def find_specs(target: str) -> list[Path]:
    """The spec files a command argument names, in name order.

    A directory means its own ``*.yaml`` files (no recursion); anything else
    is a glob, so a single file or ``pages/*.yaml`` both work. Nothing found
    is an empty list; the command turns that into its one error line.
    """
    path = Path(target)
    if path.is_dir():
        return sorted(p for p in path.glob(SPEC_GLOB) if p.is_file())
    return sorted(Path(p) for p in glob.glob(target) if Path(p).is_file())


def payload_name(spec_path: Path) -> str:
    return f"{spec_path.stem}.payload.json"


_VARS_KEY = re.compile(r"^vars:[ \t]*([^\n#]*?)[ \t]*(?:#.*)?$", re.MULTILINE)


def page_vars_name(text: str, path: Path) -> str | None:
    """The page-local ``vars:`` file a spec's ``text`` names, as written.

    The one line-anchored discovery :func:`read_spec` uses (``re.match``
    with ``(?m)`` never matched past line 1, review P1-5), refusing
    ambiguity: more than one top-level ``vars:`` key is a spec error, not
    a silent pick. Exposed so the payload stamp can record the same file
    the page actually rendered from (M10 P2-5).
    """
    matches = _VARS_KEY.findall(text)
    if len(matches) > 1:
        raise DslError(f"{path.name}: more than one top-level 'vars:' key; keep one")
    return matches[0].strip().strip("'\"") if matches else None


def page_vars_path(path: Path) -> Path | None:
    """The resolved page-local ``vars:`` file a spec names, or ``None``.

    ``read_spec`` has already loaded and validated it by the time a stamp
    is built, so a caller reaches this only for a spec that read cleanly.
    """
    path = Path(path)
    own = page_vars_name(path.read_text(encoding="utf-8"), path)
    return (path.parent / own).resolve() if own is not None else None


def read_spec(
    path: Path,
    template_vars: TemplateVars | None = None,
) -> dict[str, Any]:
    """Read one page spec, rendering it as a template when the operator
    supplied template flags.

    Contract (review 2026-09-08): rendering is keyed on OPERATOR INTENT —
    ``template_vars`` carries the ``--vars``/``--set`` flags — never on the
    resolved map's contents. With no flags the file's bytes go to the YAML
    parser unchanged, so a spec containing literal Jinja-ish text keeps
    working (no-vars-no-change).

    Precedence, highest wins: ``--set`` > the page's own ``vars:`` file >
    the shared ``--vars`` file. A page vars file naming a key that an
    explicit ``--set`` also names is refused: the operator's explicit
    override must hold, not silently lose.

    The ``vars:`` key must sit at the TOP of the spec, column 0, before
    the first document content; it is consumed here and never reaches
    ``compile_page``.
    """
    tv = template_vars
    set_map = parse_set_overrides(tv.set_pairs) if tv else {}
    shared = resolve_variables(tv.vars_path, None) if tv and tv.vars_path else {}
    # When any flag was given, the shared layer exists even if the vars
    # file resolved empty: an empty map with flags in play still renders,
    # so StrictUndefined can name what is missing (P2-2's mirror).
    shared_vars: dict[str, Any] | None = (
        {**shared, **set_map} if tv and (tv.vars_path or tv.set_pairs) else None
    )

    text = Path(path).read_text(encoding="utf-8")
    # A page's own ``vars:`` key has to be findable BEFORE rendering — the
    # template text does not parse as YAML while {{ }} placeholders are in
    # it. The discovery is shared with the payload stamp, which records the
    # file this page renders from (:func:`page_vars_name`).
    own = page_vars_name(text, path)
    variables: dict[str, Any] = dict(shared_vars or {})
    if own is not None:
        own_path = (path.parent / own).resolve()
        own_values = load_vars(own_path)
        clashing = sorted(k for k in own_values if k in set_map)
        if clashing:
            raise DslError(
                f"{path.name}: its vars file {own} would override the"
                f" explicit --set value(s) for {', '.join(clashing)};"
                " remove them from one side"
            )
        variables.update(own_values)
        # --set outranks the page file; re-assert after the merge.
        for k, v in set_map.items():
            variables[k] = v
    # Rendering happens whenever the operator supplied template flags (even
    # with an empty resulting map: StrictUndefined then names what is
    # missing). With no flags, the file is data: a literal {{ ... }} in a
    # spec with no --vars passes through untouched.
    if shared_vars is not None or own is not None:
        rendered = render_spec(text, variables, path.name)
        try:
            spec = yaml.safe_load(rendered)
        except yaml.YAMLError as exc:
            where = _first_line(exc)
            raise DslError(
                f"{path.name}: template rendered to invalid YAML ({where})"
            ) from None
    else:
        spec = yaml.safe_load(text)
    if not isinstance(spec, dict):
        raise DslError(
            f"a spec is a mapping with 'page' and 'sections', not {type(spec).__name__}"
        )
    spec.pop("vars", None)
    return spec


def compile_pages(
    spec_paths: Sequence[Path],
    discovery_path: Path | str,
    out_dir: Path | str,
    options: PageOptions | None = None,
) -> Manifest:
    """Compile every spec against the one discovery document into ``out_dir``.

    Refuses before writing anything when two specs would share a payload
    name (same stem in different directories); otherwise every spec gets a
    row, the failures alongside the successes.
    """
    specs = [Path(p) for p in spec_paths]
    seen: dict[str, Path] = {}
    for spec_path in specs:
        name = payload_name(spec_path)
        if name in seen:
            raise ValueError(
                f"{seen[name]} and {spec_path} share the payload name {name}; rename one"
            )
        seen[name] = spec_path
    # The exact bytes, hashed as read: the stamp names this file, not a
    # re-serialisation of it (review 2026-09-07 P2-7).
    discovery_bytes = Path(discovery_path).read_bytes()
    discovery = json.loads(discovery_bytes)
    cat = parse_discovery(discovery)
    header = provenance(discovery_bytes, discovery)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # One compile time for the run, so every payload it writes carries the
    # same stamp and differs only in its spec name.
    opts = options or PageOptions()
    run = _Run(
        cat,
        out,
        header,
        now_iso(),
        opts.registry,
        opts.max_age_days,
        opts.template_vars,
    )
    results = tuple(_compile_one(spec_path, run) for spec_path in specs)
    manifest = Manifest(provenance=header, results=results, path=out / MANIFEST_NAME)
    manifest.path.write_text(json.dumps(manifest.as_dict(), indent=2) + "\n", encoding="utf-8")
    return manifest


@dataclass(frozen=True)
class _Run:
    """What every spec of one compile-pages run shares."""

    cat: Catalogue
    out: Path
    header: Provenance
    compiled_at: str
    registry: Registry | None
    max_age_days: int
    template_vars: TemplateVars | None


def _compile_one(spec_path: Path, run: _Run) -> PageResult:
    try:
        spec = read_spec(spec_path, run.template_vars)
        compiled = compile_page(spec, run.cat)
    except yaml.YAMLError as exc:
        return _failed(spec_path, "invalid YAML: " + " ".join(str(exc).split()))
    except ValueError as exc:  # DslError, TextError, a refused discovery document
        return _failed(spec_path, str(exc))
    payload = {
        "schema": PAYLOAD_SCHEMA,
        "sourcePage": f"(compiled from spec {spec_path.name})",
        "title": compiled.title,
        "canvas": compiled.canvas,
        "unresolved": [],
        PAYLOAD_KEY: payload_stamp(
            run.header,
            spec_path.name,
            run.compiled_at,
            template=template_provenance(
                run.template_vars.vars_path if run.template_vars else None,
                run.template_vars.set_pairs if run.template_vars else None,
                own_vars_path=page_vars_path(spec_path),
            ),
        ).as_dict(),
    }
    payload_path = run.out / payload_name(spec_path)
    with open(payload_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    warnings: tuple[str, ...] = ()
    if run.registry is not None:
        warnings = tuple(
            entry.message(run.max_age_days)
            for entry in stale_findings(
                spec, run.cat, run.registry, max_age_days=run.max_age_days
            )
        )
    return PageResult(
        spec=spec_path.name,
        stem=spec_path.stem,
        title=compiled.title,
        payload_path=payload_path,
        parts=len(compiled.parts),
        canvas_chars=len(compiled.canvas),
        error=None,
        warnings=warnings,
    )


def _failed(spec_path: Path, error: str) -> PageResult:
    return PageResult(
        spec=spec_path.name,
        stem=spec_path.stem,
        title="",
        payload_path=None,
        parts=0,
        canvas_chars=0,
        error=error,
    )
