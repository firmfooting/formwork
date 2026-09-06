"""Standalone HTML preview of a page spec. No SharePoint, no network.

The preview walks the same validated placements the compiler does
(:func:`formwork.dsl.placements`), so a spec that previews has the geometry
and the text bodies a compile would emit. Component resolution is the one
difference: without a discovery document a part's title is its alias, and a
name the catalogue lacks is shown as unresolved rather than refused, because
a preview is for looking, not for shipping.
"""

from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from . import __version__
from .catalogue import Catalogue
from .dsl import (
    SECTION_FACTORS,
    DslError,
    Placement,
    page_title,
    part_html,
    placements,
    resolve_component,
)
from .templating import render_template


@dataclass(frozen=True)
class PreviewPart:
    kind: str  # "text" or "component"
    alias: str
    title: str
    description: str = ""
    html: str = ""  # text parts only
    resolved: bool = False  # component parts: found in the catalogue


@dataclass(frozen=True)
class PreviewColumn:
    factor: int  # of 12
    parts: tuple[PreviewPart, ...]


@dataclass(frozen=True)
class PreviewSection:
    index: int  # 1-based
    type: str
    columns: tuple[PreviewColumn, ...]


@dataclass(frozen=True)
class PagePreview:
    title: str
    sections: tuple[PreviewSection, ...]
    resolved: bool  # a catalogue supplied titles and descriptions


def build_preview(spec: dict[str, Any], cat: Catalogue | None = None) -> PagePreview:
    """Lay out a spec's sections, columns and parts for rendering."""
    title = page_title(spec)
    by_slot: dict[tuple[int, int], list[PreviewPart]] = defaultdict(list)
    for placement in placements(spec):
        by_slot[(placement.section, placement.column)].append(_preview_part(placement, cat))

    sections: list[PreviewSection] = []
    for index, section in enumerate(spec["sections"], start=1):
        type_name = section.get("type", "one")
        columns = tuple(
            PreviewColumn(factor=factor, parts=tuple(by_slot.get((index, column), ())))
            for column, factor in enumerate(SECTION_FACTORS[type_name], start=1)
        )
        sections.append(PreviewSection(index=index, type=type_name, columns=columns))
    return PagePreview(title=title, sections=tuple(sections), resolved=cat is not None)


def _preview_part(placement: Placement, cat: Catalogue | None) -> PreviewPart:
    if placement.kind == "text":
        return PreviewPart(kind="text", alias="text", title="Text", html=part_html(placement))
    name = str(placement.part["component"])
    display = placement.part.get("displayTitle")
    if cat is not None:
        with suppress(DslError):
            component = resolve_component(name, cat)
            return PreviewPart(
                kind="component",
                alias=component.alias,
                title=display or component.title,
                description=component.description,
                resolved=True,
            )
    return PreviewPart(kind="component", alias=name, title=display or name)


def render_preview(preview: PagePreview) -> str:
    """The standalone HTML document for a built preview."""
    return render_template("preview.html.j2", page=preview, version=__version__)
