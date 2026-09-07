"""The section model (M9): one description of a section's geometry.

The tree :func:`formwork.dsl.section_tree` builds is what the compiler, the
preview and the multi-page build consume. These tests pin the tree's factors
for every measured set, cite the fixture each set was measured in, prove
the compiler's positions and the preview's columns come from the tree, and
check the catalogue reads a stored canvas through the same canvas decoder
the compiler writes with.

Evidence (tests/fixtures/discovery.m5.json, shauntestazure sandbox,
2026-09-06/07):

* ``storedCanvas``: the discover spread's sections one/two/three at
  sectionIndex 1-3 read back with every control at sectionFactor 12, 6 and
  4 (``page.layout.default-factors``, FINDINGS.md);
* ``layoutVariants``: the 8/4 and 4/8 factor orders, 4/4 byte-exact and the
  written order kept (``page.layout.factors-8-4``, ``factors-4-8``).
"""

import copy
import json
import pathlib
import re

import pytest

from formwork.canvas import Canvas, decode_attribute
from formwork.catalogue import parse_discovery
from formwork.dsl import compile_page, placements, section_tree
from formwork.findings import load_findings
from formwork.generator import generate_discover_script, generate_findprobe_script
from formwork.preview import build_preview, render_preview
from formwork.sections import (
    LAYOUT_VARIANT_FACTORS,
    MEASURED_FACTOR_SETS,
    SECTION_FACTORS,
    Placement,
    Section,
    SectionColumn,
    layout_name,
    written_order,
)
from test_dsl import DISCOVERY_WITH_TEXT

ROOT = pathlib.Path(__file__).parent.parent
M5_FIXTURE = ROOT / "tests" / "fixtures" / "discovery.m5.json"
FINDINGS = ROOT / "FINDINGS.md"

#: Where each measured factor set was read back, by the fixture key.
EVIDENCE: dict[tuple[int, ...], str] = {
    (12,): "storedCanvas",
    (6, 6): "storedCanvas",
    (4, 4, 4): "storedCanvas",
    (8, 4): "layoutVariants",
    (4, 8): "layoutVariants",
}


def m5_document() -> dict:
    return json.loads(M5_FIXTURE.read_text(encoding="utf-8"))


def positions(canvas: str) -> list[dict]:
    """Every control's decoded position, in canvas order."""
    return [c.control_data["position"] for c in Canvas.parse(canvas).controls]


def spec(*sections: dict) -> dict:
    return {"page": "T", "sections": list(sections)}


#: A page whose sections are declared both ways, with a part in every
#: column position the consumers have to get right (column 2 of a
#: ``columns:`` section is the one review 2026-09-07 P1-2 found dropped).
CONSUMER_SPEC = {
    "page": "T",
    "sections": [
        {
            "columns": [8, 4],
            "parts": [
                {"component": "NewsWebPart"},
                {"text": "aside", "column": 2},
            ],
        },
        {"type": "three", "parts": [{"component": "NewsWebPart", "column": 3}]},
        {"columns": [6, 6], "parts": [{"text": "left"}, {"text": "right", "column": 2}]},
    ],
}


class TestConstants:
    def test_every_named_type_is_a_measured_set(self):
        # The named layouts are exactly the measured sets; sections.py
        # holds both tables next to each other on purpose.
        assert {tuple(f) for f in SECTION_FACTORS.values()} == set(MEASURED_FACTOR_SETS)
        assert set(EVIDENCE) == set(MEASURED_FACTOR_SETS)

    def test_layout_name_is_the_reverse_lookup(self):
        for name, factors in SECTION_FACTORS.items():
            assert layout_name(tuple(factors)) == name
        assert layout_name((5, 7)) is None
        assert layout_name((12, 0)) is None

    def test_layout_variant_labels_name_the_probe_s_sections(self):
        assert set(LAYOUT_VARIANT_FACTORS.values()) == {(8, 4), (4, 8)}
        for factors in LAYOUT_VARIANT_FACTORS.values():
            assert factors in MEASURED_FACTOR_SETS


