"""Tests for site-bound reference scanning and rewrite planning."""

import json
import pathlib

from formwork.bundle import parse_bundle
from formwork.canvas import Canvas
from formwork.refs import apply_plan, build_plan, scan

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_bundle() -> "object":
    data = json.loads((FIXTURES / "collabhome.bundle.json").read_text(encoding="utf-8"))
    return parse_bundle(data)


def test_scan_finds_base_url_in_links():
    refs = scan(load_bundle())
    base = [r for r in refs if r.kind == "baseUrl"]
    assert base, "expected at least one baseUrl ref"
    assert all(
        "shauntestazure.sharepoint.com" in r.value for r in base
    )
    assert all(r.location.startswith("webParts[") for r in base)


def test_scan_finds_site_and_web_ids():
    refs = scan(load_bundle())
    ids = {r.location: r.value for r in refs if r.kind in ("siteId", "webId")}
    assert any(k.endswith(".properties.siteId") for k in ids)
    assert all(len(v) == 36 for v in ids.values()), ids


def test_scan_finds_list_bound_properties():
    refs = scan(load_bundle())
    list_refs = [r for r in refs if r.kind == "list"]
    keys = {r.location for r in list_refs}
    assert any(k.endswith("selectedListId") for k in keys)
    assert any(k.endswith("selectedListUrl") for k in keys)
    assert any(k.endswith("webRelativeListUrl") for k in keys)
    assert any(k.endswith("selectedViewId") for k in keys)


def test_scan_flags_text_for_review_not_rewrite():
    refs = scan(load_bundle())
    texts = [r for r in refs if r.kind == "text"]
    assert any(r.location.endswith("listTitle") for r in texts)


def test_plan_reports_unresolved_without_dropping():
    bundle = load_bundle()
    refs = scan(bundle)
    mapping = {
        "baseUrl": "https://shauntestazure.sharepoint.com/sites/Other",
        "siteId": "1" * 8 + "-2222-3333-4444-555555555555",
        "webId": "a" * 8 + "-2222-3333-4444-555555555555",
        # no "list" mapping provided
    }
    plan = build_plan(refs, mapping)
    assert plan.unresolved, "list refs should be unresolved without a list mapping"
    assert any("selectedListId" in r.location for r in plan.unresolved)
    assert plan.applied, "baseUrl/siteId/webId should resolve"


def test_apply_plan_rewrites_web_parts_and_canvas():
    bundle = load_bundle()
    refs = scan(bundle)
    target_lists = {
        "Document library": {  # keyed by source web part title
            "id": "b" * 8 + "-2222-3333-4444-555555555555",
            "url": "/sites/Other/Shared Documents",
            "webRelativeUrl": "Shared Documents",
            "viewId": "c" * 8 + "-2222-3333-4444-555555555555",
        },
    }
    mapping = {
        "baseUrl": "https://shauntestazure.sharepoint.com/sites/Other",
        "siteId": "1" * 8 + "-2222-3333-4444-555555555555",
        "webId": "a" * 8 + "-2222-3333-4444-555555555555",
        "lists": target_lists,
        "textOverrides": {"Documents": "Reports library"},
    }
    plan = build_plan(refs, mapping)
    final = apply_plan(bundle, plan)

    doclib = next(w for w in final.web_parts if w["title"] == "Document library")
    props = doclib["properties"]
    assert props["selectedListId"] == target_lists["Document library"]["id"]
    assert props["webRelativeListUrl"] == "Shared Documents"
    spc = doclib["serverProcessedContent"]
    assert spc["searchablePlainTexts"]["listTitle"] == "Reports library"

    # The regenerated canvas carries the mutated values and parses cleanly.
    canvas = Canvas.parse(final.canvas_html)
    assert canvas.render() == final.canvas_html  # regenerated canvas round-trips
    rendered = final.canvas_html
    assert target_lists["Document library"]["id"] in rendered
    assert "Reports library" in rendered


def test_apply_plan_leaves_unresolved_values_unchanged():
    bundle = load_bundle()
    refs = scan(bundle)
    mapping = {
        "baseUrl": "https://shauntestazure.sharepoint.com/sites/Other",
        "siteId": "1" * 8 + "-2222-3333-4444-555555555555",
        "webId": "a" * 8 + "-2222-3333-4444-555555555555",
    }
    plan = build_plan(refs, mapping)
    final = apply_plan(bundle, plan)
    doclib = next(w for w in final.web_parts if w["title"] == "Document library")
    # No list mapping: the original sandbox values survive untouched.
    assert doclib["properties"]["webRelativeListUrl"].startswith("Shared")
