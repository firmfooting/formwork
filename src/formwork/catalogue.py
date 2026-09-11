"""Component catalogue parsed from a discovery bundle.

``GetClientSideWebParts`` (measured 2026-09-06, shauntestazure sandbox) returns
every placeable client-side component with an embedded ``Manifest`` JSON
string: alias, title, component type, hidden flag, and preconfigured entries.
A component's ``title`` and ``default_properties`` are its *first* entry's —
what the alias names — and :meth:`Component.as_entry` reads any later
entry's own pair, the web part picker's other variants (the live
ListWebPart's second entry is ``"Document library"``). The catalogue is the
authority the page DSL compiles against — nothing is placed that the live
site did not declare placeable.

The discover script also places two text controls (``controlType`` 4, not
web parts) with known HTML and reads back what SharePoint persisted. They
arrive under the additive ``textControls`` key and are carried here as
:class:`TextControlSample` pairs so the shape the compiler emits can be
checked against a measurement rather than a guess. A discovery document from
before that probe has no such key and parses exactly as it did.

The M5 probes (discover template, 2026-09-06) add three more additive keys,
all measurement and no gate: ``webpartProperties`` (each representative web
part placed twice, defaults and one modified flat property), ``layoutVariants``
(the 8/4 and 4/8 factor orders and a control in column 2) and
``listBindings`` (library, list and quick-links parts bound to two fixture
containers the script creates and recycles). They are carried here as
:class:`PropertySample`, :class:`LayoutVariant`, :class:`ProbeList` and
:class:`ListBinding`, paired by control id the same tolerant way. Nothing in
the DSL reads them until a live run has been folded into a fixture.

The M7 page-state lane (discover template, 2026-09-07) adds ``pageState``:
real scratch pages created with an explicit file name, a non-default layout,
a promoted state, a description and banner, and one checked out and
published, each read back as a page entity and a list item, then recycled.
They are carried here as :class:`PageStateSample` rows (requested versus
persisted, keyed by page id) plus the ``unmeasured`` topics the lane names
rather than guesses at; the same tolerance applies, so a document from
before the lane parses unchanged.

Persisted blocks are decoded through :mod:`formwork.canvas`, the one canvas
serialiser (M9, review 2026-09-06 P2-7): the catalogue keeps the colon fold
(the one measured rewrite) and the pairing, and reads a stored block's
attributes with the same parser the compiler's output would be read with.
The layout probe's section labels are resolved against the shared
:mod:`formwork.sections` table, so the factor set a layout variant measured
is the same constant the compiler places by.
"""

import json
import re
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse

from .canvas import COLON_ENTITY, Canvas
from .sections import LAYOUT_VARIANT_FACTORS

#: A layout-probe row's label: ``<section>-col<n>`` (``_probe_legs.js.j2``).
_LAYOUT_LABEL_RE = re.compile(r"^(?P<section>.+)-col(?P<column>\d+)$")


@dataclass(frozen=True)
class Component:
    component_id: str
    alias: str
    title: str
    hidden: bool
    component_type: int
    default_properties: dict[str, Any]
    description: str = ""
    entry_titles: tuple[str, ...] = ()
    entry_properties: tuple[dict[str, Any], ...] = ()

    def entry_count(self) -> int:
        return len(self.entry_titles)

    def as_entry(self, title: str) -> "Component":
        """This component as the preconfigured entry titled ``title``.

        ``title`` and ``default_properties`` are the *first* entry's (the
        component's own, what the alias names). A later entry carries its
        own pair: the live catalogue's ListWebPart declares ``"List"`` and
        ``"Document library"`` (``tests/fixtures/discovery.m5.json``), and
        the M5 probe placed the second one by index and SharePoint stored it
        as ``title: "Document library"`` with ``isDocumentLibrary: true``
        (``listBindings.persisted[0]``). A title this component does not
        carry returns the component unchanged.
        """
        if title in self.entry_titles:
            index = self.entry_titles.index(title)
            if index < len(self.entry_properties):
                return replace(
                    self,
                    title=title,
                    default_properties=dict(self.entry_properties[index]),
                )
        return self