class TestSectionTree:
    @pytest.mark.parametrize(
        "factors", MEASURED_FACTOR_SETS, ids=lambda f: "-".join(str(n) for n in f)
    )
    def test_columns_yield_one_section_with_the_measured_factors(self, factors):
        (section,) = section_tree(spec({"columns": list(factors), "parts": []}))
        assert isinstance(section, Section)
        assert section.index == 1
        assert section.factors == factors
        assert [c.factor for c in section.columns] == list(factors)
        assert all(isinstance(c, SectionColumn) and c.controls == () for c in section.columns)
        assert section.measured is True
        assert section.type_name is None
        assert section.layout == layout_name(factors)
        # The set was read back in this fixture key (module docstring).
        assert EVIDENCE[factors] in m5_document()

    @pytest.mark.parametrize("type_name", sorted(SECTION_FACTORS))
    def test_a_named_type_and_its_explicit_columns_build_the_same_geometry(self, type_name):
        factors = SECTION_FACTORS[type_name]
        parts = [{"component": "NewsWebPart", "column": len(factors)}, {"text": "hi"}]
        (named,) = section_tree(spec({"type": type_name, "parts": parts}))
        (explicit,) = section_tree(spec({"columns": factors, "parts": parts}))
        assert named.type_name == type_name
        assert named.layout == explicit.layout == type_name
        assert named.factors == explicit.factors == tuple(factors)
        assert named.columns == explicit.columns
        assert named.placements == explicit.placements

    def test_the_default_section_is_type_one(self):
        (section,) = section_tree(spec({"parts": [{"text": "hi"}]}))
        assert (section.type_name, section.layout, section.factors) == ("one", "one", (12,))

    def test_parts_land_in_their_columns_and_keep_written_order(self):
        # The split-4-8-two measurement: a column-2 control written before
        # its column-1 neighbour, stored in that order, controlIndex per
        # section (discovery.m5.json layoutVariants, labels
        # split-4-8-two-col2 then split-4-8-two-col1).
        tree = section_tree(
            spec(
                {
                    "columns": [4, 8],
                    "parts": [
                        {"component": "NewsWebPart", "column": 2},
                        {"component": "NewsWebPart"},
                        {"text": "third", "column": 2},
                    ],
                },
                {"type": "one", "parts": [{"text": "fourth"}]},
            )
        )
        first, second = tree
        assert [c.factor for c in first.columns] == [4, 8]
        assert [p.ordinal for p in first.columns[0].controls] == [2]
        assert [p.ordinal for p in first.columns[1].controls] == [1, 3]
        assert [(p.ordinal, p.column, p.control_index) for p in first.placements] == [
            (1, 2, 1),
            (2, 1, 2),
            (3, 2, 3),
        ]
        assert [p.section_factor for p in first.placements] == [8, 4, 8]
        assert second.index == 2
        assert [(p.ordinal, p.section, p.kind) for p in second.placements] == [(4, 2, "text")]
        # The flat view is the tree's written order, and placements() is it.
        assert [p.ordinal for p in written_order(tree)] == [1, 2, 3, 4]
        assert placements(
            spec(
                {
                    "columns": [4, 8],
                    "parts": [
                        {"component": "NewsWebPart", "column": 2},
                        {"component": "NewsWebPart"},
                        {"text": "third", "column": 2},
                    ],
                },
                {"type": "one", "parts": [{"text": "fourth"}]},
            )
        ) == written_order(tree)
        assert all(isinstance(p, Placement) for p in written_order(tree))

    def test_a_legal_unmeasured_set_is_flagged_and_named_columns(self):
        with pytest.warns(UserWarning, match="unmeasured"):
            (section,) = section_tree(spec({"columns": [5, 7], "parts": []}))
        assert section.factors == (5, 7)
        assert section.measured is False
        assert section.layout == "columns"
        assert [c.factor for c in section.columns] == [5, 7]


class TestConsumers:
    """The compiler and the preview read the tree; nothing re-derives it."""

    def test_compiled_positions_are_the_tree_s(self):
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        result = compile_page(copy.deepcopy(CONSUMER_SPEC), cat)
        expected = [
            (float(p.section), float(p.control_index), p.section_factor)
            for p in written_order(section_tree(CONSUMER_SPEC))
        ]
        assert [
            (pos["sectionIndex"], pos["controlIndex"], pos["sectionFactor"])
            for pos in positions(result.canvas)
        ] == expected
        assert expected == [
            (1.0, 1.0, 8),
            (1.0, 2.0, 4),
            (2.0, 1.0, 4),
            (3.0, 1.0, 6),
            (3.0, 2.0, 6),
        ]

    def test_preview_columns_are_the_tree_s(self):
        preview = build_preview(copy.deepcopy(CONSUMER_SPEC))
        tree = section_tree(CONSUMER_SPEC)
        assert [s.index for s in preview.sections] == [s.index for s in tree]
        assert [[c.factor for c in s.columns] for s in preview.sections] == [
            [8, 4],
            [4, 4, 4],
            [6, 6],
        ]
        assert [[len(c.parts) for c in s.columns] for s in preview.sections] == [
            [len(c.controls) for c in s.columns] for s in tree
        ]
        # The column-2 part of a columns: section is present (review
        # 2026-09-07 P1-2), and the section is labelled by its layout.
        aside = preview.sections[0].columns[1].parts[0]
        assert (aside.kind, aside.html) == ("text", "<p>aside</p>")
        assert [s.type for s in preview.sections] == ["two-thirds", "three", "two"]
        html = render_preview(preview)
        assert re.findall(r'<section data-section="(\d+)" data-type="([\w-]+)">', html) == [
            ("1", "two-thirds"),
            ("2", "three"),
            ("3", "two"),
        ]

    def test_an_unnamed_set_previews_as_columns(self):
        with pytest.warns(UserWarning, match="unmeasured"):
            preview = build_preview(spec({"columns": [5, 7], "parts": [{"text": "x"}]}))
        assert preview.sections[0].type == "columns"
        assert 'data-type="columns"' in render_preview(preview)


