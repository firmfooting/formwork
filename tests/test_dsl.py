"""Tests for the component catalogue and the page-spec DSL."""

import json

import pytest

from formwork.canvas import Canvas
from formwork.catalogue import Catalogue, parse_discovery
from formwork.dsl import DslError, compile_page


# A synthetic discovery document in the wire shape the discover script emits.
def make_component(cid: str, alias: str, title: str, hidden: bool = False):
    manifest = {
        "manifestVersion": 2,
        "id": cid,
        "alias": alias,
        "componentType": "WebPart",
        "isHidden": hidden,
        "preconfiguredEntries": [
            {
                "title": {"default": title},
                "description": {"default": f"{title} description"},
                "properties": {"layoutId": "Default"},
                "dataVersion": "1.0",
            }
        ],
    }
    return {
        "ComponentType": 1,
        "Id": cid,
        "Manifest": json.dumps(manifest),
    }


NEWS = make_component("11111111-1111-1111-1111-111111111111", "NewsWebPart", "News")
DOCLIB = make_component(
    "22222222-2222-2222-2222-222222222222", "DocumentLibraryWebPart", "Document library"
)
HIDDEN = make_component(
    "33333333-3333-3333-3333-333333333333", "SearchBoxWebPart", "Search box", hidden=True
)
EXTENSION = {"ComponentType": 2, "Id": "44444444-4444-4444-4444-444444444444", "Manifest": "{}"}

DISCOVERY = {
    "schema": "formwork.discovery/v1",
    "web": {"url": "https://x/sites/T", "id": "w" * 32},
    "components": [NEWS, DOCLIB, HIDDEN, EXTENSION],
    "placements": {
        "placed": ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"],
        "sections": [
            {"zoneIndex": 1.0, "type": "one", "factors": [12]},
            {"zoneIndex": 2.0, "type": "two", "factors": [6, 6]},
        ],
    },
}


class TestCatalogue:
    def test_parses_components_from_manifests(self):
        cat = parse_discovery(DISCOVERY)
        assert isinstance(cat, Catalogue)
        assert cat.count >= 2
        news = cat.by_alias("NewsWebPart")
        assert news.title == "News"
        assert news.component_id == "11111111-1111-1111-1111-111111111111"

    def test_hidden_parts_are_flagged(self):
        cat = parse_discovery(DISCOVERY)
        assert cat.by_alias("SearchBoxWebPart").hidden is True

    def test_lookup_by_title(self):
        cat = parse_discovery(DISCOVERY)
        assert cat.by_title("Document library").alias == "DocumentLibraryWebPart"

    def test_defaults_surface_preconfigured_properties(self):
        cat = parse_discovery(DISCOVERY)
        assert cat.by_alias("NewsWebPart").default_properties == {"layoutId": "Default"}


class TestCompilePage:
    def spec(self):
        return {
            "page": "Team home",
            "sections": [
                {
                    "type": "two-thirds",
                    "parts": [
                        {"component": "NewsWebPart"},
                        {"component": "Document library", "properties": {"selectedListId": "x"}},
                    ],
                },
                {"type": "one", "parts": [{"component": "NewsWebPart"}]},
            ],
        }

    def test_compiles_sections_and_parts_to_canvas(self):
        cat = parse_discovery(DISCOVERY)
        result = compile_page(self.spec(), cat)
        assert result.title == "Team home"
        canvas = Canvas.parse(result.canvas)
        assert canvas.render() == result.canvas  # valid, round-trippable markup
        titles = [c.web_part_title for c in canvas.web_part_controls()]
        assert titles == ["News", "Document library", "News"]

    def test_unknown_component_refuses_to_compile(self):
        cat = parse_discovery(DISCOVERY)
        spec = {"page": "X", "sections": [{"type": "one", "parts": [{"component": "Nope"}]}]}
        with pytest.raises(DslError, match="Nope"):
            compile_page(spec, cat)

    def test_hidden_component_refuses_with_reason(self):
        cat = parse_discovery(DISCOVERY)
        spec = {
            "page": "X",
            "sections": [{"type": "one", "parts": [{"component": "SearchBoxWebPart"}]}],
        }
        with pytest.raises(DslError, match="hidden"):
            compile_page(spec, cat)

    def test_section_factors_follow_sharepoint_model(self):
        cat = parse_discovery(DISCOVERY)
        spec = {
            "page": "X",
            "sections": [
                {
                    "type": "two-thirds",
                    "parts": [
                        {"component": "NewsWebPart"},
                        {"component": "NewsWebPart", "column": 2},
                    ],
                }
            ],
        }
        result = compile_page(spec, cat)
        controls = Canvas.parse(result.canvas).web_part_controls()
        factors = [c.control_data["position"]["sectionFactor"] for c in controls]
        assert factors == [8, 4]

    def test_property_overrides_reach_web_part_data(self):
        cat = parse_discovery(DISCOVERY)
        result = compile_page(self.spec(), cat)
        assert "selectedListId" in result.canvas

    def test_web_part_ids_come_from_the_catalogue(self):
        cat = parse_discovery(DISCOVERY)
        result = compile_page(self.spec(), cat)
        assert "11111111-1111-1111-1111-111111111111" in result.canvas

    def test_unsupported_section_type_refuses(self):
        cat = parse_discovery(DISCOVERY)
        spec = {"page": "X", "sections": [{"type": "seven-way", "parts": []}]}
        with pytest.raises(DslError, match="section type"):
            compile_page(spec, cat)

    def test_compiled_canvas_is_balanced_html(self):
        cat = parse_discovery(DISCOVERY)
        result = compile_page(self.spec(), cat)
        assert result.canvas.count("<div") == result.canvas.count("</div>")
