"""The page DSL: declarative page specs compiled to canvas markup.

A spec names sections (with SharePoint's column factors) and parts. A part is
either a web part, named by component alias or title with optional property
overrides, or a text block, ``{"text": ...}``, whose body is HTML or the
markdown subset in :mod:`formwork.text`. Compilation resolves every component
against the live catalogue — an unknown or hidden component refuses to compile
rather than emitting markup SharePoint would silently drop or mis-render.
Output is a complete CanvasContent1 document, ready for the apply paste-in.

:func:`section_tree` is the one walk over a spec's sections and parts: it
builds the :mod:`formwork.sections` tree (sections of columns of placements)
that the compiler, the preview and the multi-page build all consume, so all
of them validate the same way and none re-derives a column from ``type``.
:func:`placements` is that tree flattened to written order, the canvas order.
The section vocabulary itself (named types, measured factor sets, geometry)
lives in :mod:`formwork.sections`, which :mod:`formwork.catalogue` shares.
"""

import re
import warnings
from dataclasses import dataclass
from math import isfinite
from typing import Any

from .canvas import COLON_ENTITY, Canvas, Control
from .catalogue import Catalogue, Component
from .sections import (
    MAX_COLUMNS,
    MEASURED_FACTOR_SETS,
    ROW_SPAN,
    SECTION_FACTORS,
    Placement,
    Section,
    SectionColumn,
    written_order,
)
from .text import TextError, text_to_html

#: The two kinds of part a spec may place.
PART_KINDS = ("component", "text")

#: ``zoneEmphasis`` values the ``emphasis:`` key accepts on a component part.
#: Measured (tests/fixtures/discovery.styling.json, shauntestazure sandbox,
#: 2026-09-06): 2 and 3 were sent on web-part controls and persisted
#: byte-for-byte through the item MERGE the apply script uses
#: (``styling.sectionSamples``, labels ``emphasis-soft`` and
#: ``emphasis-unknown-key``), and 3 was live-verified surviving on a newly
#: merged control in a SavePage-established section
#: (``styling.sectionEmphasisMechanism.evidence.savePageJsonArray``). 1 is
#: the editor pane's "neutral" and 4 has not been read back: both are
#: accepted as the key set the editor offers, not as measured values.
ZONE_EMPHASIS_VALUES = (1, 2, 3, 4)

#: The one emphasis key the DSL encodes. The probe showed an unknown key
#: (``formworkProbe``) echoing back unchanged (``emphasis-unknown-key``,
#: 2026-09-06); that proves survival, not rendering, so nothing else is
#: accepted.
EMPHASIS_KEYS = frozenset({"zoneEmphasis"})

#: Styling keys a spec may be tempted to write on a section (or ``theme`` on
#: the page) that compile cannot encode, each with the measured reason. All
#: are named in the discovery document's ``styling.unmeasured`` list or its
#: ``sectionEmphasisMechanism`` block (2026-09-06); refusing them keeps
#: "nothing is silently dropped" true for styling as well as text.
UNENCODABLE_SECTION_KEYS: dict[str, str] = {
    "emphasis": (
        "section-level emphasis is not encodable by compile alone: measured 2026-09-06"
        " (discovery.styling.json, styling.sectionEmphasisMechanism), section emphasis"
        " takes effect only once the section is established through the page model's"
        " SavePage with a zoneId, which the apply path does not do. Put 'emphasis' on"
        " the section's component parts to carry the measured per-control block."
    ),
    "background": (
        "section backgrounds are unmeasured: the control-data shape is not known"
        " (discovery.styling.json, styling.unmeasured 'section-background', 2026-09-06)"
    ),
    "spacing": (
        "section spacing is unmeasured: no per-section spacing key is known in the"
        " canvas model (discovery.styling.json, styling.unmeasured 'section-spacing',"
        " 2026-09-06)"
    ),
}

#: Same rule for the page: theme and accent are web-level settings that no
#: page save can set (``styling.unmeasured`` 'theme', 2026-09-06).
UNENCODABLE_PAGE_KEYS: dict[str, str] = {
    "theme": (
        "theme is not a page setting: theme and accent colour are web-level"
        " (web/ApplyTheme), and CanvasContent1 carries no theme field"
        " (discovery.styling.json, styling.unmeasured 'theme', 2026-09-06)"
    ),
}