@dataclass(frozen=True)
class TextControlSample:
    """One text control the discover script placed, as sent and as kept.

    ``requested`` is the canvas block the script wrote; ``persisted`` is the
    block SharePoint stored for the same control id, verbatim, or None when
    the readback did not contain it. The persisted bytes are the measurement
    of the text-control shape; nothing here interprets them.
    """

    control_id: str
    html: str
    requested: str
    persisted: str | None

    def persisted_matches(self) -> bool | None:
        """Whether SharePoint kept this sample byte-for-byte after normalising.

        Measured live (shauntestazure, 2026-09-06): SharePoint rewrites ``:``
        as ``&#58;`` inside a text control's inner HTML — the same entity
        style the canvas attributes use — and leaves everything else
        byte-identical. So equality is judged with the colon's spelling
        folded on BOTH sides, and nothing else folded: the requested block
        already carries ``&#58;`` in its control-data attribute, so folding
        the persisted side alone un-escapes that attribute on one side only
        and every real sample compared unequal (found 2026-09-06 against the
        live document; the fixture's sample had no colon to rewrite). Any
        other difference is a real shape change and returns False.

        None when the sample was never persisted (or the stored bytes could
        not be read), in which case no claim is made.
        """
        return _blocks_match(self.requested, self.persisted)


def _fold_colons(block: str) -> str:
    """The one measured normalisation, folded: ``&#58;`` and ``:`` read alike."""
    return block.replace(COLON_ENTITY, ":")


def _blocks_match(requested: str, persisted: str | None) -> bool | None:
    """The same judgement :meth:`TextControlSample.persisted_matches` makes,
    shared by every M5 sample: None when nothing was read back, True when
    the stored block equals the requested one with the colon fold applied
    to both sides, False on any other difference."""
    if persisted is None:
        return None
    if persisted == requested:
        return True
    return _fold_colons(persisted) == _fold_colons(requested)


@dataclass(frozen=True)
class PropertySample:
    """One web part the M5 property probe placed, as sent and as kept.

    Each representative part is placed twice: ``variant`` ``"default"``
    carries the manifest's first preconfigured entry unchanged, and
    ``"modified"`` carries ONE flat, visible property (``property_path``)
    changed from ``old_value`` to ``new_value``. ``stored_value`` is what the
    readback found at that path in the persisted webpartdata, with
    ``stored_present`` telling a stored ``null`` apart from a dropped key.
    """

    component: str
    control_id: str
    variant: str
    property_path: str
    old_value: Any
    new_value: Any
    requested: str
    persisted: str | None
    stored_value: Any = None
    stored_present: bool = False

    def persisted_matches(self) -> bool | None:
        """Whether the whole control block survived the item MERGE."""
        return _blocks_match(self.requested, self.persisted)

    def value_round_tripped(self) -> bool | None:
        """Whether the property read back equal to what was sent.

        None when the control was never read back; False when the key was
        dropped or its value changed; True when it came back equal.
        """
        if self.persisted is None:
            return None
        return self.stored_present and self.stored_value == self.new_value


@dataclass(frozen=True)
class LayoutVariant:
    """One control the M5 layout probe placed, as sent and as kept.

    ``control_data`` is the position the script wrote (the factor of the
    column the control sits in, and its index within that column), so a
    reordered or re-factored readback is attributable to one variant.

    The label is ``<section>-col<n>``; ``section`` and ``column`` split it,
    and ``factors`` is the factor set that probe section was laid out with,
    from the shared :data:`formwork.sections.LAYOUT_VARIANT_FACTORS` table
    (None for a label the table does not know). A row carries only its own
    control's ``sectionFactor``, which is ``factors[column - 1]``.
    """

    label: str
    control_id: str
    control_data: dict[str, Any]
    requested: str
    persisted: str | None

    @property
    def section(self) -> str:
        match = _LAYOUT_LABEL_RE.match(self.label)
        return match.group("section") if match else self.label

    @property
    def column(self) -> int | None:
        match = _LAYOUT_LABEL_RE.match(self.label)
        return int(match.group("column")) if match else None

    @property
    def factors(self) -> tuple[int, ...] | None:
        return LAYOUT_VARIANT_FACTORS.get(self.section)

    @property
    def section_factor(self) -> int | None:
        return _position_int(self.control_data, "sectionFactor")

    @property
    def control_index(self) -> int | None:
        return _position_int(self.control_data, "controlIndex")

    def persisted_matches(self) -> bool | None:
        return _blocks_match(self.requested, self.persisted)


