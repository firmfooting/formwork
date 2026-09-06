"""Catalogue accessors for the M5 discover probes.

The discover paste-in (M5, 2026-09-06) adds three additive keys to
``formwork.discovery/v1``: ``webpartProperties`` (a default and a modified
instance per web part), ``layoutVariants`` (the one-third factor orders and
column alignment) and ``listBindings`` (parts bound to two fixture containers
the script creates and recycles). The catalogue carries each as typed
samples paired by control id; nothing in the DSL consumes them yet. These
tests are written against a synthetic document in the wire shape the
template emits, so the accessors are pinned before a live run exists.
"""

import copy
import json
import pathlib

from formwork.canvas import escape_attribute
from formwork.catalogue import (
    Catalogue,
    LayoutVariant,
    ListBinding,
    ProbeList,
    PropertySample,
    parse_discovery,
)
from test_dsl import DISCOVERY


def control_data(control_id: str, section_factor: int, control_index: int) -> dict:
    return {
        "controlType": 3,
        "id": control_id,
        "position": {
            "zoneIndex": 9000,
            "sectionIndex": 9,
            "controlIndex": control_index,
            "zoneId": None,
            "sectionFactor": section_factor,
            "layoutIndex": 1,
        },
        "webPartId": "11111111-1111-1111-1111-111111111111",
        "emphasis": {},
    }


def web_part_block(cd: dict, wpd: dict) -> str:
    """The block the discover script writes for a web-part control."""
    return (
        '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0" data-sp-controldata="'
        + escape_attribute(json.dumps(cd, separators=(",", ":")))
        + '"><div data-sp-webpartdata="'
        + escape_attribute(json.dumps(wpd, separators=(",", ":")))
        + '"></div></div>'
    )


PROP_DEFAULT_ID = "00000000-0000-0000-0005-000000000001"
PROP_MODIFIED_ID = "00000000-0000-0000-0005-000000000002"
PROP_MISSING_ID = "00000000-0000-0000-0005-000000000003"


def property_rows() -> dict:
    default_wpd = {"id": "1" * 36, "instanceId": PROP_DEFAULT_ID, "properties": {"layoutId": "A"}}
    modified_wpd = {
        "id": "1" * 36,
        "instanceId": PROP_MODIFIED_ID,
        "properties": {"layoutId": "B"},
    }
    default_block = web_part_block(control_data(PROP_DEFAULT_ID, 12, 1), default_wpd)
    modified_block = web_part_block(control_data(PROP_MODIFIED_ID, 12, 2), modified_wpd)
    return {
        "requested": [
            {
                "component": "NewsWebPart",
                "id": PROP_DEFAULT_ID,
                "variant": "default",
                "propertyPath": "layoutId",
                "oldValue": "A",
                "newValue": "A",
                "canvas": default_block,
            },
            {
                "component": "NewsWebPart",
                "id": PROP_MODIFIED_ID,
                "variant": "modified",
                "propertyPath": "layoutId",
                "oldValue": "A",
                "newValue": "B",
                "canvas": modified_block,
            },
            {
                "component": "NewsWebPart",
                "id": PROP_MISSING_ID,
                "variant": "modified",
                "propertyPath": "layoutId",
                "oldValue": "A",
                "newValue": "C",
                "canvas": "<x>",
            },
        ],
        "persisted": [
            {
                "id": PROP_DEFAULT_ID,
                "propertyPath": "layoutId",
                "present": True,
                "storedValue": "A",
                "canvas": default_block,
            },
            {
                "id": PROP_MODIFIED_ID,
                "propertyPath": "layoutId",
                "present": True,
                "storedValue": "B",
                "canvas": modified_block,
            },
        ],
        "skipped": [{"component": "HeroWebPart", "why": "not placeable on this site"}],
    }


LAYOUT_ID = "00000000-0000-0000-0006-000000000001"
LAYOUT_CD = control_data(LAYOUT_ID, 8, 2)
LAYOUT_BLOCK = web_part_block(LAYOUT_CD, {"id": "1" * 36, "instanceId": LAYOUT_ID})