class TestMeasuredFixture:
    """The M5 fixture read through the section vocabulary and the one decoder."""

    @pytest.fixture(scope="class")
    def doc(self):
        return m5_document()

    def test_stored_canvas_round_trips_byte_exact(self, doc):
        stored = doc["storedCanvas"]
        canvas = Canvas.parse(stored)
        assert len(canvas.controls) == stored.count('<div data-sp-canvascontrol=""')
        assert len(canvas.controls) >= doc["placements"]["storedControlCount"]
        assert canvas.render() == stored

    def test_default_sections_read_back_with_their_named_factors(self, doc):
        # discover.js.j2 lays one/two/three out at sectionIndex 1-3; every
        # control of each section carries that type's column factor (the
        # spread uses columns 1 and 2, so a two- or three-column section
        # shows one factor per control, never a different one).
        by_section: dict[int, set[int]] = {}
        for pos in positions(doc["storedCanvas"]):
            index = int(pos["sectionIndex"])
            if index in (1, 2, 3):
                by_section.setdefault(index, set()).add(int(pos["sectionFactor"]))
        assert by_section == {
            1: set(SECTION_FACTORS["one"]),
            2: set(SECTION_FACTORS["two"]),
            3: set(SECTION_FACTORS["three"]),
        }

    def test_layout_variants_carry_the_shared_factor_sets(self, doc):
        cat = parse_discovery(doc)
        assert len(cat.layout_variants) == doc["placements"]["layoutVariantCount"] == 4
        assert {v.factors for v in cat.layout_variants} == {(8, 4), (4, 8)}
        for variant in cat.layout_variants:
            assert variant.factors == LAYOUT_VARIANT_FACTORS[variant.section]
            assert variant.column is not None
            assert variant.section_factor == variant.factors[variant.column - 1]
            assert variant.persisted_matches() is True
        assert [(v.section, v.column) for v in cat.layout_variants] == [
            ("split-8-4", 1),
            ("split-4-8", 1),
            ("split-4-8-two", 2),
            ("split-4-8-two", 1),
        ]

    def test_persisted_layout_blocks_decode_to_the_probe_s_own_reading(self, doc):
        # canvas.py's decode of the stored block equals the DOMParser +
        # JSON.parse reading the probe recorded beside it.
        for row in doc["layoutVariants"]["persisted"]:
            (control,) = Canvas.parse(row["canvas"]).controls
            assert control.control_data == row["controlData"]
            assert decode_attribute(control.controldata_raw) == row["controlData"]

    def test_catalogue_reads_stored_web_part_data_through_the_canvas_decoder(self, doc):
        cat = parse_discovery(doc)
        persisted = {row["id"]: row for row in doc["listBindings"]["persisted"]}
        assert persisted
        for binding in cat.list_bindings:
            row = persisted.get(binding.control_id)
            if row is None or not isinstance(row.get("canvas"), str):
                assert binding.stored_web_part_data is None
                continue
            assert binding.stored_web_part_data == row["webPartData"]
            assert binding.stored_properties == row["webPartData"]["properties"]
        assert sum(b.stored_web_part_data is not None for b in cat.list_bindings) == len(
            persisted
        )


class TestScriptsSpeakTheSameFactors:
    """The JS side spells its factor tables as literals; pin them to ours."""

    def test_discover_spread_factors_are_the_named_types(self):
        script = generate_discover_script()
        literal = re.search(r"const FACTORS = \{\n(.*?)\n\s*\};", script, re.S)
        assert literal, "no FACTORS literal"
        found = {
            name: json.loads(factors)
            for name, factors in re.findall(r"(\w+): (\[[^\]]*\])", literal.group(1))
        }
        assert found == {name: SECTION_FACTORS[name] for name in found}
        assert set(found) == {"one", "two", "three"}

    def test_probe_layout_samples_are_the_layout_variant_table(self):
        script = generate_findprobe_script(load_findings(FINDINGS))
        literal = re.search(r"const LAYOUT_SAMPLES = \[\n(.*?)\n\s*\];", script, re.S)
        assert literal, "no LAYOUT_SAMPLES literal"
        found = {
            section: tuple(json.loads(factors))
            for section, factors in re.findall(
                r'section: "([^"]+)", factors: (\[[^\]]*\])', literal.group(1)
            )
        }
        assert found == LAYOUT_VARIANT_FACTORS