#: Page keys no measurement covers yet. Distinct from UNENCODABLE_PAGE_KEYS,
#: whose reasons cite a measurement: each of these names the FINDINGS.md
#: check-id pattern a discover lane would fill, and is refused until that
#: lane has run and the row exists. The M7 pageState lane lists them under
#: ``pageState.unmeasured`` so the refusal and the probe name the same gap.
UNMEASURED_PAGE_KEYS: dict[str, str] = {
    "navigation": (
        "navigation is unmeasured: adding a page to the site navigation is a"
        " navigation-node write (web/Navigation/QuickLaunch), not a page save, and"
        " no FINDINGS.md row page.navigation.* records one; refused until a"
        " formwork gen discover lane measures it (pageState.unmeasured"
        " 'navigation', 2026-09-07)"
    ),
}


class DslError(ValueError):
    """A page spec cannot be compiled against this site's catalogue."""


@dataclass(frozen=True)
class CompiledPage:
    title: str
    canvas: str
    parts: list[dict[str, Any]]


def page_title(spec: dict[str, Any]) -> str:
    title = spec.get("page") or spec.get("title")
    if not title or not isinstance(title, str):
        raise DslError("spec must carry a page title under 'page'")
    return title


#: The bind keys a spec may write. ``listId``/``listUrl`` required,
#: ``viewId`` optional (the measured shapes all carry a view id, but the
#: key set with an omitted view was not measured as *refused* — binding
#: without a view is the documented default-view behaviour).
BIND_KEYS: frozenset[str] = frozenset({"listId", "listUrl", "viewId"})

#: Where those keys land in the web part's ``properties``. The URL pair is
#: the measured shape (discovery.m5.json listBindings, 2026-09-07): every
#: bound part stored ``selectedListUrl`` SERVER-relative
#: (``/sites/<web>/<list>``) beside ``webRelativeListUrl`` web-relative
#: (no leading slash). The spec's ``listUrl`` stays web-relative (the
#: ergonomic input); the server-relative form is derived at compile time
#: from the discovery document's web URL.
BIND_TARGET_KEYS: dict[str, str] = {
    "listId": "selectedListId",
    "listUrl": "selectedListUrl",
    "viewId": "selectedViewId",
}

#: The rest of the measured binding shape: every bound ListWebPart stored
#: these alongside the selected* keys (discovery.m5.json, 2026-09-07).
BIND_SHAPE_EXTRAS: dict[str, Any] = {
    "webpartHeightKey": 4,
    "hideCommandBar": False,
}

#: Components with a measured binding sample (discovery.m5.json
#: listBindings, 2026-09-07: ListWebPart bound to list and library
#: targets, 4/4 with the selected* key set). Binding other components is
#: unmeasured and refused — the Quick links rows in the same block carry
#: none of the selected* keys.
BIND_COMPONENTS: frozenset[str] = frozenset({"ListWebPart"})

#: The web-part property that picks a multi-entry component's preconfigured
#: entry (ListWebPart entry 0 'List' vs entry 1 'Document library'):
#: measured (discovery.m5.json components, 2026-09-07).
DOC_LIB_ENTRY_PROPERTY = ("isDocumentLibrary", True)

#: GUID shape for bind ids: bare or paired braces, case-insensitive; the
#: value is normalised to bare lowercase before storing (every measured id
#: is bare lowercase — discovery.m5.json listBindings, 2026-09-07).
_GUID_RE = re.compile(
    r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$"
)


