"""Tests for the CanvasContent1 parser and renderer.

The round-trip contract: rendering a parsed, untouched canvas reproduces the
original string byte-for-byte. Only controls explicitly marked dirty are
re-serialised, and their re-escaping must match the escaping SharePoint
itself emits (& -> &amp; first, then < > ", then { } : as numeric entities).
"""

import json
import pathlib

import pytest

from formwork.canvas import (
    COLON_ENTITY,
    Canvas,
    Control,
    decode_attribute,
    encode_attribute,
    escape_attribute,
)

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


def test_dirty_control_syncs_the_htmlproperties_mirror():
    """The control's own copy of a rewritten value moves with it.

    Control 3 carries ``listTitle`` twice: in the webpartdata attribute and in
    the ``data-sp-htmlproperties`` child, which the fixture stores verbatim
    from it. Rewriting only the attribute left the copy on the page (raised as
    P2 by the 2026-09-06 P1-fix re-review, unactioned).
    """
    canvas = Canvas.parse(load_fixture())
    target = canvas.controls[3]  # Document library
    target.web_part_data["serverProcessedContent"]["searchablePlainTexts"][
        "listTitle"
    ] = "Reports library"
    target.mark_dirty()

    rendered = canvas.render()

    mirror = 'data-sp-prop-name="listTitle" data-sp-searchableplaintext="true"'
    assert f"{mirror}>Reports library</div>" in rendered
    assert f"{mirror}>Documents</div>" not in rendered


def test_mirror_sync_leaves_derived_mirrors_alone():
    # Quick links: the part title is mirrored verbatim and follows the new
    # value; the baseUrl mirror is an href SharePoint re-spells server-relative
    # where the JSON value is absolute, so it is not the value to copy.
    canvas = Canvas.parse(load_fixture())
    target = canvas.controls[2]  # Quick links
    processed = target.web_part_data["serverProcessedContent"]
    processed["searchablePlainTexts"]["title"] = "Team links"
    processed["links"]["baseUrl"] = "https://tgt.example/sites/New"
    target.mark_dirty()

    rendered = canvas.render()

    mirror = 'data-sp-prop-name="title" data-sp-searchableplaintext="true"'
    assert f"{mirror}>Team links</div>" in rendered
    assert 'data-sp-prop-name="baseUrl" href="/sites/TestSampleTeam"' in rendered


def test_dirtied_but_unchanged_control_still_renders_byte_exact():
    # The module's headline contract: only real changes reach the bytes.
    canvas = Canvas.parse(load_fixture())
    for control in canvas.controls:
        control.mark_dirty()
    assert canvas.render() == load_fixture()


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


# M9: canvas.py is the one serialiser. The compiler builds its controls
# through Control.web_part / Control.text and the catalogue decodes stored
# blocks through decode_attribute; these pin the pair and the shapes.

CONTROL_DATA = {
    "controlType": 3,
    "id": "00000000-0000-0000-0000-000000000001",
    "position": {
        "zoneIndex": 1000.0,
        "sectionIndex": 1.0,
        "controlIndex": 1.0,
        "zoneId": None,
        "sectionFactor": 12,
        "layoutIndex": 1,
    },
    "webPartId": "8c88f208-6c77-4bdb-86a0-0c47b4316588",
    "emphasis": {"zoneEmphasis": 2},
}

WEB_PART_DATA = {
    "id": "8c88f208-6c77-4bdb-86a0-0c47b4316588",
    "instanceId": "00000000-0000-0000-0000-000000000001",
    "title": "Bob’s <news> & \"links\"",
    "description": "",
    "serverProcessedContent": {"searchablePlainTexts": {"listTitle": "Docs: {a}"}},
    "dataVersion": "1.0",
    "properties": {"layoutId": "FeaturedNews", "count": 4, "on": True, "url": "https://x/y"},
}


def test_encode_and_decode_attribute_are_inverses():
    encoded = encode_attribute(WEB_PART_DATA)
    assert decode_attribute(encoded) == WEB_PART_DATA
    # Compact JSON: no space after the separators json.dumps would pad.
    assert encoded.startswith("&#123;&quot;id&quot;&#58;&quot;")
    assert "&quot;,&quot;" in encoded
    assert "&quot;, &quot;" not in encoded
    # SharePoint's entities, nothing left raw, and the ampersand escaped
    # first so nothing is double-escaped.
    assert not any(ch in encoded for ch in '<>"{}:')
    assert "Bob’s &lt;news&gt; &amp; \\&quot;links\\&quot;" in encoded
    assert "&amp;#" not in encoded
    assert "&amp;quot;" not in encoded
    # Non-ASCII kept literal, not \\u-escaped.
    assert "\\u2019" not in encoded
    assert escape_attribute(":") == COLON_ENTITY == "&#58;"


def test_decode_attribute_refuses_non_json():
    with pytest.raises(ValueError, match="Expecting"):
        decode_attribute("&#123;not json")


def test_web_part_control_renders_as_a_parsed_and_dirtied_one_would():
    control = Control.web_part(CONTROL_DATA, WEB_PART_DATA)
    rendered = control.render()
    assert control.dirty is False
    # Shape: the control div, the webpartdata child with its empty
    # htmlproperties, then the control's own close.
    assert rendered.startswith(
        '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0" data-sp-controldata="'
    )
    assert '"><div data-sp-webpartdata="' in rendered
    assert rendered.endswith('" data-sp-htmlproperties=""></div></div>')
    assert rendered.count("<div") == 2
    # The raw attributes are the encoded dicts, so parse reads them back.
    assert control.controldata_raw == encode_attribute(CONTROL_DATA)
    assert control.webpartdata_raw == encode_attribute(WEB_PART_DATA)
    (reparsed,) = Canvas.parse(rendered).controls
    assert reparsed.control_data == CONTROL_DATA
    assert reparsed.web_part_data == WEB_PART_DATA
    # And the dirty path, re-serialising from the dicts, gives the same bytes.
    reparsed.mark_dirty()
    assert reparsed.render() == rendered


def test_text_control_wraps_the_inner_html_as_given():
    control_data = {
        "controlType": 4,
        "id": "00000000-0000-0000-0000-000000000002",
        "position": CONTROL_DATA["position"],
        "emphasis": {},
        "editorType": "CKEditor",
    }
    inner = "<p>Hi&#58; <a href=\"https&#58;//x\">y</a></p>"
    control = Control.text(control_data, inner)
    rendered = control.render()
    assert control.dirty is False
    assert control.web_part_data is None
    assert control.webpartdata_raw is None
    assert rendered == (
        '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0" '
        f'data-sp-controldata="{encode_attribute(control_data)}">'
        f'<div data-sp-rte="">{inner}</div></div>'
    )
    (reparsed,) = Canvas.parse(rendered).controls
    assert reparsed.control_data == control_data
    assert reparsed.body == f'<div data-sp-rte="">{inner}</div></div>'
    reparsed.mark_dirty()
    assert reparsed.render() == rendered
