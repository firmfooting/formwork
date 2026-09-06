"""Tests for the component catalogue and the page-spec DSL."""

import copy
import json

import pytest

from formwork.canvas import Canvas, escape_attribute
from formwork.catalogue import Catalogue, parse_discovery
from formwork.dsl import (
    EMPHASIS_KEYS,
    ZONE_EMPHASIS_VALUES,
    DslError,
    compile_page,
    stored_text_html,
)


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
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
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
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
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
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        result = compile_page(self.spec("<p>x</p>"), cat)
        text = Canvas.parse(result.canvas).controls[1]
        assert text.controldata_raw.startswith("&#123;&quot;controlType&quot;&#58;4,")
        assert "{" not in text.open_tag
        # The HTML itself is inner content, written as-is: no entity noise.
        assert '<div data-sp-rte=""><p>x</p></div>' in result.canvas

    def test_compiled_text_part_round_trips_through_canvas_parse_byte_exactly(self):
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        result = compile_page(self.spec("<p>A &amp; B: {c}</p>"), cat)
        parsed = Canvas.parse(result.canvas)
        assert [c.control_data["controlType"] for c in parsed.controls] == [3, 4]
        assert parsed.render() == result.canvas
        # And after the dirty path re-serialises from the decoded dicts.
        for control in parsed.controls:
            control.mark_dirty()
        assert parsed.render() == result.canvas

    def test_markdown_text_part_is_converted(self):
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        result = compile_page(self.spec("## Hi\n\nSome **bold** and a [link](/x)."), cat)
        assert (
            '<div data-sp-rte=""><h2>Hi</h2><p>Some <strong>bold</strong> and a '
            '<a href="/x">link</a>.</p></div>' in result.canvas
        )
        assert result.parts[1]["kind"] == "text"
        assert result.parts[1]["html"].startswith("<h2>Hi</h2>")

    def test_format_is_honoured(self):
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        result = compile_page(self.spec("plain words", format="markdown"), cat)
        assert '<div data-sp-rte=""><p>plain words</p></div>' in result.canvas
        with pytest.raises(DslError, match="part 2: unknown text format"):
            compile_page(self.spec("x", format="rtf"), cat)

    def test_unsupported_markdown_refuses_with_the_part_and_line(self):
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        with pytest.raises(DslError, match="part 2: line 1: tables"):
            compile_page(self.spec("a | b"), cat)

    def test_text_must_be_a_non_empty_string(self):
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
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

    def test_text_part_does_not_need_the_catalogue_to_know_components(self):
        # No component resolution happens for a text part: an empty component
        # list compiles fine, as long as a persisted measurement exists (P2-3).
        spec = {"page": "T", "sections": [{"parts": [{"text": "<p>x</p>"}]}]}
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        result = compile_page(spec, Catalogue(components=(), text_controls=cat.text_controls))
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
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        result = compile_page(self.spec("<div><p>x</p></div>"), cat)
        assert result.canvas.count("<div") == result.canvas.count("</div>")


