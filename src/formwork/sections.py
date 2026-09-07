"""The section model: the one description of a canvas section's geometry.

CanvasContent1 has no section object. A section is a row of columns whose
``sectionFactor`` widths sum to twelve, and a control's column is its factor
plus its ``controlIndex`` within that column — nothing else (measured
2026-09-06, tests/fixtures/discovery.m5.json ``layoutVariants``). Before M9
that vocabulary was spelled twice on the Python side: the compiler's
``SECTION_FACTORS`` plus per-placement factors, and the preview re-deriving
columns from ``type`` (review 2026-09-07 P1-2 caught it dropping the
column-2 parts of a ``columns: [8, 4]`` section). This module is now the one
place the vocabulary lives:

* the named layouts a spec's ``type:`` may ask for (:data:`SECTION_FACTORS`);
* the factor sets a live run has measured persisting
  (:data:`MEASURED_FACTOR_SETS`), and the probe's own layout samples by
  label (:data:`LAYOUT_VARIANT_FACTORS`), which the catalogue reads;
* the tree :func:`formwork.dsl.section_tree` builds from a spec:
  :class:`Section` rows of :class:`SectionColumn` columns holding
  :class:`Placement` controls. The compiler, the preview and the multi-page
  build all consume that one tree.

The module imports nothing from the package, so :mod:`formwork.catalogue`
(which :mod:`formwork.dsl` imports) can share these constants without a
cycle.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

#: Section types: SharePoint's vertical section model. zoneIndex is the
#: top-to-bottom position (first section must be 1000 in the observed model —
#: CollabHome controls sit at zoneIndex 1.0 after SharePoint's own writes, so
#: both scales appear; we emit the integer scale SharePoint writes on save).
#: The discover spread's ``FACTORS`` literal (discover.js.j2) spells the
#: first three of these in JS; tests/test_sections.py pins the two equal.
SECTION_FACTORS: dict[str, list[int]] = {
    "one": [12],
    "two": [6, 6],
    "three": [4, 4, 4],
    "two-thirds": [8, 4],
    "one-third": [4, 8],
}

#: Section geometry: a row of factors must sum to this, each 1-12.
MAX_COLUMNS = 3
ROW_SPAN = 12

#: The column factors the M5 layout probe measured persisting through the
#: item MERGE (tests/fixtures/discovery.m5.json layoutVariants, plus the
#: M2-era one/two/three defaults the live scratch pages always carried):
#: 2026-09-07. Any legal factor set compiles; unmeasured sets emit a
#: warning naming the measured set, because the evidence shows factors
#: persist generally (4/4 split-order variants kept) while only these
#: exact shapes are pinned.
MEASURED_FACTOR_SETS: tuple[tuple[int, ...], ...] = (
    (12,),
    (6, 6),
    (4, 4, 4),
    (8, 4),
    (4, 8),
)

#: The M5 layout probe's samples by section label: the ``LAYOUT_SAMPLES``
#: literal of ``_probe_legs.js.j2``, which tests/test_sections.py pins
#: against this table. A discovery row is labelled ``<section>-col<n>``
#: and carries only its own control's sectionFactor, so this is how the
#: Python side knows which factor set a layout variant measured.
LAYOUT_VARIANT_FACTORS: dict[str, tuple[int, ...]] = {
    "split-8-4": (8, 4),
    "split-4-8": (4, 8),
    "split-4-8-two": (4, 8),
}


def layout_name(factors: tuple[int, ...]) -> str | None:
    """The ``type:`` name whose factors these are, or None for an unnamed set."""
    for name, named in SECTION_FACTORS.items():
        if tuple(named) == factors:
            return name
    return None


@dataclass(frozen=True)
class Placement:
    """One part of a spec, validated and positioned."""

    ordinal: int  # 1-based across the page; becomes the control id
    section: int  # 1-based
    factors: tuple[int, ...]
    column: int  # 1-based
    control_index: int  # 1-based within the section
    kind: str  # one of dsl.PART_KINDS
    part: dict[str, Any]
    emphasis: dict[str, Any] = field(default_factory=dict)  # validated control-data block

    @property
    def section_factor(self) -> int:
        return self.factors[self.column - 1]


@dataclass(frozen=True)
class SectionColumn:
    """One column of a section: its factor and the controls placed in it.

    ``controls`` keeps the spec's written order, which is the canvas order:
    the probe measured SharePoint storing a column-2 control written before
    its column-1 neighbour exactly as written (``page.layout.factors-4-8``).
    """

    factor: int  # of ROW_SPAN
    controls: tuple[Placement, ...] = ()


@dataclass(frozen=True)
class Section:
    """One section of a spec: its factors and its columns' controls.

    ``index`` is 1-based and becomes every control's ``sectionIndex``;
    ``factors`` is the row of column widths; ``columns`` has one entry per
    factor, in order; ``type_name`` is the ``type:`` the spec used (the
    default ``one`` included), or None when it gave ``columns:`` instead.
    """

    index: int
    factors: tuple[int, ...]
    columns: tuple[SectionColumn, ...]
    type_name: str | None = None

    @property
    def layout(self) -> str:
        """The layout's display name: the type used, else the type whose
        factors these are, else ``columns`` for a set no type names."""
        if self.type_name is not None:
            return self.type_name
        return layout_name(self.factors) or "columns"

    @property
    def measured(self) -> bool:
        """Whether a live run measured this exact factor set persisting."""
        return self.factors in MEASURED_FACTOR_SETS

    @property
    def placements(self) -> tuple[Placement, ...]:
        """Every control of the section in written order (the canvas order)."""
        controls = [control for column in self.columns for control in column.controls]
        return tuple(sorted(controls, key=lambda control: control.ordinal))


def written_order(tree: Iterable[Section]) -> list[Placement]:
    """The flat, written-order view of a section tree: the canvas order."""
    return [control for section in tree for control in section.placements]