def layout_rows() -> dict:
    row = {"label": "split-4-8-col2", "id": LAYOUT_ID, "controlData": LAYOUT_CD}
    return {
        "requested": [
            row | {"canvas": LAYOUT_BLOCK},
            {
                "label": "split-8-4-col1",
                "id": "00000000-0000-0000-0006-000000000002",
                "controlData": control_data("00000000-0000-0000-0006-000000000002", 8, 1),
                "canvas": "<y>",
            },
        ],
        "persisted": [row | {"canvas": LAYOUT_BLOCK}],
    }


BINDING_ID = "00000000-0000-0000-0007-000000000001"
LIST_ID = "3ea65699-0f63-4592-ba66-28d1a8b68968"
BINDING_WPD = {
    "id": "f92bf067-bc19-489e-a556-7fe95f508720",
    "instanceId": BINDING_ID,
    "title": "Document library",
    "description": "",
    "serverProcessedContent": {
        "htmlStrings": {},
        "searchablePlainTexts": {"listTitle": "Formwork Probe Docs"},
        "imageSources": {},
        "links": {},
    },
    "dataVersion": "1.0",
    "properties": {
        "isDocumentLibrary": True,
        "filterBy": {},
        "selectedListId": LIST_ID,
        "selectedListUrl": "/sites/T/Formwork Probe Docs",
        "webRelativeListUrl": "Formwork Probe Docs",
        "webpartHeightKey": 4,
        "selectedViewId": "e150a99e-f3e3-4c81-811f-882c8036c862",
        "hideCommandBar": False,
    },
}
BINDING_BLOCK = web_part_block(control_data(BINDING_ID, 12, 1), BINDING_WPD)


def binding_rows() -> dict:
    target = {
        "key": "library",
        "title": "Formwork Probe Docs",
        "listId": LIST_ID,
        "serverRelativeUrl": "/sites/T/Formwork Probe Docs",
        "webRelativeUrl": "Formwork Probe Docs",
        "defaultViewId": "e150a99e-f3e3-4c81-811f-882c8036c862",
        "defaultViewUrl": "/sites/T/Formwork Probe Docs/Forms/AllItems.aspx",
    }
    return {
        "fixtures": [
            {
                "key": "list",
                "title": "Formwork Probe Source",
                "baseTemplate": 100,
                "created": False,
                "status": 500,
                "reason": "A list, survey, discussion board, or document library with the "
                "specified title already exists in this Web site.",
                "id": None,
                "serverRelativeUrl": None,
                "webRelativeUrl": None,
                "defaultViewId": None,
                "defaultViewUrl": None,
                "recycled": None,
                "recycleStatus": 0,
            },
            {
                "key": "library",
                "title": "Formwork Probe Docs",
                "baseTemplate": 101,
                "created": True,
                "status": 201,
                "reason": "",
                "id": LIST_ID,
                "serverRelativeUrl": "/sites/T/Formwork Probe Docs",
                "webRelativeUrl": "Formwork Probe Docs",
                "defaultViewId": "e150a99e-f3e3-4c81-811f-882c8036c862",
                "defaultViewUrl": "/sites/T/Formwork Probe Docs/Forms/AllItems.aspx",
                "recycled": True,
                "recycleStatus": 200,
            },
        ],
        "requested": [
            {
                "label": "library-part-to-library",
                "component": "ListWebPart",
                "entry": 1,
                "id": BINDING_ID,
                "target": target,
                "controlData": control_data(BINDING_ID, 12, 1),
                "webPartData": BINDING_WPD,
                "canvas": BINDING_BLOCK,
            },
            {
                "label": "quick-links-to-library",
                "component": "QuickLinksWebPart",
                "entry": 0,
                "id": "00000000-0000-0000-0007-000000000002",
                "target": target,
                "controlData": control_data("00000000-0000-0000-0007-000000000002", 12, 2),
                "webPartData": {"id": "c" * 36, "properties": {"items": [{"id": 1}]}},
                "canvas": "<z>",
            },
        ],
        "persisted": [
            {
                "label": "library-part-to-library",
                "id": BINDING_ID,
                "controlData": control_data(BINDING_ID, 12, 1),
                "canvas": BINDING_BLOCK,
                "webPartData": BINDING_WPD,
            }
        ],
        "skipped": [{"target": "list", "why": "fixture not created: already exists"}],
    }


