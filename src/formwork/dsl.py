"""The page DSL: declarative page specs compiled to canvas markup.

A spec names sections (with SharePoint's column factors) and parts. A part is
either a web part, named by component alias or title with optional property
overrides, or a text block, ``{"text": ...}``, whose body is HTML or the
markdown subset in :mod:`formwork.text`. Compilation resolves every component
against the live catalogue — an unknown or hidden component refuses to compile
rather than emitting markup SharePoint would silently drop or mis-render.
Output is a complete CanvasContent1 document, ready for the apply paste-in.

:func:`placements` is the one walk over a spec's sections and parts, shared
by the compiler and the preview, so both validate the same way.
"""

import json
from dataclasses import dataclass
from typing import Any

from .canvas import Canvas, Control, escape_attribute
from .catalogue import Catalogue, Component
from .text import TextError, text_to_html

# Section types: SharePoint's vertical section model. zoneIndex is the
# top-to-bottom position (first section must be 1000 in the observed model —
# CollabHome controls sit at zoneIndex 1.0 after SharePoint's own writes, so
# both scales appear; we emit the integer scale SharePoint writes on save).
SECTION_FACTORS: dict[str, list[int]] = {
    "one": [12],
    "two": [6, 6],
    "three": [4, 4, 4],
    "two-thirds": [8, 4],
    "one-third": [4, 8],
}

#: The two kinds of part a spec may place.
PART_KINDS = ("component", "text")


class DslError(ValueError):
    """A page spec cannot be compiled against this site's catalogue."""


@dataclass(frozen=True)
class CompiledPage:
    title: str
    canvas: str
    parts: list[dict[str, Any]]


@dataclass(frozen=True)
class Placement:
    """One part of a spec, validated and positioned."""

    ordinal: int  # 1-based across the page; becomes the control id
    section: int  # 1-based
    section_type: str
    factors: tuple[int, ...]
    column: int  # 1-based
    control_index: int  # 1-based within the section
    kind: str  # one of PART_KINDS
    part: dict[str, Any]

    @property
    def section_factor(self) -> int:
        return self.factors[self.column - 1]


def page_title(spec: dict[str, Any]) -> str:
    title = spec.get("page") or spec.get("title")
    if not title or not isinstance(title, str):
        raise DslError("spec must carry a page title under 'page'")
    return title


def placements(spec: dict[str, Any]) -> list[Placement]:
    """Walk a spec's sections and parts, validating shape and geometry."""
    sections = spec.get("sections")
    if not isinstance(sections, list) or not sections:
        raise DslError("spec must declare at least one section")

    placed: list[Placement] = []
    ordinal = 0
    for s_index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            raise DslError(f"section {s_index}: expected a mapping with 'type' and 'parts'")
        type_name = section.get("type", "one")
        if type_name not in SECTION_FACTORS:
            known = ", ".join(sorted(SECTION_FACTORS))
            raise DslError(f"unknown section type {type_name!r} (known: {known})")
        factors = tuple(SECTION_FACTORS[type_name])
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
            placed.append(
                Placement(
                    ordinal=ordinal,
                    section=s_index,
                    section_type=type_name,
                    factors=factors,
                    column=column,
                    control_index=p_index,
                    kind=_part_kind(part, ordinal),
                    part=part,
                )
            )
    return placed


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


def _control_for(component: Component, placement: Placement) -> Control:
    """Build one web-part canvas control for a spec part."""
    control_id = _control_id(placement)
    web_part_id = component.component_id
    part = placement.part
    control_data = {
        "controlType": 3,
        "id": control_id,
        "position": _position(placement),
        "webPartId": web_part_id,
        "emphasis": {},
    }
    web_part_data = {
        "id": web_part_id,
        "instanceId": control_id,
        "title": part.get("displayTitle") or component.title,
        "description": "",
        "serverProcessedContent": {},
        "dataVersion": "1.0",
        "properties": dict(component.default_properties)
        | dict(part.get("properties") or {}),
    }
    open_tag = (
        '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0" '
        f'data-sp-controldata="{_escaped(control_data)}">'
    )
    # The renderer's dirty path re-escapes from the decoded dicts, so we can
    # emit the body through Control with empty raw attributes present.
    wp_open = (
        '<div data-sp-webpartdata="'
        + _escaped(web_part_data)
        + '" data-sp-htmlproperties=""></div>'
    )
    # Body: the web-part child div, then the close of the control div itself —
    # the same shape the live canvas writes.
    body = wp_open + "</div>"
    control = Control(
        open_tag=open_tag,
        control_data=control_data,
        web_part_data=web_part_data,
        controldata_raw="",
        webpartdata_raw=None,
        body=body,
    )
    control.mark_dirty()
    return control


def _text_control(body_html: str, placement: Placement) -> Control:
    """Build one text canvas control: controlType 4, no web part.

    The shape is the one the discover script sends (discover.js.j2, step
    3a): the control data carries ``editorType`` and no ``webPartId``, and
    the HTML is the inner content of a ``data-sp-rte`` child.
    TODO(measure, 2026-09-06): the persisted shape has not yet been
    read from a live site; when a discovery document carries
    ``textControls.persisted``, compare it with ``requested`` and fold any
    difference (wrapper, ``editorType``, surviving tags) in here.
    """
    control_data = {
        "controlType": 4,
        "id": _control_id(placement),
        "position": _position(placement),
        "emphasis": {},
        "editorType": "CKEditor",
    }
    open_tag = (
        '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0" '
        f'data-sp-controldata="{_escaped(control_data)}">'
    )
    control = Control(
        open_tag=open_tag,
        control_data=control_data,
        web_part_data=None,
        controldata_raw="",
        webpartdata_raw=None,
        body=f'<div data-sp-rte="">{body_html}</div></div>',
    )
    control.mark_dirty()
    return control


def _escaped(data: dict[str, Any]) -> str:
    return escape_attribute(json.dumps(data, separators=(",", ":")))


def compile_page(spec: dict[str, Any], cat: Catalogue) -> CompiledPage:
    """Compile a page spec against a component catalogue."""
    title = page_title(spec)
    controls: list[Control] = []
    parts_out: list[dict[str, Any]] = []
    for placement in placements(spec):
        where = {
            "section": placement.section,
            "column": placement.column,
            "controlIndex": placement.control_index,
        }
        if placement.kind == "text":
            body_html = part_html(placement)
            controls.append(_text_control(body_html, placement))
            parts_out.append(
                {"kind": "text", "component": "text", "title": "Text", "html": body_html}
                | where
            )
            continue
        component = resolve_component(placement.part["component"], cat)
        _check_placeable(component)
        controls.append(_control_for(component, placement))
        parts_out.append(
            {
                "kind": "component",
                "component": component.alias,
                "title": placement.part.get("displayTitle") or component.title,
            }
            | where
        )

    canvas = Canvas(controls=controls, preamble="<div>")
    return CompiledPage(
        title=title,
        canvas=canvas.render() + "</div>",
        parts=parts_out,
    )