class TestEmphasis:
    """The ``emphasis:`` key on a component part (M3-DSL).

    Measured 2026-09-06 (tests/fixtures/discovery.styling.json,
    styling.sectionSamples): a web-part control sent with
    ``emphasis: {zoneEmphasis: 2}`` and one with ``{zoneEmphasis: 3, ...}``
    persisted byte-for-byte through the apply path's item MERGE, and every
    text control the probe read back carried ``emphasis: {}``.
    test_styling_evidence.py pins those bytes; these tests pin what the
    compiler makes of them, read back through Canvas.parse.
    """

    def spec(self, part, **section):
        return {"page": "T", "sections": [{"type": "one", "parts": [part], **section}]}

    def control(self, part):
        result = compile_page(self.spec(part), parse_discovery(DISCOVERY))
        return Canvas.parse(result.canvas).controls[0]

    def test_emphasis_block_reaches_the_control_data(self):
        control = self.control({"component": "NewsWebPart", "emphasis": {"zoneEmphasis": 2}})
        assert control.control_data["emphasis"] == {"zoneEmphasis": 2}
        # Same keys, same order, as the measured web-part controls.
        assert list(control.control_data) == [
            "controlType",
            "id",
            "position",
            "webPartId",
            "emphasis",
        ]

    def test_shorthand_integer_means_zone_emphasis(self):
        control = self.control({"component": "NewsWebPart", "emphasis": 3})
        assert control.control_data["emphasis"] == {"zoneEmphasis": 3}

    def test_without_emphasis_the_block_is_empty(self):
        # {} is what every probe control was sent with, and what SharePoint
        # kept on all of them.
        assert self.control({"component": "NewsWebPart"}).control_data["emphasis"] == {}
        explicit = self.control({"component": "NewsWebPart", "emphasis": {}})
        assert explicit.control_data["emphasis"] == {}

    def test_emphasis_is_escaped_in_the_measured_style_and_round_trips(self):
        result = compile_page(
            self.spec({"component": "NewsWebPart", "emphasis": 2}), parse_discovery(DISCOVERY)
        )
        escaped = "&quot;emphasis&quot;&#58;&#123;&quot;zoneEmphasis&quot;&#58;2&#125;"
        assert escaped in result.canvas
        parsed = Canvas.parse(result.canvas)
        assert parsed.render() == result.canvas
        for control in parsed.controls:
            control.mark_dirty()
        assert parsed.render() == result.canvas

    @pytest.mark.parametrize("value", ZONE_EMPHASIS_VALUES)
    def test_every_accepted_value_is_encoded_as_given(self, value):
        control = self.control({"component": "NewsWebPart", "emphasis": value})
        assert control.control_data["emphasis"] == {"zoneEmphasis": value}

    def test_the_accepted_set_is_the_editor_swatch_set(self):
        # 2 and 3 are measured; 1 and 4 are the editor's other two swatches
        # (see the ZONE_EMPHASIS_VALUES comment in dsl.py).
        assert ZONE_EMPHASIS_VALUES == (1, 2, 3, 4)
        assert {"zoneEmphasis"} == EMPHASIS_KEYS

    @pytest.mark.parametrize("value", [0, 5, -1, "2", 2.0, True, None, [2]])
    def test_values_outside_the_set_refuse_with_the_citation(self, value):
        with pytest.raises(
            DslError,
            match=r"part 1: emphasis\.zoneEmphasis must be an integer in \{1, 2, 3, 4\}"
            r".*sectionSamples.*2026-09-06",
        ):
            compile_page(
                self.spec({"component": "NewsWebPart", "emphasis": value}),
                parse_discovery(DISCOVERY),
            )

    def test_unknown_emphasis_keys_refuse(self):
        # The probe's unknown key echoed back from SharePoint; that is
        # survival, not rendering, so the DSL does not pass it through.
        part = {
            "component": "NewsWebPart",
            "emphasis": {"zoneEmphasis": 3, "formworkProbe": "x", "alpha": 1},
        }
        with pytest.raises(
            DslError, match=r"part 1: unknown emphasis key\(s\) alpha, formworkProbe"
        ):
            compile_page(self.spec(part), parse_discovery(DISCOVERY))

    def test_emphasis_on_a_text_part_refuses(self):
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        with pytest.raises(
            DslError, match=r"part 1: emphasis on text parts is not measured.*\{\}"
        ):
            compile_page(self.spec({"text": "<p>x</p>", "emphasis": 2}), cat)

    def test_section_level_emphasis_refuses_naming_the_measured_limitation(self):
        spec = self.spec({"component": "NewsWebPart"}, emphasis=2)
        with pytest.raises(
            DslError, match=r"section 1: section-level emphasis is not encodable.*SavePage"
        ):
            compile_page(spec, parse_discovery(DISCOVERY))

    @pytest.mark.parametrize("key", ["background", "spacing"])
    def test_unmeasured_section_styling_keys_refuse(self, key):
        spec = self.spec({"component": "NewsWebPart"}, **{key: "x"})
        with pytest.raises(DslError, match=rf"section 1: .*section-{key}"):
            compile_page(spec, parse_discovery(DISCOVERY))

    def test_theme_on_the_page_refuses(self):
        spec = {"page": "T", "theme": "x", "sections": [{"parts": []}]}
        with pytest.raises(DslError, match=r"spec: theme is not a page setting"):
            compile_page(spec, parse_discovery(DISCOVERY))

    def test_compiled_parts_report_the_emphasis(self):
        result = compile_page(
            self.spec({"component": "NewsWebPart", "emphasis": 2}), parse_discovery(DISCOVERY)
        )
        assert result.parts[0]["emphasis"] == {"zoneEmphasis": 2}
        plain = compile_page(self.spec({"component": "NewsWebPart"}), parse_discovery(DISCOVERY))
        assert plain.parts[0]["emphasis"] == {}

    def test_emphasis_is_carried_per_control(self):
        # The key lives on the part, so two parts in one section can differ.
        # SharePoint's own editor writes the same block on every control of a
        # section (tests/fixtures/savepage-section-emphasis.json); the DSL
        # does not enforce that, it encodes what the spec says.
        spec = {
            "page": "T",
            "sections": [
                {
                    "type": "two",
                    "parts": [
                        {"component": "NewsWebPart", "emphasis": 2},
                        {"component": "NewsWebPart", "column": 2},
                    ],
                }
            ],
        }
        canvas = Canvas.parse(compile_page(spec, parse_discovery(DISCOVERY)).canvas)
        assert [c.control_data["emphasis"] for c in canvas.controls] == [{"zoneEmphasis": 2}, {}]


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
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
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
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        result = compile_page(self.spec(), cat)
        assert "selectedListId" in result.canvas

    def test_web_part_ids_come_from_the_catalogue(self):
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        result = compile_page(self.spec(), cat)
        assert "11111111-1111-1111-1111-111111111111" in result.canvas

    def test_unsupported_section_type_refuses(self):
        cat = parse_discovery(DISCOVERY)
        spec = {"page": "X", "sections": [{"type": "seven-way", "parts": []}]}
        with pytest.raises(DslError, match="section type"):
            compile_page(spec, cat)

    def test_compiled_canvas_is_balanced_html(self):
        cat = parse_discovery(DISCOVERY_WITH_TEXT)
        result = compile_page(self.spec(), cat)
        assert result.canvas.count("<div") == result.canvas.count("</div>")