def _position_int(control_data: dict[str, Any], key: str) -> int | None:
    position = control_data.get("position")
    if not isinstance(position, dict):
        return None
    value = position.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class ProbeList:
    """One fixture container the M5 binding probe created, and its fate.

    ``created`` False means the bindings that targeted it were skipped and
    ``reason`` carries the server's message; ``recycled`` is None when no
    recycle was attempted (nothing to recycle), else the outcome.
    """

    key: str
    title: str
    base_template: int
    created: bool
    recycled: bool | None
    reason: str
    list_id: str | None = None
    server_relative_url: str | None = None
    web_relative_url: str | None = None
    default_view_id: str | None = None
    default_view_url: str | None = None
    recycle_reason: str = ""


@dataclass(frozen=True)
class ListBinding:
    """One list-bound web part the M5 binding probe placed, sent and kept.

    ``target`` is the :attr:`ProbeList.key` the part was bound to;
    ``list_id`` and ``list_url`` are that container's real id and
    server-relative URL as read from ``_api/web/lists``. ``web_part_data``
    is the webpartdata the script wrote and ``stored_web_part_data`` the
    webpartdata of the persisted block, decoded by :mod:`formwork.canvas`,
    or None when the control was not read back.
    """

    label: str
    component: str
    entry: int
    control_id: str
    target: str
    list_id: str
    list_url: str
    web_part_data: dict[str, Any]
    requested: str
    persisted: str | None
    stored_web_part_data: dict[str, Any] | None = None

    @property
    def properties(self) -> dict[str, Any]:
        return _properties_of(self.web_part_data) or {}

    @property
    def stored_properties(self) -> dict[str, Any] | None:
        if self.stored_web_part_data is None:
            return None
        return _properties_of(self.stored_web_part_data)

    def persisted_matches(self) -> bool | None:
        return _blocks_match(self.requested, self.persisted)


def _properties_of(web_part_data: dict[str, Any]) -> dict[str, Any] | None:
    properties = web_part_data.get("properties")
    return properties if isinstance(properties, dict) else None


def _stored_web_part_data(block: str | None) -> dict[str, Any] | None:
    """The webpartdata of a persisted block, decoded by the canvas parser.

    The probe's own DOMParser decode of the same bytes rides along in the
    row as ``webPartData``; this reads the block instead, through the one
    serialiser (tests/test_sections.py pins the two equal on the M5
    fixture). None when nothing was read back, the block holds no web-part
    control, or its attribute is not JSON.
    """
    if block is None:
        return None
    try:
        web_parts = Canvas.parse(block).web_part_controls()
    except ValueError:
        return None
    first = web_parts[0] if web_parts else None
    if first is None or first.web_part_data is None:
        return None
    return dict(first.web_part_data)


@dataclass(frozen=True)
class PageStateSample:
    """One scratch page the M7 page-state probe created, as asked and as kept.

    ``requested`` holds what the probe sent, by step (``create`` is the
    sitepages/pages POST body; later steps are the item MERGE fields or the
    page-model action bodies). ``persisted`` holds what it read back, by
    step (``created``, ``read``, ``afterMerge``, ``afterPublish``...), each
    read a page-entity view, a list-item view and the non-fatal permission
    read. ``topics`` names the questions the sample answers (fileName,
    description, bannerImageUrl, layout, promotedState, publishState,
    permissionInheritance); one page can answer several. A sample whose
    create was refused has ``page_id`` None, ``ok`` False and ``reason`` the
    server's message; ``recycled`` is None when no recycle was attempted.
    """

    label: str
    topics: tuple[str, ...]
    page_id: int | None
    requested: dict[str, Any]
    persisted: dict[str, Any]
    ok: bool
    status: int
    reason: str
    recycled: bool | None

    def requested_value(self, path: str) -> Any:
        """The value at a dotted path into ``requested``; None when absent."""
        return _walk(self.requested, path)

    def persisted_value(self, path: str) -> Any:
        """The value at a dotted path into ``persisted``; None when absent."""
        return _walk(self.persisted, path)


