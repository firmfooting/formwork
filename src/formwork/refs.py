"""Site-bound reference scanning and rewrite planning.

A modern page is not site-agnostic. Its web parts carry values bound to the
source site: ``links.baseUrl`` in ``serverProcessedContent``, ``siteId`` and
``webId`` properties, list ids and web-relative urls, and searchable plain
texts a human may want to retitle. Formwork scans them all, plans a rewrite,
and applies what resolved, leaving anything unresolved untouched so a
partial mapping degrades to "as extracted" rather than a broken page.

The refs live in the canvas and nowhere else. :func:`scan` reads them from
each web-part control's ``data-sp-webpartdata`` through the canvas model,
addressed by the control's ``instanceId`` plus the path inside that data,
and :func:`apply_plan` writes them back into the same controls in place.
There is no parallel web-part list: the extract paste-in never filled one,
and the rewriter that walked it matched controls on the web part's ``id``,
which is the component type GUID, so two Quick Links on one page both took
the first entry's data (architecture review P1-2, 2026-09-06). A control is
re-serialised only when one of its values actually changed; every other
control keeps its extracted bytes.
"""

from dataclasses import dataclass, field
from typing import Any

from .bundle import Bundle
from .canvas import Canvas, Control

# Property names that hold a GUID binding to a list.
_LIST_ID_KEYS = {"selectedListId", "listId"}
_LIST_URL_KEYS = {"selectedListUrl", "webRelativeListUrl", "listUrl"}
_LIST_VIEW_KEYS = {"selectedViewId", "viewId"}

#: Which key of a ``lists`` mapping entry each list-bound property takes.
_LIST_FIELDS = {
    "selectedListId": "id",
    "listId": "id",
    "selectedListUrl": "url",
    "listUrl": "url",
    "webRelativeListUrl": "webRelativeUrl",
    "selectedViewId": "viewId",
    "viewId": "viewId",
}

#: Ref kinds a mapping can resolve: ``baseUrl``, ``siteId`` and ``webId`` by
#: plain replacement, ``list`` through ``lists``, ``text`` through
#: ``textOverrides``.
REWRITABLE_KINDS = frozenset({"baseUrl", "siteId", "webId", "list", "text"})

#: Ref kinds that are detected and reported, never rewritten. No mapping key
#: exists for them because what a target site wants there is not measured: a
#: ``links`` entry other than ``baseUrl`` (a Quick Links item's
#: ``items[n].sourceItem.url``) may be external, page-relative or list-bound,
#: and an ``imageSources`` entry may be a site asset or a CDN url. They land
#: in ``Plan.unresolved`` so the operator sees them next to the page.
REPORT_ONLY_KINDS = frozenset({"link", "image"})


@dataclass(frozen=True)
class Ref:
    """One site-bound value found on the page, addressed into the canvas."""

    kind: str  # baseUrl | siteId | webId | list | text | link | image
    instance_id: str  # ``instanceId`` of the web-part control carrying it
    section: str  # properties | links | imageSources | searchablePlainTexts
    key: str  # the key inside that section, e.g. "selectedListId"
    value: str
    web_part_title: str

    @property
    def location(self) -> str:
        """The ref's address, e.g. ``webParts[<instanceId>].properties.selectedListId``."""
        return f"webParts[{self.instance_id}].{self.section}.{self.key}"


@dataclass
class Plan:
    applied: list[tuple[Ref, str]] = field(default_factory=list)
    unresolved: list[Ref] = field(default_factory=list)


@dataclass(frozen=True)
class RewriteResult:
    canvas_html: str
    #: ``instanceId`` of every control whose bytes were re-serialised, in
    #: canvas order; each appears once however many of its refs changed.
    rewritten: tuple[str, ...]
    #: Human-readable notes for mirrors a render could not sync (new value
    #: needs HTML escaping a plain-text mirror cannot carry verbatim). The
    #: JSON values are written; the mirror keeps the source site's text, so
    #: the operator must see it rather than a silent stale copy.
    unresolved_extra: tuple[str, ...] = ()


def _instance_id(control: Control) -> str:
    """The address of a web-part control: its ``instanceId``.

    Every measured canvas (the CollabHome capture, the discover probe, the
    compiler's own output) writes the same GUID as the control's ``id`` and
    the web part's ``instanceId``; the control id is the fallback for a
    control whose data lacks the key.
    """
    data = control.web_part_data or {}
    instance = data.get("instanceId")
    if isinstance(instance, str) and instance:
        return instance
    control_id = control.control_data.get("id")
    return control_id if isinstance(control_id, str) else ""


def _controls_by_instance(canvas: Canvas) -> dict[str, Control]:
    """Web-part controls keyed by instanceId, in canvas order.

    A control that cannot be addressed is refused, never skipped. Two controls
    with one instanceId cannot be told apart, so that canvas is refused rather
    than resolved to whichever came first; and a web-part control carrying no
    address at all (neither a web-part ``instanceId`` nor a control-data
    ``id``) is refused too. Skipping the latter silently is the worst of the
    two: every site-bound value the control carries is then neither rewritten
    nor reported as unresolved, so ``process`` declares the copy clean while
    the emitted canvas still points at the source site.
    """
    by_id: dict[str, Control] = {}
    for control in canvas.web_part_controls():
        instance = _instance_id(control)
        if not instance:
            raise ValueError(
                "canvas carries a web-part control with no address (its "
                "web-part data has no instanceId and its control data no id), "
                "so the site-bound values it carries cannot be rewritten or "
                "reported. Re-extract the page, or restore the control's "
                "instanceId."
            )
        if instance in by_id:
            raise ValueError(
                f"canvas carries two web-part controls with instanceId {instance!r}"
            )
        by_id[instance] = control
    return by_id