def _flat_scalars(properties: Any, ordinal: int) -> dict[str, Any]:
    """Validated ``properties:`` for one part: flat scalars only.

    Measured (discovery.m5.json webpartProperties, 2026-09-07): flat
    property paths survive the item MERGE byte-exact. Nested objects and
    lists were NOT measured, so they refuse rather than guess; the
    catalogue is evidence, not a whitelist, so unknown names pass.
    """
    if properties is None:
        return {}
    if not isinstance(properties, dict):
        raise DslError(f"part {ordinal}: 'properties' must be a mapping of name to value")
    for name, value in properties.items():
        # Allow-list, not deny-list: JSON-serialisable scalars only. The
        # measured sample types are exactly bool and str (webpartProperties,
        # 2026-09-07). A YAML unquoted date resolves to datetime.date, which
        # json.dumps raises TypeError on — reachable from an ordinary spec
        # (properties: {startDate: 2026-09-07}), so it refuses as a DslError
        # (review 2026-09-07 P2).
        if not isinstance(value, (str, int, float, bool)):
            raise DslError(
                f"part {ordinal}: properties.{name}: only flat scalar values are"
                " measured (discovery.m5.json webpartProperties, 2026-09-07:"
                " 12/12 flat changes persisted byte-exact); got"
                f" {type(value).__name__}. Nested objects, arrays, null and"
                " non-JSON scalars (YAML dates, binaries) are refused. Quote"
                " dates as strings if the property takes one."
            )
        if isinstance(value, float) and not isfinite(value):
            # The 2026-09-07 review asked for the whole non-finite class, not
            # just NaN: json.dumps writes either as a bare token —
            # NaN/Infinity/-Infinity — which is not JSON, and the canvas
            # attributes are read back with a JSON.parse (canvas.py's
            # decode_attribute path; the discover probe does the same with
            # DOMParser). `Infinity` reached data-sp-webpartdata until this
            # check.
            raise DslError(
                f"part {ordinal}: properties.{name}: {value!r} is not"
                " JSON-serialisable — json.dumps writes a non-finite float as the"
                " bare token NaN/Infinity, which JSON.parse (the page's own read of"
                " the control data) rejects. Use a finite number."
            )
    return dict(properties)


def _type_check_against_samples(
    properties: dict[str, Any], component: Component, cat: Catalogue, ordinal: int
) -> None:
    """Refuse type mismatches against the M5 measured samples.

    Where the discovery document carries a property sample for this
    component (webpartProperties), the measured value's type is the truth
    about that path: a string for a measured-bool path is a spec bug.
    Components without samples are unconstrained.
    """
    for sample in cat.property_samples_for(component.alias):
        declared = properties.get(sample.property_path)
        if declared is None:
            continue
        if type(declared) is not type(sample.new_value):
            raise DslError(
                f"part {ordinal}: properties.{sample.property_path} must be"
                f" {type(sample.new_value).__name__} — the M5 probe measured that"
                f" path carrying {sample.new_value!r}"
                " (discovery.m5.json webpartProperties, 2026-09-07), got"
                f" {declared!r}"
            )


def _bind_guid(key: str, value: Any, ordinal: int) -> str:
    """A bind id as the probe measured storing it: bare lowercase GUID."""
    if not isinstance(value, str) or not _GUID_RE.match(value):
        raise DslError(
            f"part {ordinal}: bind.{key} must be a GUID, got {value!r}"
            " (the probe bound real ids read from _api/web/lists)"
        )
    # Asymmetric braces refuse: the regex's independent optionals would
    # otherwise accept "{guid" and "guid}" (review 2026-09-07 P2).
    if (value.startswith("{") != value.endswith("}")) and ("{" in value or "}" in value):
        raise DslError(
            f"part {ordinal}: bind.{key} GUID braces must be paired, got {value!r}"
        )
    # Normalise to the bare lowercase form every measured id carries
    # (review 2026-09-07 P2: {GUID} and mixed case reached stored bytes in
    # a shape no probe sent).
    return value.strip("{}").lower()


def _bind_url(value: Any, ordinal: int, cat: Catalogue) -> tuple[str, str]:
    """The two stored spellings of a bound list's URL.

    The probe stored selectedListUrl SERVER-relative and
    webRelativeListUrl web-relative (discovery.m5.json persisted rows,
    2026-09-07); the server-relative form derives from the discovery
    document's web URL. The spec's value stays web-relative.
    """
    if not isinstance(value, str) or not value or value.startswith("/") or "://" in value:
        raise DslError(
            f"part {ordinal}: bind.listUrl must be web-relative (e.g."
            f" 'Shared Documents'), got {value!r}. The server-relative form"
            " is derived at compile time from the discovery document's web"
            " URL, matching the measured stored shape."
        )
    web_path = cat.web_server_relative_path
    if not web_path:
        raise DslError(
            f"part {ordinal}: the discovery document carries no web URL, so"
            " the server-relative selectedListUrl cannot be derived; re-run"
            " 'formwork gen discover' against the target site."
        )
    return f"{web_path}/{value}", value