def test_text_parts_refuse_to_compile_without_a_persisted_measurement():
    """P2-3: compiling text against a pre-probe discovery document is refused."""
    cat = parse_discovery(DISCOVERY)  # fixture has no textControls key
    spec = {"page": "X", "sections": [{"type": "one", "parts": [{"text": "# Hi"}]}]}
    with pytest.raises(DslError, match="gen discover"):
        compile_page(spec, cat)


def test_malformed_text_controls_scalar_values_are_tolerated():
    """P3-4: a truthy scalar under requested/persisted is an empty sample set."""
    doc = dict(DISCOVERY, textControls={"requested": 1, "persisted": True})
    cat = parse_discovery(doc)
    assert cat.text_controls == ()


def test_persisted_matches_survives_the_colon_normalisation():
    """Measured 2026-09-06: SharePoint rewrites ':' to '&#58;' in text-control HTML."""
    doc = copy.deepcopy(DISCOVERY_WITH_TEXT)
    samples = doc["textControls"]["persisted"]
    samples[0]["canvas"] = samples[0]["canvas"].replace(":", "&#58;")
    cat = parse_discovery(doc)
    assert [s.persisted_matches() for s in cat.text_controls] == [True, None]


# A live-shaped sample (shauntestazure, 2026-09-06): the inner HTML carries
# colons in a href, a style and the running text, and the control-data
# attribute is already entity-escaped on BOTH sides. TEXT_HTML above has no
# colon, which is how the one-sided fold went unnoticed.
LIVE_HTML = (
    '<h2>Formwork text probe</h2><p>Paragraph with <b>bold</b>, '
    '<a href="https://example.com/">a link</a> and '
    '<span style="color:#a4262c;">a colour span</span>. Note: done.</p>'
)
LIVE_REQUESTED = TEXT_BLOCK.replace(TEXT_HTML, LIVE_HTML)
LIVE_PERSISTED = TEXT_BLOCK.replace(TEXT_HTML, LIVE_HTML.replace(":", "&#58;"))


