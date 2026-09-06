"""Tests for extraction bundle parsing and validation."""

import json

import pytest

from formwork.bundle import parse_bundle

MINIMAL = {
    "schema": "formwork.bundle/v1",
    "extractedAt": "2026-09-05T10:00:00.000Z",
    "source": {
        "webUrl": "https://contoso.sharepoint.com/sites/alpha",
        "webPath": "/sites/alpha",
        "pagePath": "SitePages/tooling-home.aspx",
    },
    "meta": {"webTitle": "alpha"},
    "page": {"Title": "Tooling home", "CanvasContent1": "<div></div>"},
    "sections": [],
    "webParts": [],
}


class TestParseBundle:
    def test_minimal_bundle_round_trips(self):
        bundle = parse_bundle(MINIMAL)
        assert bundle.schema == "formwork.bundle/v1"
        assert bundle.source.web_path == "/sites/alpha"
        assert bundle.page["Title"] == "Tooling home"

    def test_missing_schema_is_rejected(self):
        broken = {k: v for k, v in MINIMAL.items() if k != "schema"}
        with pytest.raises(ValueError, match="schema"):
            parse_bundle(broken)

    def test_wrong_schema_version_is_rejected(self):
        broken = dict(MINIMAL, schema="formwork.bundle/v9")
        with pytest.raises(ValueError, match="schema"):
            parse_bundle(broken)

    def test_missing_page_is_rejected(self):
        broken = {k: v for k, v in MINIMAL.items() if k != "page"}
        with pytest.raises(ValueError, match="page"):
            parse_bundle(broken)

    def test_missing_page_canvas_is_reported_not_fatal(self):
        flat = dict(MINIMAL, page={"Title": "No canvas here"})
        bundle = parse_bundle(flat)
        assert bundle.canvas_html is None

    def test_missing_source_paths_are_rejected(self):
        broken = dict(MINIMAL)
        broken["source"] = {"webUrl": "https://contoso.sharepoint.com/sites/alpha"}
        with pytest.raises(ValueError, match="webPath"):
            parse_bundle(broken)

    def test_parse_from_json_string(self):
        bundle = parse_bundle(json.dumps(MINIMAL))
        assert bundle.source.web_url == "https://contoso.sharepoint.com/sites/alpha"