def part_bind(
    part: dict[str, Any],
    ordinal: int,
    component: Component,
    cat: Catalogue | None = None,
) -> dict[str, Any]:
    """The web-part ``properties`` a part's ``bind:`` key contributes.

    ``bind: {listId, listUrl, viewId?}`` writes the binding key set the M5
    probe measured persisting for ListWebPart (discovery.m5.json
    listBindings, 2026-09-07): ``selectedListId``, ``selectedListUrl``
    SERVER-relative (derived here from the discovery document's web URL),
    ``webRelativeListUrl`` web-relative, ``selectedViewId``, plus the
    measured companions ``webpartHeightKey: 4`` and ``hideCommandBar:
    false``. The spec's ``listUrl`` stays web-relative — the ergonomic
    input; ids are GUID-shaped and normalised to the bare lowercase form
    every measured id carries. Binding a component without a measured
    binding sample refuses.
    """
    bind = part.get("bind")
    if bind is None:
        return {}
    if component.alias not in BIND_COMPONENTS:
        measured = ", ".join(sorted(BIND_COMPONENTS))
        raise DslError(
            f"part {ordinal}: bind on {component.alias} is unmeasured: the M5"
            f" probe bound {measured} only (discovery.m5.json listBindings,"
            " 2026-09-07 — the Quick links rows carry none of the selected*"
            " keys). Bind is refused rather than guessed."
        )
    if not isinstance(bind, dict):
        raise DslError(f"part {ordinal}: 'bind' must be a mapping (listId, listUrl, viewId?)")
    unknown = sorted(set(bind) - BIND_KEYS)
    if unknown:
        raise DslError(
            f"part {ordinal}: unknown bind key(s) {', '.join(unknown)}: measured keys are"
            " listId, listUrl, viewId (discovery.m5.json listBindings, 2026-09-07)"
        )
    missing = sorted(BIND_KEYS - {"viewId"} - set(bind))
    if missing:
        raise DslError(
            f"part {ordinal}: bind is missing {', '.join(missing)}: the measured"
            " binding key set is listId + listUrl (+ optional viewId)"
        )
    if cat is None:
        # No catalogue in context: the server-relative selectedListUrl the
        # probe measured storing cannot be derived.
        raise DslError(
            f"part {ordinal}: bind requires a discovery document to derive"
            " the server-relative selectedListUrl the probe measured storing"
        )
    out: dict[str, Any] = {}
    for key, target in BIND_TARGET_KEYS.items():
        if key not in bind:
            continue
        if key in ("listId", "viewId"):
            out[target] = _bind_guid(key, bind[key], ordinal)
        else:
            out[target], out["webRelativeListUrl"] = _bind_url(bind[key], ordinal, cat)
    out |= dict(BIND_SHAPE_EXTRAS)
    return out


def section_factors(
    section: dict[str, Any], index: int
) -> tuple[tuple[int, ...], str | None]:
    """A section's column factors, from ``columns:`` or the named type.

    Returns the factors and the type name the section used (``one`` when it
    named neither key), or None for a section that gave ``columns:``.
    """
    explicit = section.get("columns")
    type_name = section.get("type", "one")
    if explicit is not None and "type" in section:
        factors_hint = SECTION_FACTORS.get(type_name) if isinstance(type_name, str) else None
        raise DslError(
            f"section {index}: give 'type' or 'columns', not both"
            + (
                f" (type {type_name!r} means factors {factors_hint})"
                if factors_hint
                else f" (type {type_name!r} is not a known section type)"
            )
        )
    if explicit is not None:
        if not isinstance(explicit, list) or not 1 <= len(explicit) <= MAX_COLUMNS:
            raise DslError(
                f"section {index}: columns must be 1-3 factors, got {explicit!r}"
            )
        # Ints only, bools refused (catalogue.py's predicate): 8.9 silently
        # becoming 8, or [true, 11] becoming [1, 11], is a spec bug
        # (review 2026-09-07 P3).
        for f in explicit:
            if not isinstance(f, int) or isinstance(f, bool):
                raise DslError(
                    f"section {index}: columns must be integers, got {explicit!r}"
                )
        factors = tuple(explicit)
        if any(not 1 <= f <= ROW_SPAN for f in factors) or sum(factors) != ROW_SPAN:
            raise DslError(
                f"section {index}: illegal factor set {factors!r}: each factor is"
                " 1-12 and the row sums to 12"
            )
        return factors, None
    if type_name not in SECTION_FACTORS:
        known = ", ".join(sorted(SECTION_FACTORS))
        raise DslError(f"unknown section type {type_name!r} (known: {known})")
    return tuple(SECTION_FACTORS[type_name]), type_name