def _string_items(section: Any) -> list[tuple[str, str]]:
    if not isinstance(section, dict):
        return []
    return [(str(key), val) for key, val in section.items() if isinstance(val, str)]


def _refs_for(instance: str, control: Control) -> list[Ref]:
    data = control.web_part_data or {}
    title = control.web_part_title or ""
    spc = data.get("serverProcessedContent") or {}
    refs: list[Ref] = []

    def add(kind: str, section: str, key: str, value: str) -> None:
        refs.append(Ref(kind, instance, section, key, value, title))

    for key, val in _string_items(spc.get("links")):
        add("baseUrl" if key == "baseUrl" else "link", "links", key, val)
    for key, val in _string_items(spc.get("imageSources")):
        add("image", "imageSources", key, val)
    for key, val in _string_items(spc.get("searchablePlainTexts")):
        add("text", "searchablePlainTexts", key, val)
    for key, val in _string_items(data.get("properties")):
        if key in ("siteId", "webId"):
            add(key, "properties", key, val)
        elif key in _LIST_ID_KEYS or key in _LIST_URL_KEYS or key in _LIST_VIEW_KEYS:
            add("list", "properties", key, val)
    return refs


def scan(bundle: Bundle) -> list[Ref]:
    """Inventory every site-bound value on the page, read from its canvas."""
    return scan_canvas(Canvas.parse(bundle.canvas_html or ""))


def scan_canvas(canvas: Canvas) -> list[Ref]:
    """Inventory every site-bound value in a parsed canvas, control by control."""
    refs: list[Ref] = []
    for instance, control in _controls_by_instance(canvas).items():
        refs.extend(_refs_for(instance, control))
    return refs


def build_plan(refs: list[Ref], mapping: dict[str, Any]) -> Plan:
    """Resolve each ref against the target-site mapping.

    mapping keys:
      baseUrl, siteId, webId  -- plain string replacements
      lists: {sourceWebPartTitle: {id, url, webRelativeUrl, viewId}}
      textOverrides: {sourceText: replacement}

    A ref is resolved when the mapping carries a value for it, the empty
    string included; only an absent entry leaves it unresolved. Refs of a
    :data:`REPORT_ONLY_KINDS` kind are always unresolved: there is no mapping
    key for them by design.
    """
    plan = Plan()
    lists: dict[str, Any] = mapping.get("lists") or {}

    for ref in refs:
        new_value: Any = None
        if ref.kind in ("baseUrl", "siteId", "webId"):
            new_value = mapping.get(ref.kind)
        elif ref.kind == "list":
            entry = lists.get(ref.web_part_title) or {}
            new_value = entry.get(_LIST_FIELDS[ref.key])
        elif ref.kind == "text":
            new_value = (mapping.get("textOverrides") or {}).get(ref.value)
        # REPORT_ONLY_KINDS have no branch: detected, reported, never rewritten.

        if new_value is None:
            plan.unresolved.append(ref)
            continue
        if not isinstance(new_value, str):
            raise ValueError(
                f"mapping value for {ref.location} must be a string, "
                f"got {type(new_value).__name__}"
            )
        plan.applied.append((ref, new_value))

    return plan


def apply_plan(bundle: Bundle, plan: Plan) -> RewriteResult:
    """Write the plan into the bundle's canvas and render it.

    Unresolved refs are left exactly as extracted, and so is every control
    none of whose values changed.
    """
    canvas = Canvas.parse(bundle.canvas_html or "")
    rewritten = apply_plan_to_canvas(canvas, plan)
    rendered = canvas.render()
    # A mirror the render could not sync (new value needs HTML escaping the
    # plain-text mirror cannot carry verbatim) leaves the source site's text
    # in the emitted page while the ref itself applied (review 2026-09-11
    # P2-2 on #26). Render first, then read what it recorded, so the
    # operator sees it instead of a silent stale copy; the JSON values are
    # still written.
    by_id = _controls_by_instance(canvas)
    stale = tuple(
        f"{instance} mirror {name} kept the source site's text: the new value"
        " needs HTML escaping a plain-text mirror cannot carry"
        for instance in rewritten
        for name in by_id[instance].unsynced_mirrors
    )
    return RewriteResult(canvas_html=rendered, rewritten=rewritten, unresolved_extra=stale)


def apply_plan_to_canvas(canvas: Canvas, plan: Plan) -> tuple[str, ...]:
    """Write each applied value into its control's web-part data, in place.

    A control is marked dirty, and so re-serialised on render, only when a
    value it carries actually changed: a mapping that resolves to the
    extracted value leaves the control's raw bytes alone. Returns the
    instanceIds of the controls that changed, in canvas order.
    """
    by_id = _controls_by_instance(canvas)
    changed: set[str] = set()
    for ref, new_value in plan.applied:
        control = by_id.get(ref.instance_id)
        if control is None:
            raise ValueError(
                f"plan names control {ref.instance_id!r}, which the canvas does not carry"
            )
        if _write(control, ref, new_value):
            control.mark_dirty()
            changed.add(ref.instance_id)
    return tuple(instance for instance in by_id if instance in changed)


def _write(control: Control, ref: Ref, new_value: str) -> bool:
    """Set one value on the control's decoded data; True when it differed."""
    data = control.web_part_data
    if data is None:
        raise ValueError(f"control {ref.instance_id!r} carries no web-part data")
    if ref.section == "properties":
        target = data.setdefault("properties", {})
    else:
        target = data.setdefault("serverProcessedContent", {}).setdefault(ref.section, {})
    if target.get(ref.key) == new_value:
        return False
    target[ref.key] = new_value
    return True