def m5_document() -> dict:
    return copy.deepcopy(DISCOVERY) | {
        "webpartProperties": property_rows(),
        "layoutVariants": layout_rows(),
        "listBindings": binding_rows(),
    }


class TestAdditiveKeys:
    def test_a_document_without_the_probes_parses_to_empty_tuples(self):
        for key in ("webpartProperties", "layoutVariants", "listBindings"):
            assert key not in DISCOVERY
        cat = parse_discovery(DISCOVERY)
        assert cat.property_samples == ()
        assert cat.layout_variants == ()
        assert cat.probe_lists == ()
        assert cat.list_bindings == ()

    def test_the_catalogue_defaults_stay_constructible_without_them(self):
        cat = Catalogue(components=())
        assert (cat.property_samples, cat.layout_variants, cat.probe_lists, cat.list_bindings) == (
            (),
            (),
            (),
            (),
        )

    def test_malformed_blocks_are_tolerated(self):
        for raw in (None, "nope", 7, [], {"requested": "x"}, {"persisted": [1, {"id": "a"}]}):
            doc = copy.deepcopy(DISCOVERY) | {
                "webpartProperties": raw,
                "layoutVariants": raw,
                "listBindings": raw,
            }
            cat = parse_discovery(doc)
            assert cat.property_samples == ()
            assert cat.layout_variants == ()
            assert cat.probe_lists == ()
            assert cat.list_bindings == ()

    def test_the_styling_fixture_still_parses_and_carries_nothing_new(self):
        # The live 2026-09-06 document predates M5: same catalogue as before.
        fixture = pathlib.Path(__file__).parent / "fixtures" / "discovery.styling.json"
        cat = parse_discovery(json.loads(fixture.read_text(encoding="utf-8")))
        assert cat.count == 285
        assert len(cat.text_controls) == 2
        assert cat.property_samples == ()
        assert cat.layout_variants == ()
        assert cat.list_bindings == ()


class TestPropertySamples:
    def test_pairs_requested_with_persisted_by_control_id(self):
        cat = parse_discovery(m5_document())
        assert [s.control_id for s in cat.property_samples] == [
            PROP_DEFAULT_ID,
            PROP_MODIFIED_ID,
            PROP_MISSING_ID,
        ]
        default, modified, missing = cat.property_samples
        assert isinstance(default, PropertySample)
        assert (default.component, default.variant, default.property_path) == (
            "NewsWebPart",
            "default",
            "layoutId",
        )
        assert (default.old_value, default.new_value) == ("A", "A")
        assert (modified.old_value, modified.new_value) == ("A", "B")
        assert modified.persisted == modified.requested
        assert modified.stored_value == "B"
        assert modified.stored_present is True
        assert missing.persisted is None
        assert missing.stored_value is None
        assert missing.stored_present is False

    def test_value_round_tripped_is_the_stored_value_against_the_new_value(self):
        default, modified, missing = parse_discovery(m5_document()).property_samples
        assert default.value_round_tripped() is True
        assert modified.value_round_tripped() is True
        assert missing.value_round_tripped() is None
        doc = m5_document()
        doc["webpartProperties"]["persisted"][1]["storedValue"] = "A"
        assert parse_discovery(doc).property_samples[1].value_round_tripped() is False
        doc["webpartProperties"]["persisted"][1]["present"] = False
        assert parse_discovery(doc).property_samples[1].value_round_tripped() is False

    def test_persisted_matches_folds_the_colon_like_a_text_sample(self):
        doc = m5_document()
        doc["webpartProperties"]["persisted"][0]["canvas"] = (
            doc["webpartProperties"]["persisted"][0]["canvas"].replace("&#58;", ":")
        )
        doc["webpartProperties"]["persisted"][1]["canvas"] = "<other>"
        default, modified, missing = parse_discovery(doc).property_samples
        assert default.persisted != default.requested
        assert default.persisted_matches() is True
        assert modified.persisted_matches() is False
        assert missing.persisted_matches() is None

    def test_a_null_stored_value_is_kept_apart_from_an_absent_one(self):
        doc = m5_document()
        doc["webpartProperties"]["persisted"][1] |= {"present": True, "storedValue": None}
        sample = parse_discovery(doc).property_samples[1]
        assert sample.stored_present is True
        assert sample.stored_value is None
        assert sample.value_round_tripped() is False

    def test_by_component_groups_the_pair(self):
        cat = parse_discovery(m5_document())
        news = cat.property_samples_for("NewsWebPart")
        assert [s.variant for s in news] == ["default", "modified", "modified"]
        assert cat.property_samples_for("HeroWebPart") == ()