def _refuse_unsupported_page_keys(spec: dict[str, Any]) -> None:
    """Page-level keys compile cannot encode (theme) or has not measured
    (navigation) refuse with their citation, before any section walks."""
    for key, reason in UNENCODABLE_PAGE_KEYS.items():
        if key in spec:
            raise DslError(f"spec: {reason}")
    for key, reason in UNMEASURED_PAGE_KEYS.items():
        if key in spec:
            raise DslError(f"spec: {reason}")


def section_tree(spec: dict[str, Any]) -> tuple[Section, ...]:
    """Walk a spec's sections and parts, validating shape and geometry.

    The one walk. Each :class:`Section` carries one :class:`SectionColumn`
    per factor, and each column the placements written into it, in written
    order.

    A placement's ``control_index`` counts within its SECTION (the
    compiler's convention since M1). The M5 discovery probe numbers per
    COLUMN (split-4-8-two-col1 and -col2 both persisted controlIndex 1,
    discovery.m5.json:4128-4163), so the two conventions disagree for the
    second column of any multi-column section. The render-side effect is
    UNMEASURED — whether the editor accepts, renumbers or reorders a
    per-section number on save is open (m12 review note, 2026-09-06).
    Reconcile with a live probe before the SavePage emphasis slice
    depends on these numbers.
    """
    declared = spec.get("sections")
    if not isinstance(declared, list) or not declared:
        raise DslError("spec must declare at least one section")
    _refuse_unsupported_page_keys(spec)

    tree: list[Section] = []
    ordinal = 0
    for s_index, section in enumerate(declared, start=1):
        if not isinstance(section, dict):
            raise DslError(f"section {s_index}: expected a mapping with 'type' and 'parts'")
        for key, reason in UNENCODABLE_SECTION_KEYS.items():
            if key in section:
                raise DslError(f"section {s_index}: {reason}")
        factors, type_name = section_factors(section, s_index)
        if factors not in MEASURED_FACTOR_SETS:
            measured = " / ".join(
                str(list(f)) for f in MEASURED_FACTOR_SETS if len(f) == len(factors)
            )
            warnings.warn(
                f"section {s_index}: factor set {list(factors)} is legal but unmeasured"
                f" (measured sets of this width: {measured} — discovery.m5.json"
                " layoutVariants, 2026-09-07); compiling anyway.",
                stacklevel=2,
            )
        by_column: list[list[Placement]] = [[] for _ in factors]
        for p_index, part in enumerate(section.get("parts") or [], start=1):
            ordinal += 1
            if not isinstance(part, dict):
                raise DslError(f"part {ordinal}: expected a mapping with 'component' or 'text'")
            column = int(part.get("column", 1))
            if not 1 <= column <= len(factors):
                raise DslError(
                    f"part {ordinal} names column {column} but section "
                    f"{s_index} has {len(factors)} column(s)"
                )
            kind = _part_kind(part, ordinal)
            # A part's displayTitle becomes the canvas web part data's title
            # (dsl.py:_control_for, parts_out and preview.py all read it), and
            # every title the persisted canvases carry is a JSON string
            # (tests/fixtures/collabhome.canvas.html). A non-string would go
            # into the canvas as a number or array — and a non-finite float
            # as the bare token Infinity, which is not JSON at all.
            display = part.get("displayTitle")
            if display is not None and not isinstance(display, str):
                raise DslError(
                    f"part {ordinal}: 'displayTitle' must be a string (it is the"
                    " title the page shows); got"
                    f" {type(display).__name__}"
                )
            by_column[column - 1].append(
                Placement(
                    ordinal=ordinal,
                    section=s_index,
                    factors=factors,
                    column=column,
                    control_index=p_index,
                    kind=kind,
                    part=part,
                    emphasis=part_emphasis(part, ordinal, kind),
                )
            )
        tree.append(
            Section(
                index=s_index,
                factors=factors,
                columns=tuple(
                    SectionColumn(factor=factor, controls=tuple(controls))
                    for factor, controls in zip(factors, by_column, strict=True)
                ),
                type_name=type_name,
            )
        )
    return tuple(tree)