def _walk(node: Any, path: str) -> Any:
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


@dataclass(frozen=True)
class Catalogue:
    components: tuple[Component, ...]
    text_controls: tuple[TextControlSample, ...] = ()
    property_samples: tuple[PropertySample, ...] = ()
    layout_variants: tuple[LayoutVariant, ...] = ()
    probe_lists: tuple[ProbeList, ...] = ()
    list_bindings: tuple[ListBinding, ...] = ()
    page_state: tuple[PageStateSample, ...] = ()
    page_state_unmeasured: tuple[str, ...] = ()
    web_url: str = ""

    @property
    def web_server_relative_path(self) -> str:
        """The web's path (e.g. '/sites/T'), from the discovery web URL.

        This is what a bound part's server-relative ``selectedListUrl`` is
        relative to: measured (discovery.m5.json listBindings, 2026-09-07)
        storing selectedListUrl server-relative against the web root and
        webRelativeListUrl web-relative.
        """
        return urlparse(self.web_url).path.rstrip("/")

    @property
    def count(self) -> int:
        return len(self.components)

    def property_samples_for(self, component: str) -> tuple[PropertySample, ...]:
        return tuple(s for s in self.property_samples if s.component == component)

    def layout_variant(self, label: str) -> LayoutVariant | None:
        for variant in self.layout_variants:
            if variant.label == label:
                return variant
        return None

    def probe_list(self, key: str) -> ProbeList | None:
        for probe in self.probe_lists:
            if probe.key == key:
                return probe
        return None

    def page_state_sample(self, label: str) -> PageStateSample | None:
        for sample in self.page_state:
            if sample.label == label:
                return sample
        return None

    def page_state_for(self, topic: str) -> tuple[PageStateSample, ...]:
        return tuple(s for s in self.page_state if topic in s.topics)

    def by_alias(self, alias: str) -> Component:
        for c in self.components:
            if c.alias == alias:
                return c
        raise KeyError(f"component alias not in catalogue: {alias!r}")

    def by_title(self, title: str) -> Component:
        """A component by its own title, or by any preconfigured entry's.

        A manifest's entries are the web part picker's variants and each
        carries its own title and defaults, so a spec naming the title the
        picker showed — the live ListWebPart's second entry, ``"Document
        library"`` — resolves to that entry with its measured defaults
        (:meth:`Component.as_entry`). A title more than one component
        carries is refused, as before.
        """
        matches = [c for c in self.components if c.title == title]
        if not matches:
            matches = [c for c in self.components if title in c.entry_titles]
        if not matches:
            raise KeyError(f"component title not in catalogue: {title!r}")
        if len(matches) > 1:
            raise KeyError(
                f"component title {title!r} is ambiguous across "
                f"{len(matches)} components; use the alias instead"
            )
        return matches[0].as_entry(title)