class TestLayoutVariants:
    def test_pairs_by_id_and_exposes_the_position(self):
        cat = parse_discovery(m5_document())
        assert [v.label for v in cat.layout_variants] == ["split-4-8-col2", "split-8-4-col1"]
        first, second = cat.layout_variants
        assert isinstance(first, LayoutVariant)
        assert first.control_id == LAYOUT_ID
        assert first.control_data == LAYOUT_CD
        assert (first.section_factor, first.control_index) == (8, 2)
        assert first.requested == LAYOUT_BLOCK
        assert first.persisted == LAYOUT_BLOCK
        assert first.persisted_matches() is True
        assert second.persisted is None
        assert second.persisted_matches() is None

    def test_position_accessors_tolerate_a_missing_position(self):
        doc = m5_document()
        doc["layoutVariants"]["requested"][0]["controlData"] = {"controlType": 3}
        variant = parse_discovery(doc).layout_variants[0]
        assert variant.section_factor is None
        assert variant.control_index is None

    def test_by_label(self):
        cat = parse_discovery(m5_document())
        assert cat.layout_variant("split-8-4-col1").persisted is None
        assert cat.layout_variant("nope") is None


class TestListBindings:
    def test_fixture_lists_are_carried_with_their_outcome(self):
        cat = parse_discovery(m5_document())
        assert [f.key for f in cat.probe_lists] == ["list", "library"]
        failed, library = cat.probe_lists
        assert isinstance(failed, ProbeList)
        assert failed.created is False
        assert failed.recycled is None
        assert "already exists" in failed.reason
        assert failed.list_id is None
        assert library.created is True
        assert library.recycled is True
        assert library.base_template == 101
        assert library.list_id == LIST_ID
        assert library.server_relative_url == "/sites/T/Formwork Probe Docs"
        assert library.web_relative_url == "Formwork Probe Docs"
        assert library.default_view_id == "e150a99e-f3e3-4c81-811f-882c8036c862"
        assert library.default_view_url == "/sites/T/Formwork Probe Docs/Forms/AllItems.aspx"

    def test_bindings_pair_by_id_and_record_the_target(self):
        cat = parse_discovery(m5_document())
        assert [b.label for b in cat.list_bindings] == [
            "library-part-to-library",
            "quick-links-to-library",
        ]
        bound, links = cat.list_bindings
        assert isinstance(bound, ListBinding)
        assert (bound.component, bound.entry, bound.target) == ("ListWebPart", 1, "library")
        assert bound.list_id == LIST_ID
        assert bound.list_url == "/sites/T/Formwork Probe Docs"
        assert bound.web_part_data == BINDING_WPD
        assert bound.properties["selectedListId"] == LIST_ID
        assert bound.requested == BINDING_BLOCK
        assert bound.persisted == BINDING_BLOCK
        assert bound.stored_web_part_data == BINDING_WPD
        assert bound.stored_properties == BINDING_WPD["properties"]
        assert bound.persisted_matches() is True
        assert links.component == "QuickLinksWebPart"
        assert links.persisted is None
        assert links.stored_web_part_data is None
        assert links.stored_properties is None
        assert links.persisted_matches() is None

    def test_probe_list_lookup_by_key(self):
        cat = parse_discovery(m5_document())
        assert cat.probe_list("library").created is True
        assert cat.probe_list("nope") is None

    def test_a_binding_without_a_target_block_still_parses(self):
        doc = m5_document()
        del doc["listBindings"]["requested"][0]["target"]
        bound = parse_discovery(doc).list_bindings[0]
        assert (bound.target, bound.list_id, bound.list_url) == ("", "", "")