def placements(spec: dict[str, Any]) -> list[Placement]:
    """Every part of a spec, validated and positioned, in written order."""
    return written_order(section_tree(spec))


def part_emphasis(part: dict[str, Any], ordinal: int, kind: str) -> dict[str, Any]:
    """The control-data ``emphasis`` block a part declares, validated.

    ``emphasis: {zoneEmphasis: N}`` or the shorthand ``emphasis: N``; absent
    (or an empty mapping) is ``{}``, which is what every control the probe
    sent carried. Component parts only: every text control the probe read
    back (``textControls`` and the seven ``styling.styleSamples``,
    2026-09-06) carried ``emphasis: {}``, so emphasis on a text part is
    unmeasured and refused rather than guessed. Values and keys are checked
    against :data:`ZONE_EMPHASIS_VALUES` and :data:`EMPHASIS_KEYS`, whose
    comments carry the measurement.
    """
    if "emphasis" not in part:
        return {}
    if kind == "text":
        raise DslError(
            f"part {ordinal}: emphasis on text parts is not measured; the discover"
            " samples always carry {} (discovery.styling.json textControls and"
            " styleSamples, 2026-09-06). Put it on a component part."
        )
    raw = part["emphasis"]
    block = dict(raw) if isinstance(raw, dict) else {"zoneEmphasis": raw}
    if not block:
        return {}
    unknown = sorted(str(key) for key in block if key not in EMPHASIS_KEYS)
    if unknown:
        raise DslError(
            f"part {ordinal}: unknown emphasis key(s) {', '.join(unknown)}: only"
            " zoneEmphasis is encoded. The probe measured that an unknown key echoes"
            " back (discovery.styling.json, emphasis-unknown-key, 2026-09-06), not"
            " that it renders."
        )
    value = block["zoneEmphasis"]
    if isinstance(value, bool) or not isinstance(value, int) or value not in ZONE_EMPHASIS_VALUES:
        accepted = ", ".join(str(v) for v in ZONE_EMPHASIS_VALUES)
        raise DslError(
            f"part {ordinal}: emphasis.zoneEmphasis must be an integer in {{{accepted}}}"
            " (2 and 3 measured persisting, discovery.styling.json sectionSamples,"
            f" 2026-09-06; 1 and 4 are the editor's other swatches), got {value!r}"
        )
    return {"zoneEmphasis": value}


def _part_kind(part: dict[str, Any], ordinal: int) -> str:
    named = [kind for kind in PART_KINDS if kind in part]
    if len(named) != 1:
        raise DslError(f"part {ordinal}: a part names exactly one of 'component' or 'text'")
    return named[0]


def resolve_component(name: str, cat: Catalogue) -> Component:
    """A component by alias, then by title; DslError when the site lacks it."""
    try:
        return cat.by_alias(name)
    except KeyError:
        pass
    try:
        return cat.by_title(name)
    except KeyError:
        raise DslError(
            f"component {name!r} is not placeable on this site — "
            "run 'formwork gen discover' to refresh the catalogue"
        ) from None


def part_html(placement: Placement) -> str:
    """The HTML a text part carries, converted per its declared format."""
    text = placement.part["text"]
    if not isinstance(text, str) or not text.strip():
        raise DslError(f"part {placement.ordinal}: 'text' must be a non-empty string")
    fmt = placement.part.get("format")
    try:
        return text_to_html(text, None if fmt is None else str(fmt))
    except TextError as exc:
        raise DslError(f"part {placement.ordinal}: {exc}") from None


