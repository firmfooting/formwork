"""The page DSL: declarative page specs compiled to canvas markup.

A spec names sections (with SharePint's column factors), parts by component
alias or title, and property overrides. Compilation resolves every component
against the live catalogue — an unknown or hidden component refuses to compile
rather than emitting markup SharePoint would silently drop or mis-render.
Output is a complete CanvasContent1 document, ready for the apply paste-in.
"""

import json
from dataclasses import dataclass
from typing import Any

from .canvas import Canvas, Control, escape_attribute
from .catalogue import Catalogue, Component

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


class DslError(ValueError):
    """A page spec cannot be compiled against this site's catalogue."""


@dataclass(frozen=True)
class CompiledPage:
    title: str
    canvas: str
    parts: list[dict[str, Any]]


def _resolve_component(name: str, cat: Catalogue) -> Component:
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


def _check_placeable(component: Component) -> None:
    if component.hidden:
        raise DslError(f"component {component.alias!r} is hidden on this site")
    if component.component_type != 1:
        raise DslError(
            f"component {component.alias!r} is a type-{component.component_type} "
            "component (extension), not a placeable web part"
        )


def _control_for(component: Component, part: dict[str, Any], ordinal: int) -> Control:
    """Build one canvas control for a spec part."""
    control_id = f"00000000-0000-0000-0000-{ordinal:012d}"
    web_part_id = component.component_id
    position = {
        "zoneIndex": part["zoneIndex"],
        "sectionIndex": part["sectionIndex"],
        "controlIndex": part["controlIndex"],
        "zoneId": None,
        "sectionFactor": part["sectionFactor"],
        "layoutIndex": 1,
    }
    control_data = {
        "controlType": 3,
        "id": control_id,
        "position": position,
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


def _escaped(data: dict[str, Any]) -> str:
    return escape_attribute(json.dumps(data, separators=(",", ":")))


def compile_page(spec: dict[str, Any], cat: Catalogue) -> CompiledPage:
    """Compile a page spec against a component catalogue."""
    title = spec.get("page") or spec.get("title")
    if not title or not isinstance(title, str):
        raise DslError("spec must carry a page title under 'page'")
    sections = spec.get("sections")
    if not isinstance(sections, list) or not sections:
        raise DslError("spec must declare at least one section")

    controls: list[Control] = []
    parts_out: list[dict[str, Any]] = []
    ordinal = 0
    for s_index, section in enumerate(sections):
        type_name = section.get("type", "one")
        if type_name not in SECTION_FACTORS:
            known = ", ".join(sorted(SECTION_FACTORS))
            raise DslError(
                f"unknown section type {type_name!r} (known: {known})"
            )
        factors = SECTION_FACTORS[type_name]
        zone_index = float((s_index + 1) * 1000)
        parts = section.get("parts") or []
        for p_index, part in enumerate(parts):
            ordinal += 1
            column = int(part.get("column", 1))
            if not 1 <= column <= len(factors):
                raise DslError(
                    f"part {ordinal} names column {column} but section "
                    f"{s_index + 1} has {len(factors)} column(s)"
                )
            component = _resolve_component(part["component"], cat)
            _check_placeable(component)
            control = _control_for(
                component,
                {
                    "zoneIndex": zone_index,
                    "sectionIndex": float(s_index + 1),
                    "controlIndex": float(p_index + 1),
                    "sectionFactor": factors[column - 1],
                    "displayTitle": part.get("displayTitle"),
                    "properties": part.get("properties") or {},
                },
                ordinal,
            )
            controls.append(control)
            parts_out.append(
                {
                    "component": component.alias,
                    "section": s_index + 1,
                    "column": column,
                    "controlIndex": p_index + 1,
                    "title": part.get("displayTitle") or component.title,
                }
            )

    canvas = Canvas(controls=controls, preamble="<div>")
    return CompiledPage(
        title=title,
        canvas=canvas.render() + "</div>",
        parts=parts_out,
    )
