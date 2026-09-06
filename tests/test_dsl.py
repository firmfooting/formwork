"""Tests for the component catalogue and the page-spec DSL."""

import copy
import json

import pytest

from formwork.canvas import Canvas, escape_attribute
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

# The text-control probe's output, in the shape discover.js.j2 step 3a/4a
# emits: the requested block is what the script wrote, the persisted block is
# what SharePoint stored (here: identical, which is the still-unmeasured
# assumption the compiler runs on).
TEXT_ID = "00000000-0000-0000-0001-000000000001"
TEXT_HTML = "<h2>Formwork text probe</h2><p>Paragraph with <b>bold</b>.</p>"
TEXT_CONTROL_DATA = {
    "controlType": 4,
    "id": TEXT_ID,
    "position": {
        "zoneIndex": 4000,
        "sectionIndex": 4,
        "controlIndex": 1,
        "zoneId": None,
        "sectionFactor": 12,
        "layoutIndex": 1,
    },
    "emphasis": {},
    "editorType": "CKEditor",
}
TEXT_BLOCK = (
    '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0" data-sp-controldata="'
    + escape_attribute(json.dumps(TEXT_CONTROL_DATA, separators=(",", ":")))
    + '"><div data-sp-rte="">'
    + TEXT_HTML
    + "</div></div>"
)
DISCOVERY_WITH_TEXT = copy.deepcopy(DISCOVERY) | {
    "textControls": {
        "requested": [
            {
                "id": TEXT_ID,
                "html": TEXT_HTML,
                "controlData": TEXT_CONTROL_DATA,
                "canvas": TEXT_BLOCK,
            },
            {"id": "00000000-0000-0000-0001-000000000002", "html": "<p>2</p>", "canvas": "<x>"},
        ],
        "persisted": [{"id": TEXT_ID, "controlData": TEXT_CONTROL_DATA, "canvas": TEXT_BLOCK}],
    }
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

    def test_description_comes_from_the_first_preconfigured_entry(self):
        cat = parse_discovery(DISCOVERY)
        assert cat.by_alias("NewsWebPart").description == "News description"

    def test_discovery_without_text_controls_still_parses(self):
        # The key is additive: a document from before the probe is unchanged.
        assert "textControls" not in DISCOVERY
        assert parse_discovery(DISCOVERY).text_controls == ()

    def test_text_controls_pair_requested_with_persisted_by_id(self):
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        assert [t.control_id for t in cat.text_controls] == [
            TEXT_ID,
            "00000000-0000-0000-0001-000000000002",
        ]
        first, second = cat.text_controls
        assert first.html == TEXT_HTML
        assert first.requested == TEXT_BLOCK
        assert first.persisted == TEXT_BLOCK
        assert second.persisted is None  # the readback did not carry it

    def test_malformed_text_controls_are_tolerated(self):
        for raw in (None, "nope", [], {"requested": "x"}, {"persisted": [1, {"id": "a"}]}):
            doc = copy.deepcopy(DISCOVERY) | {"textControls": raw}
            assert parse_discovery(doc).text_controls == ()


class TestTextParts:
    """A text block is not a web part: controlType 4, no webPartId, the HTML
    as the inner content of a data-sp-rte child. Shape per the discover probe;
    the persisted form is the measurement still pending (see dsl._text_control)."""

    def spec(self, text, **extra):
        return {
            "page": "T",
            "sections": [
                {
                    "type": "two-thirds",
                    "parts": [
                        {"component": "NewsWebPart"},
                        {"text": text, "column": 2, **extra},
                    ],
                }
            ],
        }

    def test_text_part_compiles_to_a_control_type_4_control(self):
        cat = parse_discovery(DISCOVERY)
        result = compile_page(self.spec("<p>Hello <b>there</b></p>"), cat)
        news, text = Canvas.parse(result.canvas).controls
        assert news.control_data["controlType"] == 3
        assert text.control_data["controlType"] == 4
        assert "webPartId" not in text.control_data
        assert text.web_part_data is None
        assert text.control_data["editorType"] == "CKEditor"
        assert text.control_data["id"] == "00000000-0000-0000-0000-000000000002"
        # The last control's body also carries the page wrapper's own close.
        assert text.body == '<div data-sp-rte=""><p>Hello <b>there</b></p></div></div>' + "</div>"

    def test_text_part_is_positioned_like_any_other_part(self):
        cat = parse_discovery(DISCOVERY)
        result = compile_page(self.spec("<p>x</p>"), cat)
        text = Canvas.parse(result.canvas).controls[1]
        assert text.control_data["position"] == {
            "zoneIndex": 1000.0,
            "sectionIndex": 1.0,
            "controlIndex": 2.0,
            "zoneId": None,
            "sectionFactor": 4,
            "layoutIndex": 1,
        }

    def test_control_data_is_escaped_in_the_measured_style(self):
        cat = parse_discovery(DISCOVERY)
        result = compile_page(self.spec("<p>x</p>"), cat)
        text = Canvas.parse(result.canvas).controls[1]
        assert text.controldata_raw.startswith("&#123;&quot;controlType&quot;&#58;4,")
        assert "{" not in text.open_tag
        # The HTML itself is inner content, written as-is: no entity noise.
        assert '<div data-sp-rte=""><p>x</p></div>' in result.canvas

    def test_compiled_text_part_round_trips_through_canvas_parse_byte_exactly(self):
        cat = parse_discovery(DISCOVERY)
        result = compile_page(self.spec("<p>A &amp; B: {c}</p>"), cat)
        parsed = Canvas.parse(result.canvas)
        assert [c.control_data["controlType"] for c in parsed.controls] == [3, 4]
        assert parsed.render() == result.canvas
        # And after the dirty path re-serialises from the decoded dicts.
        for control in parsed.controls:
            control.mark_dirty()
        assert parsed.render() == result.canvas

    def test_markdown_text_part_is_converted(self):
        cat = parse_discovery(DISCOVERY)
        result = compile_page(self.spec("## Hi\n\nSome **bold** and a [link](/x)."), cat)
        assert (
            '<div data-sp-rte=""><h2>Hi</h2><p>Some <strong>bold</strong> and a '
            '<a href="/x">link</a>.</p></div>' in result.canvas
        )
        assert result.parts[1]["kind"] == "text"
        assert result.parts[1]["html"].startswith("<h2>Hi</h2>")

    def test_format_is_honoured(self):
        cat = parse_discovery(DISCOVERY)
        result = compile_page(self.spec("plain words", format="markdown"), cat)
        assert '<div data-sp-rte=""><p>plain words</p></div>' in result.canvas
        with pytest.raises(DslError, match="part 2: unknown text format"):
            compile_page(self.spec("x", format="rtf"), cat)

    def test_unsupported_markdown_refuses_with_the_part_and_line(self):
        cat = parse_discovery(DISCOVERY)
        with pytest.raises(DslError, match="part 2: line 1: tables"):
            compile_page(self.spec("a | b"), cat)

    def test_text_must_be_a_non_empty_string(self):
        cat = parse_discovery(DISCOVERY)
        with pytest.raises(DslError, match="part 2: 'text' must be a non-empty string"):
            compile_page(self.spec("   "), cat)
        with pytest.raises(DslError, match="part 2: 'text' must be a non-empty string"):
            compile_page(self.spec(42), cat)

    def test_a_part_names_exactly_one_of_component_or_text(self):
        cat = parse_discovery(DISCOVERY)
        both = {"page": "T", "sections": [{"parts": [{"component": "NewsWebPart", "text": "x"}]}]}
        neither = {"page": "T", "sections": [{"parts": [{"column": 1}]}]}
        for spec in (both, neither):
            with pytest.raises(DslError, match="exactly one of 'component' or 'text'"):
                compile_page(spec, cat)

    def test_text_part_does_not_need_the_catalogue_to_know_it(self):
        # Nothing to resolve: a text part compiles against an empty catalogue.
        spec = {"page": "T", "sections": [{"parts": [{"text": "<p>x</p>"}]}]}
        result = compile_page(spec, Catalogue(components=()))
        assert result.parts == [
            {
                "kind": "text",
                "component": "text",
                "title": "Text",
                "html": "<p>x</p>",
                "section": 1,
                "column": 1,
                "controlIndex": 1,
            }
        ]

    def test_compiled_canvas_stays_balanced_with_text_parts(self):
        cat = parse_discovery(DISCOVERY)
        result = compile_page(self.spec("<div><p>x</p></div>"), cat)
        assert result.canvas.count("<div") == result.canvas.count("</div>")


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
        assert [p["kind"] for p in result.parts] == ["component"] * 3

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