def _check_placeable(component: Component) -> None:
    if component.hidden:
        raise DslError(f"component {component.alias!r} is hidden on this site")
    if component.component_type != 1:
        raise DslError(
            f"component {component.alias!r} is a type-{component.component_type} "
            "component (extension), not a placeable web part"
        )


def _position(placement: Placement) -> dict[str, Any]:
    return {
        "zoneIndex": float(placement.section * 1000),
        "sectionIndex": float(placement.section),
        "controlIndex": float(placement.control_index),
        "zoneId": None,
        "sectionFactor": placement.section_factor,
        "layoutIndex": 1,
    }


def _control_id(placement: Placement) -> str:
    return f"00000000-0000-0000-0000-{placement.ordinal:012d}"


def _control_for(
    component: Component,
    placement: Placement,
    cat: Catalogue | None = None,
) -> Control:
    """Build one web-part canvas control for a spec part.

    The control data is the shape the discover probe sends for a web-part
    control (discover.js.j2 step 3, same keys in the same order), with the
    part's validated ``emphasis`` block in place of the probe's ``{}``.
    Measured (discovery.styling.json sectionSamples, 2026-09-06): a web-part
    control sent with ``emphasis: {zoneEmphasis: 2}`` (and one with 3)
    through the item MERGE persisted byte-for-byte. Whether the section then
    RENDERS with that emphasis is the SavePage-establishment question the
    ``sectionEmphasisMechanism`` block records; see UNENCODABLE_SECTION_KEYS.
    """
    control_id = _control_id(placement)
    web_part_id = component.component_id
    part = placement.part
    control_data = {
        "controlType": 3,
        "id": control_id,
        "position": _position(placement),
        "webPartId": web_part_id,
        "emphasis": dict(placement.emphasis),
    }
    # Bound parts carry the measured listTitle in searchablePlainTexts
    # (discovery.m5.json listBindings, 2026-09-07); unbound parts keep the
    # empty serverProcessedContent every other probe control carried.
    bind_props = part_bind(part, placement.ordinal, component, cat)
    bound = "webRelativeListUrl" in bind_props
    server_processed: dict[str, Any] = (
        {"searchablePlainTexts": {"listTitle": part["bind"]["listUrl"]}} if bound else {}
    )
    web_part_data = {
        "id": web_part_id,
        "instanceId": control_id,
        "title": part.get("displayTitle") or component.title,
        "description": "",
        "serverProcessedContent": server_processed,
        "dataVersion": "1.0",
        "properties": dict(component.default_properties)
        | _flat_scalars(part.get("properties"), placement.ordinal)
        | bind_props,
    }
    # canvas.py owns the markup shape and the attribute encoding: the same
    # encoder its dirty-render path uses, so the bytes are the ones a
    # parsed-and-re-rendered control would carry.
    return Control.web_part(control_data, web_part_data)


def stored_text_html(html: str) -> str:
    """A text part's HTML as SharePoint stores it: every ``:`` as ``&#58;``.

    Measured live (shauntestazure, 2026-09-06,
    tests/fixtures/discovery.styling.json): the item MERGE the apply
    paste-in uses stored each colon-bearing text sample with ``:``
    rewritten as ``&#58;`` and nothing else changed. ``styling.styleSamples``
    ``color`` was requested as ``style="color:#a4262c;"`` and persisted as
    ``style="color&#58;#a4262c;"``; ``font-size``, ``background``,
    ``styled-link`` (a colon in the href and two in the style) and
    ``block-align`` likewise; the two colon-free samples, ``mark`` and
    ``rte-classes``, came back byte-identical. Over the whole scratch page
    the rewrite is the only growth: ``requestedCanvasChars`` 97907 against
    ``storedCanvasChars`` 97947. This is the one rewrite, so this is the one
    fold; ``tests/test_styling_evidence.py`` pins that it reproduces the
    stored bytes of all seven samples.
    """
    return html.replace(":", COLON_ENTITY)


