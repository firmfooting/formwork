"""Site-bound reference scanning and rewrite planning.

A modern page is not site-agnostic. Its web parts carry values bound to the
source site: ``links.baseUrl`` in ``serverProcessedContent``, ``siteId`` and
``webId`` properties, list ids and web-relative urls, and searchable plain
texts a human may want to retitle. Formwork scans them all, plans a rewrite,
and applies what resolved — leaving anything unresolved untouched so a
partial mapping degrades to "as extracted" rather than a broken page.
"""

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from .bundle import Bundle
from .canvas import Canvas

# Property names that hold a GUID binding to a list.
_LIST_ID_KEYS = {"selectedListId", "listId"}
_LIST_URL_KEYS = {"selectedListUrl", "webRelativeListUrl", "listUrl"}
_LIST_VIEW_KEYS = {"selectedViewId", "viewId"}


@dataclass
class Ref:
    """One site-bound value found on the page."""

    kind: str  # baseUrl | siteId | webId | list | text | image
    location: str  # e.g. "webParts[3].properties.selectedListId"
    value: str
    web_part_title: str


@dataclass
class Plan:
    applied: list[tuple[Ref, str]] = field(default_factory=list)
    unresolved: list[Ref] = field(default_factory=list)


@dataclass
class RewriteResult:
    web_parts: list[dict[str, Any]]
    canvas_html: str


def _spc_entries(
    bundle: Bundle, section: str
) -> "list[tuple[int, dict[str, Any], str, Any]]":
    out: list[tuple[int, dict[str, Any], str, Any]] = []
    for i, wp in enumerate(bundle.web_parts):
        spc = wp.get("serverProcessedContent") or {}
        for key, val in (spc.get(section) or {}).items():
            out.append((i, wp, key, val))
    return out


def scan(bundle: Bundle) -> list[Ref]:
    """Inventory every site-bound value on the page."""
    refs: list[Ref] = []

    def add(kind: str, location: str, value: Any, title: str) -> None:
        refs.append(Ref(kind=kind, location=location, value=value, web_part_title=title))

    for i, wp, key, val in _spc_entries(bundle, "links"):
        if key == "baseUrl":
            add("baseUrl", f"webParts[{i}].links.baseUrl", val, wp.get("title", ""))
        else:
            add("link", f"webParts[{i}].links.{key}", val, wp.get("title", ""))

    for i, wp, key, val in _spc_entries(bundle, "imageSources"):
        add("image", f"webParts[{i}].imageSources.{key}", val, wp.get("title", ""))

    for i, wp, key, val in _spc_entries(bundle, "searchablePlainTexts"):
        add("text", f"webParts[{i}].searchablePlainTexts.{key}", val, wp.get("title", ""))

    for i, wp in enumerate(bundle.web_parts):
        title = wp.get("title", "")
        for key, val in (wp.get("properties") or {}).items():
            loc = f"webParts[{i}].properties.{key}"
            if key in ("siteId", "webId") and isinstance(val, str):
                add(key, loc, val, title)
            elif isinstance(val, str) and (
                key in _LIST_ID_KEYS
                or key in _LIST_URL_KEYS
                or key in _LIST_VIEW_KEYS
            ):
                add("list", loc, val, title)

    return refs


def build_plan(refs: list[Ref], mapping: dict[str, Any]) -> Plan:
    """Resolve each ref against the target-site mapping.

    mapping keys:
      baseUrl, siteId, webId  -- plain string replacements
      lists: {sourceListTitle: {id, url, webRelativeUrl, viewId}}
      textOverrides: {sourceText: replacement}
    """
    plan = Plan()
    lists: dict[str, Any] = mapping.get("lists") or {}

    for ref in refs:
        new_value = None
        if ref.kind == "baseUrl":
            new_value = mapping.get("baseUrl")
        elif ref.kind == "siteId":
            new_value = mapping.get("siteId")
        elif ref.kind == "webId":
            new_value = mapping.get("webId")
        elif ref.kind == "list":
            entry = lists.get(ref.web_part_title)
            if entry:
                key = ref.location.rsplit(".", 1)[-1]
                field_map = {
                    "selectedListId": "id",
                    "listId": "id",
                    "selectedListUrl": "url",
                    "listUrl": "url",
                    "webRelativeListUrl": "webRelativeUrl",
                    "selectedViewId": "viewId",
                    "viewId": "viewId",
                }
                new_value = entry.get(field_map[key])
        elif ref.kind == "text":
            new_value = (mapping.get("textOverrides") or {}).get(ref.value)

        if new_value:
            plan.applied.append((ref, new_value))
        else:
            plan.unresolved.append(ref)

    return plan


def apply_plan(bundle: Bundle, plan: Plan) -> RewriteResult:
    """Mutate web parts per the plan, then regenerate the canvas.

    Unresolved refs are left exactly as extracted.
    """
    web_parts = copy.deepcopy(bundle.web_parts)

    for ref, new_value in plan.applied:
        wp = web_parts[_parse_index(ref.location)]
        section, prop = _split_location(ref.location)
        if section == "properties":
            wp.setdefault("properties", {})[prop] = new_value
        elif section == "links":
            wp.setdefault("serverProcessedContent", {}).setdefault("links", {})[prop] = (
                new_value
            )
        elif section == "imageSources":
            wp.setdefault("serverProcessedContent", {}).setdefault(
                "imageSources", {}
            )[prop] = new_value
        elif section == "searchablePlainTexts":
            wp.setdefault("serverProcessedContent", {}).setdefault(
                "searchablePlainTexts", {}
            )[prop] = new_value

    canvas = Canvas.parse(bundle.canvas_html or "")
    for control in canvas.web_part_controls():
        wpd = control.web_part_data
        if wpd is None:
            continue
        for candidate in web_parts:
            if candidate.get("id") == wpd.get("id"):
                control.web_part_data = candidate
                control.mark_dirty()
                break

    return RewriteResult(
        web_parts=web_parts,
        canvas_html=canvas.render(),
    )


def _parse_index(location: str) -> int:
    m = re.search(r"webParts\[(\d+)\]", location)
    if m is None:
        raise ValueError(f"cannot parse web part index from location: {location!r}")
    return int(m.group(1))


def _split_location(location: str) -> tuple[str, str]:
    after = location.split("].", 1)[1]
    section, prop = after.rsplit(".", 1)
    return section, prop
