"""Tests for the CanvasContent1 parser and renderer.

The round-trip contract: rendering a parsed, untouched canvas reproduces the
original string byte-for-byte. Only controls explicitly marked dirty are
re-serialised, and their re-escaping must match the escaping SharePoint
itself emits (& -> &amp; first, then < > ", then { } : as numeric entities).
"""

import json
import pathlib

from formwork.canvas import Canvas, escape_attribute

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "collabhome.canvas.html"

EXPECTED_TITLES = ["News", "Site activity", "Quick links", "Document library"]


def load_fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_finds_web_part_controls_in_order():
    canvas = Canvas.parse(load_fixture())
    assert len(canvas.controls) == 4
    assert [c.web_part_title for c in canvas.controls] == EXPECTED_TITLES
    positions = [c.control_data["position"] for c in canvas.controls]
    assert positions == sorted(
        positions,
        key=lambda p: (p["zoneIndex"], p["sectionIndex"], p["controlIndex"]),
    )


def test_roundtrip_is_byte_exact():
    original = load_fixture()
    canvas = Canvas.parse(original)
    assert canvas.render() == original


def test_dirty_control_reescapes_sharepoint_style():
    canvas = Canvas.parse(load_fixture())
    target = canvas.controls[3]  # Document library
    assert target.web_part_title == "Document library"
    target.web_part_data["serverProcessedContent"]["searchablePlainTexts"][
        "listTitle"
    ] = "Reports"
    target.mark_dirty()

    rendered = canvas.render()

    # New value present, SharePoint-escaped.
    assert "&quot;listTitle&quot;&#58;&quot;Reports&quot;" in rendered
    # The other three controls' raw markup is untouched.
    assert "&quot;Site activity&quot;" in rendered
    assert rendered.count("data-sp-canvascontrol") == 4

    # And the mutated canvas parses back to the mutated value.
    reparsed = Canvas.parse(rendered)
    assert [c.web_part_title for c in reparsed.controls] == [
        "News",
        "Site activity",
        "Quick links",
        "Document library",  # title itself untouched
    ]
    assert (
        reparsed.controls[3]
        .web_part_data["serverProcessedContent"]["searchablePlainTexts"]["listTitle"]
        == "Reports"
    )


def test_escape_attribute_matches_sharepoint_style():
    escaped = escape_attribute(json.dumps({"controlType": 3, "id": "a:b"}, separators=(",", ":")))
    assert escaped.startswith("&#123;&quot;controlType&quot;&#58;3")
    assert "}" not in escaped and '"' not in escaped
    assert escaped.endswith("&#125;")
    # Ampersand first, so the numeric entities are not double-escaped.
    assert "&amp;#" not in escaped


def test_parse_tolerates_control_without_web_part_data():
    # A text control or section div carries controldata but no webpartdata.
    snippet = (
        '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0" '
        'data-sp-controldata="&#123;&quot;controlType&quot;&#58;4,&quot;id&quot;&#58;&quot;aaa&quot;&#125;">'
        "</div>"
    )
    canvas = Canvas.parse(snippet)
    assert len(canvas.controls) == 1
    assert canvas.controls[0].web_part_data is None
    assert canvas.controls[0].web_part_title is None
    assert canvas.render() == snippet