def _text_control(body_html: str, placement: Placement) -> Control:
    """Build one text canvas control: controlType 4, no web part.

    The shape is the one the discover script sends (discover.js.j2, step
    3a): the control data carries ``editorType`` and no ``webPartId``, and
    the HTML is the inner content of a ``data-sp-rte`` child. The inner
    HTML is emitted through :func:`stored_text_html`, the spelling
    SharePoint stores, because the apply paste-in compares what it sent
    with what was stored byte for byte: emitting a literal ``:`` created
    the page and then failed that check for every styled part and every
    absolute link (architecture review P1-1, 2026-09-06). Nothing else is
    folded; :func:`compile_page` still gates on the discovery document's
    own samples via :meth:`TextControlSample.persisted_matches`, whose
    requested side is the probe's literal-colon HTML and so folds both
    sides.
    """
    control_data = {
        "controlType": 4,
        "id": _control_id(placement),
        "position": _position(placement),
        "emphasis": {},
        "editorType": "CKEditor",
    }
    return Control.text(control_data, stored_text_html(body_html))


def compile_page(spec: dict[str, Any], cat: Catalogue) -> CompiledPage:
    """Compile a page spec against a component catalogue.

    The controls are the section tree's placements in written order: one
    canvas control per placement, positioned from the tree (section index,
    section factor, control index) and nothing else.
    """
    title = page_title(spec)
    controls: list[Control] = []
    parts_out: list[dict[str, Any]] = []
    placed = placements(spec)
    wants_text = any(p.kind == "text" for p in placed)
    if wants_text:
        matched = [s for s in cat.text_controls if s.persisted_matches() is True]
        mismatched = [s for s in cat.text_controls if s.persisted_matches() is False]
        if mismatched:
            raise DslError(
                "the discovery document's text-control measurement does not match what"
                " was sent (after normalising SharePoint's ':' -> '&#58;' rewrite):"
                " the text-control shape has changed since the probe ran. Re-run"
                " 'formwork gen discover' and review the new samples before compiling"
                " text parts."
            )
        if not matched:
            raise DslError(
                "the spec has text parts, but this discovery document carries no persisted"
                " text-control measurement. Run 'formwork gen discover' against the target"
                " site first, then re-run 'formwork compile': applying an unmeasured text"
                " shape can abort after page creation on the byte-exact check."
            )
    for placement in placed:
        where = {
            "section": placement.section,
            "column": placement.column,
            "controlIndex": placement.control_index,
        }
        if placement.kind == "text":
            if "bind" in placement.part:
                raise DslError(
                    f"part {placement.ordinal}: bind on text parts is unmeasured:"
                    " the M5 probe bound ListWebPart only (discovery.m5.json"
                    " listBindings, 2026-09-07). Put bind on a component part."
                )
            body_html = part_html(placement)
            controls.append(_text_control(body_html, placement))
            parts_out.append(
                {"kind": "text", "component": "text", "title": "Text", "html": body_html}
                | where
            )
            continue
        component = resolve_component(placement.part["component"], cat)
        _check_placeable(component)
        declared_properties = _flat_scalars(
            placement.part.get("properties"), placement.ordinal
        )
        bind_props = part_bind(
            placement.part, placement.ordinal, component, cat
        )
        overlap = sorted(set(declared_properties) & set(bind_props))
        if overlap:
            raise DslError(
                f"part {placement.ordinal}: bind writes {', '.join(overlap)} which"
                " 'properties' also sets; the measured binding key set owns those"
                " names — remove them from 'properties' (collision)"
            )
        if cat is not None:
            _type_check_against_samples(declared_properties, component, cat, placement.ordinal)
        controls.append(_control_for(component, placement, cat))
        bind_block = placement.part.get("bind") or None
        parts_out.append(
            {
                "kind": "component",
                "component": component.alias,
                "title": placement.part.get("displayTitle") or component.title,
                "emphasis": dict(placement.emphasis),
            }
            | where
        )
        if bind_block:
            parts_out[-1]["boundTo"] = {
                key: bind_block[key] for key in ("listId", "listUrl", "viewId") if key in bind_block
            }

    canvas = Canvas(controls=controls, preamble="<div>")
    return CompiledPage(
        title=title,
        canvas=canvas.render() + "</div>",
        parts=parts_out,
    )