def test_persisted_matches_folds_the_colon_on_both_sides():
    """The requested block's attribute already spells ':' as '&#58;'; the
    persisted block additionally spells it so in the inner HTML. Folding the
    persisted side alone compared every real sample unequal."""
    assert ":" in LIVE_REQUESTED and "&#58;" in LIVE_REQUESTED  # both spellings, one side
    assert ":" not in LIVE_PERSISTED.split('data-sp-rte=""')[1]  # inner HTML fully rewritten
    doc = copy.deepcopy(DISCOVERY_WITH_TEXT)
    doc["textControls"]["requested"][0] |= {"html": LIVE_HTML, "canvas": LIVE_REQUESTED}
    doc["textControls"]["persisted"][0]["canvas"] = LIVE_PERSISTED
    cat = parse_discovery(doc)
    sample = cat.text_controls[0]
    assert sample.persisted != sample.requested
    assert sample.persisted_matches() is True
    # The gate folds both sides; the emitted canvas is the stored spelling,
    # because apply compares byte for byte and does not fold (P1-1).
    spec = {"page": "X", "sections": [{"type": "one", "parts": [{"text": "<p>a: b</p>"}]}]}
    canvas = compile_page(spec, cat).canvas
    assert '<div data-sp-rte=""><p>a&#58; b</p></div>' in canvas
    assert "<p>a: b</p>" not in canvas


def test_compile_stores_colons_the_way_sharepoint_does():
    """A colon in a style attribute, in running text and in an absolute
    href is emitted as '&#58;': the one rewrite measured 2026-09-06
    (tests/fixtures/discovery.styling.json, styleSamples: 'color' requested
    style="color:#a4262c;" and persisted style="color&#58;#a4262c;"; the
    two colon-free samples came back byte-identical). Emitting ':' created
    the page and then failed apply's byte-exact read-back on every styled
    part and every absolute link (review P1-1)."""
    cat = parse_discovery(DISCOVERY_WITH_TEXT)
    html = (
        '<p><span style="color:#a4262c;">Note:</span> '
        '<a href="https://example.com/a">see</a> 10:30</p>'
    )
    spec = {"page": "X", "sections": [{"type": "one", "parts": [{"text": html}]}]}
    result = compile_page(spec, cat)
    inner = (
        '<p><span style="color&#58;#a4262c;">Note&#58;</span> '
        '<a href="https&#58;//example.com/a">see</a> 10&#58;30</p>'
    )
    assert stored_text_html(html) == inner
    assert f'<div data-sp-rte="">{inner}</div></div>' in result.canvas
    assert ":" not in result.canvas.split('data-sp-rte=""', 1)[1]
    # The part record keeps the author's HTML; only the canvas is folded.
    assert result.parts[0]["html"] == html
    # Still byte-exact through the parser, dirty path included.
    parsed = Canvas.parse(result.canvas)
    assert parsed.render() == result.canvas
    parsed.controls[0].mark_dirty()
    assert parsed.render() == result.canvas
    # Nothing else is touched: a colon-free part is emitted as written.
    plain = {"page": "X", "sections": [{"type": "one", "parts": [{"text": "<p>a b</p>"}]}]}
    assert '<div data-sp-rte=""><p>a b</p></div>' in compile_page(plain, cat).canvas


def test_compile_accepts_colon_normalised_measurement():
    cat = parse_discovery(DISCOVERY_WITH_TEXT)
    # Force the persisted sample through the same normalisation: compile must
    # still accept it.
    doc_raw = json.loads(json.dumps(DISCOVERY_WITH_TEXT))
    doc_raw["textControls"]["persisted"][0]["canvas"] = (
        doc_raw["textControls"]["persisted"][0]["canvas"].replace(":", "&#58;")
    )
    cat = parse_discovery(doc_raw)
    spec = {"page": "X", "sections": [{"type": "one", "parts": [{"text": "<p>x</p>"}]}]}
    result = compile_page(spec, cat)
    assert "data-sp-rte" in result.canvas


def test_compile_refuses_a_real_shape_change():
    doc = copy.deepcopy(DISCOVERY_WITH_TEXT)
    doc["textControls"]["persisted"][0]["canvas"] = (
        doc["textControls"]["persisted"][0]["canvas"].replace("data-sp-rte", "data-sp-other")
    )
    cat = parse_discovery(doc)
    spec = {"page": "X", "sections": [{"type": "one", "parts": [{"text": "<p>x</p>"}]}]}
    with pytest.raises(DslError, match="shape has changed"):
        compile_page(spec, cat)