def parse_discovery(discovery: dict[str, Any]) -> Catalogue:
    """Build a catalogue from a formwork discovery document."""
    if discovery.get("schema") != "formwork.discovery/v1":
        raise ValueError(
            f"unsupported discovery schema: {discovery.get('schema')!r} "
            "(expected 'formwork.discovery/v1')"
        )

    components: list[Component] = []
    for raw in discovery.get("components", []):
        manifest = json.loads(raw.get("Manifest") or "{}")
        entries = manifest.get("preconfiguredEntries") or []
        first = entries[0] if entries else {}
        entry_titles = tuple(
            (entry.get("title") or {}).get("default", "") for entry in entries
        )
        entry_properties = tuple(
            dict(entry.get("properties") or {}) for entry in entries
        )
        components.append(
            Component(
                component_id=raw.get("Id") or manifest.get("id", ""),
                alias=manifest.get("alias", ""),
                title=(first.get("title") or {}).get("default", ""),
                hidden=bool(manifest.get("isHidden", False)),
                component_type=int(raw.get("ComponentType", 0)),
                default_properties=dict(first.get("properties") or {}),
                description=(first.get("description") or {}).get("default", ""),
                entry_titles=entry_titles,
                entry_properties=entry_properties,
            )
        )
    bindings = discovery.get("listBindings")
    page_state = discovery.get("pageState")
    web = discovery.get("web") or {}
    return Catalogue(
        components=tuple(components),
        text_controls=_text_controls(discovery.get("textControls")),
        property_samples=_property_samples(discovery.get("webpartProperties")),
        layout_variants=_layout_variants(discovery.get("layoutVariants")),
        probe_lists=_probe_lists(bindings),
        list_bindings=_list_bindings(bindings),
        page_state=_page_state(page_state),
        page_state_unmeasured=_page_state_unmeasured(page_state),
        web_url=web.get("url", "") if isinstance(web, dict) else "",
    )


