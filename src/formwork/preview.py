"""Standalone HTML preview of a page spec. No SharePoint, no network.

The preview lays out the same section tree the compiler compiles
(:func:`formwork.dsl.section_tree`), so a spec that previews has the geometry
and the text bodies a compile would emit. Component resolution is the one
difference: without a discovery document a part's title is its alias, and a
name the catalogue lacks is shown as unresolved rather than refused, because
a preview is for looking, not for shipping.
"""

from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from . import __version__
from .catalogue import Catalogue
from .dsl import DslError, page_title, part_html, resolve_component, section_tree
from .sections import Placement
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
    type: str  # the section's layout name (Section.layout)
    columns: tuple[PreviewColumn, ...]


@dataclass(frozen=True)
class PagePreview:
    title: str
    sections: tuple[PreviewSection, ...]
    resolved: bool  # a catalogue supplied titles and descriptions


def build_preview(spec: dict[str, Any], cat: Catalogue | None = None) -> PagePreview:
    """Lay out a spec's sections, columns and parts for rendering.

    The geometry is the section tree's, column by column, never re-derived
    by ``type``: a ``columns: [8, 4]`` section has no SECTION_FACTORS entry,
    and previewing it through the type table dropped its column-2 parts
    (review 2026-09-07 P1-2). Such a section is labelled by the type whose
    factors it uses (``two-thirds`` here), or ``columns`` when no type
    names its set.
    """
    title = page_title(spec)
    sections = tuple(
        PreviewSection(
            index=section.index,
            type=section.layout,
            columns=tuple(
                PreviewColumn(
                    factor=column.factor,
                    parts=tuple(_preview_part(p, cat) for p in column.controls),
                )
                for column in section.columns
            ),
        )
        for section in section_tree(spec)
    )
    return PagePreview(title=title, sections=sections, resolved=cat is not None)


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