def _rows(raw: Any, key: str) -> list[dict[str, Any]]:
    """The dict rows under ``raw[key]``; anything else reads as no rows."""
    if not isinstance(raw, dict):
        return []
    rows = raw.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _persisted_by_id(raw: Any) -> dict[str, dict[str, Any]]:
    """Persisted rows keyed by control id; rows without a canvas are dropped."""
    return {
        str(row.get("id", "")): row
        for row in _rows(raw, "persisted")
        if isinstance(row.get("canvas"), str)
    }


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int_or(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text_controls(raw: Any) -> tuple[TextControlSample, ...]:
    """Pair each requested text control with its persisted block by id.

    Tolerant by design: the key is additive, and a document that predates
    the probe (or a run whose readback lost the controls) yields an empty
    tuple or samples with ``persisted`` None, never an error.
    """
    if not isinstance(raw, dict):
        return ()
    persisted_by_id: dict[str, str] = {}
    persisted_raw = raw.get("persisted")
    if not isinstance(persisted_raw, list):
        persisted_raw = []
    for kept in persisted_raw:
        if isinstance(kept, dict) and isinstance(kept.get("canvas"), str):
            persisted_by_id[str(kept.get("id", ""))] = kept["canvas"]
    samples: list[TextControlSample] = []
    requested_raw = raw.get("requested")
    if not isinstance(requested_raw, list):
        requested_raw = []
    for sent in requested_raw:
        if not isinstance(sent, dict):
            continue
        control_id = str(sent.get("id", ""))
        samples.append(
            TextControlSample(
                control_id=control_id,
                html=str(sent.get("html", "")),
                requested=str(sent.get("canvas", "")),
                persisted=persisted_by_id.get(control_id),
            )
        )
    return tuple(samples)


def _property_samples(raw: Any) -> tuple[PropertySample, ...]:
    """Pair each M5 property probe with its persisted block and stored value.

    As tolerant as :func:`_text_controls`: the key is additive, and a row
    the readback lost yields ``persisted`` None with no stored value.
    """
    persisted_by_id = _persisted_by_id(raw)
    samples: list[PropertySample] = []
    for sent in _rows(raw, "requested"):
        control_id = str(sent.get("id", ""))
        kept = persisted_by_id.get(control_id)
        stored_present = bool(kept.get("present", "storedValue" in kept)) if kept else False
        samples.append(
            PropertySample(
                component=str(sent.get("component", "")),
                control_id=control_id,
                variant=str(sent.get("variant", "")),
                property_path=str(sent.get("propertyPath", "")),
                old_value=sent.get("oldValue"),
                new_value=sent.get("newValue"),
                requested=str(sent.get("canvas", "")),
                persisted=kept["canvas"] if kept else None,
                stored_value=kept.get("storedValue") if kept else None,
                stored_present=stored_present,
            )
        )
    return tuple(samples)


def _layout_variants(raw: Any) -> tuple[LayoutVariant, ...]:
    """Pair each M5 layout variant with its persisted block by control id."""
    persisted_by_id = _persisted_by_id(raw)
    variants: list[LayoutVariant] = []
    for sent in _rows(raw, "requested"):
        control_id = str(sent.get("id", ""))
        kept = persisted_by_id.get(control_id)
        variants.append(
            LayoutVariant(
                label=str(sent.get("label", "")),
                control_id=control_id,
                control_data=_dict_or_empty(sent.get("controlData")),
                requested=str(sent.get("canvas", "")),
                persisted=kept["canvas"] if kept else None,
            )
        )
    return tuple(variants)


def _probe_lists(raw: Any) -> tuple[ProbeList, ...]:
    """The fixture containers the M5 binding probe created, with their fate."""
    probes: list[ProbeList] = []
    for row in _rows(raw, "fixtures"):
        recycled = row.get("recycled")
        probes.append(
            ProbeList(
                key=str(row.get("key", "")),
                title=str(row.get("title", "")),
                base_template=_int_or(row.get("baseTemplate"), 0),
                created=bool(row.get("created", False)),
                recycled=recycled if isinstance(recycled, bool) else None,
                reason=str(row.get("reason") or ""),
                list_id=_optional_str(row.get("id")),
                server_relative_url=_optional_str(row.get("serverRelativeUrl")),
                web_relative_url=_optional_str(row.get("webRelativeUrl")),
                default_view_id=_optional_str(row.get("defaultViewId")),
                default_view_url=_optional_str(row.get("defaultViewUrl")),
                recycle_reason=str(row.get("recycleReason") or ""),
            )
        )
    return tuple(probes)


def _list_bindings(raw: Any) -> tuple[ListBinding, ...]:
    """Pair each M5 list binding with its persisted block and webpartdata."""
    persisted_by_id = _persisted_by_id(raw)
    bindings: list[ListBinding] = []
    for sent in _rows(raw, "requested"):
        control_id = str(sent.get("id", ""))
        kept = persisted_by_id.get(control_id)
        target = _dict_or_empty(sent.get("target"))
        bindings.append(
            ListBinding(
                label=str(sent.get("label", "")),
                component=str(sent.get("component", "")),
                entry=_int_or(sent.get("entry"), 0),
                control_id=control_id,
                target=str(target.get("key", "")),
                list_id=str(target.get("listId") or ""),
                list_url=str(target.get("serverRelativeUrl") or ""),
                web_part_data=_dict_or_empty(sent.get("webPartData")),
                requested=str(sent.get("canvas", "")),
                persisted=kept["canvas"] if kept else None,
                stored_web_part_data=_stored_web_part_data(kept["canvas"] if kept else None),
            )
        )
    return tuple(bindings)


def _page_state(raw: Any) -> tuple[PageStateSample, ...]:
    """The M7 page-state samples, one per scratch page the probe tried to create.

    A row without a string label is not a sample; everything else is carried
    with the same defaults the template writes before a step runs.
    """
    samples: list[PageStateSample] = []
    for row in _rows(raw, "samples"):
        label = _optional_str(row.get("label"))
        if label is None:
            continue
        recycled = row.get("recycled")
        samples.append(
            PageStateSample(
                label=label,
                topics=_str_tuple(row.get("topics")),
                page_id=_optional_int(row.get("pageId")),
                requested=_dict_or_empty(row.get("requested")),
                persisted=_dict_or_empty(row.get("persisted")),
                ok=row.get("ok") is True,
                status=_int_or(row.get("status"), 0),
                reason=str(row.get("reason") or ""),
                recycled=recycled if isinstance(recycled, bool) else None,
            )
        )
    return tuple(samples)


def _page_state_unmeasured(raw: Any) -> tuple[str, ...]:
    """The topics the page-state lane names as unmeasured, in file order."""
    return tuple(
        row["topic"] for row in _rows(raw, "unmeasured") if isinstance(row.get("topic"), str)
    )
