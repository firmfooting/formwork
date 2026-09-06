"""Tests for site-bound reference scanning and rewrite planning.

The refs live in the page's canvas, in the ``data-sp-webpartdata`` of each
web-part control, and nowhere else: the extract paste-in never wrote a
web-part inventory, so a rewriter reading one rewrote nothing, and one that
matched controls on the web part's ``id`` (the component type) could not
tell two Quick links apart (architecture review P1-2, 2026-09-06).

Every test starts from the real capture, ``tests/fixtures/collabhome.canvas.html``
(four web-part controls: News, Site activity, Quick links, Document library;
the bundle fixture's ``CanvasContent1`` is the same markup), and pins what
the rewrite promises: refs are addressed by ``instanceId``, never by the
component id; a control is re-serialised only when a value on it actually
changed; a changed control is re-serialised exactly once.
"""

import json
import pathlib
from collections import Counter
from typing import Any

import pytest

from formwork.bundle import Bundle, parse_bundle
from formwork.canvas import Canvas
from formwork.refs import (
    REPORT_ONLY_KINDS,
    REWRITABLE_KINDS,
    Plan,
    Ref,
    apply_plan,
    apply_plan_to_canvas,
    build_plan,
    scan,
    scan_canvas,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CANVAS = (FIXTURES / "collabhome.canvas.html").read_text(encoding="utf-8")

#: The capture's controls by instanceId (equal to the control data id in
#: every measured canvas), the twin the tests derive, and the Quick links
#: component id that the twin shares with the original.
NEWS = "00000000-0000-0000-0000-000000000001"
ACTIVITY = "00000000-0000-0000-0000-000000000002"
QUICK_LINKS = "00000000-0000-0000-0000-000000000003"
DOC_LIBRARY = "00000000-0000-0000-0000-000000000004"
QUICK_LINKS_TWIN = "00000000-0000-0000-0000-000000000005"
QUICK_LINKS_COMPONENT = "c70391ea-0b10-4ee9-b2b4-006d3fcad0cd"

TARGET = {
    "baseUrl": "https://shauntestazure.sharepoint.com/sites/Other",
    "siteId": "11111111-2222-3333-4444-555555555555",
    "webId": "aaaaaaaa-2222-3333-4444-555555555555",
}
TARGET_LISTS = {
    "Document library": {  # keyed by source web part title
        "id": "bbbbbbbb-2222-3333-4444-555555555555",
        "url": "/sites/Other/Shared Documents",
        "webRelativeUrl": "Shared Documents",
        "viewId": "cccccccc-2222-3333-4444-555555555555",
    },
}


def load_bundle() -> Bundle:
    data = json.loads((FIXTURES / "collabhome.bundle.json").read_text(encoding="utf-8"))
    return parse_bundle(data)


def refs_of(canvas_html: str = CANVAS) -> list[Ref]:
    return scan_canvas(Canvas.parse(canvas_html))


def blocks(canvas_html: str) -> dict[str, str]:
    """Each web-part control's rendered block, keyed by instanceId, in canvas order."""
    return {
        control.web_part_data["instanceId"]: control.render()
        for control in Canvas.parse(canvas_html).web_part_controls()
    }


def web_part(canvas_html: str, instance_id: str) -> dict[str, Any]:
    """The decoded web-part data of one control, re-read from rendered markup."""
    return next(
        control.web_part_data
        for control in Canvas.parse(canvas_html).web_part_controls()
        if control.web_part_data["instanceId"] == instance_id
    )


def texts_of(canvas_html: str, instance_id: str) -> dict[str, str]:
    return web_part(canvas_html, instance_id)["serverProcessedContent"]["searchablePlainTexts"]


def twinned_canvas() -> str:
    """The capture plus a second Quick links control right after the first:
    the same component id, its own instanceId, its own first item text.

    Derived here rather than added to the fixture file so the capture stays
    the bytes SharePoint returned (test_canvas pins its four controls).
    """
    block = blocks(CANVAS)[QUICK_LINKS]
    twin = block.replace(QUICK_LINKS, QUICK_LINKS_TWIN).replace(
        "Learn about a team site", "Second quick links"
    )
    assert twin.count(QUICK_LINKS_TWIN) == 2  # the control data id and the instanceId
    return CANVAS.replace(block, block + twin, 1)


class TestScan:
    def test_finds_every_site_bound_value_in_the_capture(self):
        refs = refs_of()
        assert Counter(r.kind for r in refs) == {
            "baseUrl": 2,  # News, Quick links
            "siteId": 2,  # News, Quick links
            "webId": 2,  # News, Quick links
            "list": 4,  # Document library: id, url, web-relative url, view
            "text": 4,  # Quick links title and two items, Document library listTitle
            "link": 2,  # Quick links items: detected, report-only
        }
        # The ten identity refs baseUrl/siteId/webId/lists resolve.
        identity = [r for r in refs if r.kind in REWRITABLE_KINDS and r.kind != "text"]
        assert len(identity) == 10

    def test_scan_reads_the_bundle_canvas_and_needs_no_web_part_list(self):
        bundle = load_bundle()
        assert "webParts" not in bundle.raw
        assert bundle.canvas_html.rstrip("\n") == CANVAS.rstrip("\n")
        assert scan(bundle) == refs_of()

    def test_scan_of_a_bundle_without_a_canvas_is_empty(self):
        bundle = parse_bundle(
            {
                "schema": "formwork.bundle/v1",
                "source": {
                    "webUrl": "https://contoso.sharepoint.com/sites/alpha",
                    "webPath": "/sites/alpha",
                    "pagePath": "SitePages/x.aspx",
                },
                "page": {"Title": "no canvas"},
            }
        )
        assert bundle.canvas_html is None
        assert scan(bundle) == []

    def test_refs_are_addressed_by_instance_id_not_component_id(self):
        refs = refs_of()
        assert {r.instance_id for r in refs} == {NEWS, QUICK_LINKS, DOC_LIBRARY}
        for ref in refs:
            assert ref.location == f"webParts[{ref.instance_id}].{ref.section}.{ref.key}"
            assert QUICK_LINKS_COMPONENT not in ref.location
        assert {r.instance_id: r.web_part_title for r in refs} == {
            NEWS: "News",
            QUICK_LINKS: "Quick links",
            DOC_LIBRARY: "Document library",
        }

    def test_scan_finds_base_url_in_links(self):
        base = [r for r in refs_of() if r.kind == "baseUrl"]
        assert [r.instance_id for r in base] == [NEWS, QUICK_LINKS]  # canvas order
        assert all((r.section, r.key) == ("links", "baseUrl") for r in base)
        assert all("shauntestazure.sharepoint.com" in r.value for r in base)
        assert all(r.location.startswith("webParts[") for r in base)

    def test_scan_finds_site_and_web_ids(self):
        ids = {(r.instance_id, r.kind): r for r in refs_of() if r.kind in ("siteId", "webId")}
        assert set(ids) == {
            (NEWS, "siteId"),
            (NEWS, "webId"),
            (QUICK_LINKS, "siteId"),
            (QUICK_LINKS, "webId"),
        }
        for ref in ids.values():
            assert ref.section == "properties" and ref.key == ref.kind
            assert len(ref.value) == 36, ref

    def test_scan_finds_list_bound_properties(self):
        lists = [r for r in refs_of() if r.kind == "list"]
        assert {r.instance_id for r in lists} == {DOC_LIBRARY}
        assert [r.key for r in lists] == [
            "selectedListId",
            "selectedListUrl",
            "webRelativeListUrl",
            "selectedViewId",
        ]
        assert all(r.section == "properties" for r in lists)

    def test_scan_keeps_searchable_plain_texts_with_their_dotted_keys(self):
        texts = {(r.instance_id, r.key): r.value for r in refs_of() if r.kind == "text"}
        assert texts == {
            (QUICK_LINKS, "title"): "Quick links",
            (QUICK_LINKS, "items[0].title"): "Learn about a team site",
            (QUICK_LINKS, "items[1].title"): "Learn how to add a page",
            (DOC_LIBRARY, "listTitle"): "Documents",
        }

    def test_two_controls_with_one_instance_id_are_refused(self):
        block = blocks(CANVAS)[QUICK_LINKS]
        doubled = CANVAS.replace(block, block + block, 1)
        assert len(Canvas.parse(doubled).web_part_controls()) == 5
        with pytest.raises(ValueError, match="two web-part controls with instanceId"):
            scan_canvas(Canvas.parse(doubled))


class TestPlan:
    def test_unresolved_values_are_reported_not_dropped(self):
        plan = build_plan(refs_of(), TARGET)  # no lists, no textOverrides
        assert Counter(r.kind for r, _ in plan.applied) == {"baseUrl": 2, "siteId": 2, "webId": 2}
        assert {r.kind for r in plan.unresolved} == {"list", "text", "link"}
        assert any(r.key == "selectedListId" for r in plan.unresolved)

    def test_lists_are_keyed_by_source_web_part_title(self):
        plan = build_plan(refs_of(), {"lists": TARGET_LISTS})
        assert {r.key: value for r, value in plan.applied} == {
            "selectedListId": TARGET_LISTS["Document library"]["id"],
            "selectedListUrl": "/sites/Other/Shared Documents",
            "webRelativeListUrl": "Shared Documents",
            "selectedViewId": TARGET_LISTS["Document library"]["viewId"],
        }
        assert all(r.instance_id == DOC_LIBRARY for r, _ in plan.applied)

    def test_an_empty_string_override_resolves(self):
        # "" is a value, not an absence: a truthiness test dropped it.
        plan = build_plan(refs_of(), {"textOverrides": {"Documents": ""}})
        assert [(r.key, value) for r, value in plan.applied] == [("listTitle", "")]

    def test_link_and_image_are_report_only(self):
        assert {"link", "image"} == REPORT_ONLY_KINDS
        assert not REPORT_ONLY_KINDS & REWRITABLE_KINDS
        refs = refs_of()
        everything = {
            **TARGET,
            "lists": TARGET_LISTS,
            "textOverrides": {r.value: "x" for r in refs if r.kind == "text"},
        }
        plan = build_plan(refs, everything)
        assert [(r.instance_id, r.kind, r.key) for r in plan.unresolved] == [
            (QUICK_LINKS, "link", "items[0].sourceItem.url"),
            (QUICK_LINKS, "link", "items[1].sourceItem.url"),
        ]
        assert all(r.value.startswith("https://go.microsoft.com/") for r in plan.unresolved)

    def test_a_non_string_mapping_value_is_refused(self):
        with pytest.raises(ValueError, match="must be a string"):
            build_plan(refs_of(), {"siteId": 42})
        with pytest.raises(ValueError, match="must be a string"):
            build_plan(refs_of(), {"lists": {"Document library": {"id": ["not", "a", "guid"]}}})


class TestApply:
    def test_untouched_controls_stay_byte_identical(self):
        bundle = load_bundle()
        plan = build_plan(scan(bundle), {"lists": TARGET_LISTS})
        result = apply_plan(bundle, plan)
        assert result.rewritten == (DOC_LIBRARY,)
        before, after = blocks(bundle.canvas_html), blocks(result.canvas_html)
        assert list(after) == list(before) == [NEWS, ACTIVITY, QUICK_LINKS, DOC_LIBRARY]
        for instance in (NEWS, ACTIVITY, QUICK_LINKS):
            assert after[instance] == before[instance], instance
        assert after[DOC_LIBRARY] != before[DOC_LIBRARY]
        props = web_part(result.canvas_html, DOC_LIBRARY)["properties"]
        assert props["selectedListId"] == TARGET_LISTS["Document library"]["id"]
        assert props["selectedListUrl"] == "/sites/Other/Shared Documents"
        assert props["webRelativeListUrl"] == "Shared Documents"
        assert props["selectedViewId"] == TARGET_LISTS["Document library"]["viewId"]
        # The re-serialised canvas parses and round-trips.
        assert Canvas.parse(result.canvas_html).render() == result.canvas_html

    def test_a_mapping_that_restates_the_extracted_values_changes_nothing(self):
        refs = refs_of()
        same = {r.kind: r.value for r in refs if r.kind in ("baseUrl", "siteId", "webId")}
        plan = build_plan(refs, same)
        assert len(plan.applied) == 6  # resolved, and nothing to write
        canvas = Canvas.parse(CANVAS)
        assert apply_plan_to_canvas(canvas, plan) == ()
        assert not any(control.dirty for control in canvas.controls)
        assert canvas.render() == CANVAS

    def test_a_changed_control_is_reserialised_exactly_once(self):
        refs = refs_of()
        plan = build_plan(refs, TARGET)
        # Three refs on News, three on Quick links: one re-serialisation each.
        assert Counter(r.instance_id for r, _ in plan.applied) == {NEWS: 3, QUICK_LINKS: 3}
        canvas = Canvas.parse(CANVAS)
        assert apply_plan_to_canvas(canvas, plan) == (NEWS, QUICK_LINKS)
        rendered = canvas.render()
        for instance in (NEWS, QUICK_LINKS):
            data = web_part(rendered, instance)
            assert data["serverProcessedContent"]["links"]["baseUrl"] == TARGET["baseUrl"]
            assert data["properties"]["siteId"] == TARGET["siteId"]
            assert data["properties"]["webId"] == TARGET["webId"]
            assert blocks(rendered)[instance].count(TARGET["siteId"]) == 1
        # Applying the same plan to the result changes nothing more.
        again = Canvas.parse(rendered)
        assert apply_plan_to_canvas(again, plan) == ()
        assert again.render() == rendered

    def test_two_controls_sharing_a_component_get_their_own_values(self):
        canvas_html = twinned_canvas()
        canvas = Canvas.parse(canvas_html)
        twins = [
            c.web_part_data["instanceId"]
            for c in canvas.web_part_controls()
            if c.web_part_data["id"] == QUICK_LINKS_COMPONENT
        ]
        assert twins == [QUICK_LINKS, QUICK_LINKS_TWIN]
        refs = scan_canvas(canvas)
        first_items = {
            r.instance_id: r.value for r in refs if r.kind == "text" and r.key == "items[0].title"
        }
        assert first_items == {
            QUICK_LINKS: "Learn about a team site",
            QUICK_LINKS_TWIN: "Second quick links",
        }
        # Override only the twin's text: the original is not touched at all.
        plan = build_plan(refs, {"textOverrides": {"Second quick links": "Twin, renamed"}})
        assert [(r.instance_id, r.key) for r, _ in plan.applied] == [
            (QUICK_LINKS_TWIN, "items[0].title")
        ]
        assert apply_plan_to_canvas(canvas, plan) == (QUICK_LINKS_TWIN,)
        rendered = canvas.render()
        before, after = blocks(canvas_html), blocks(rendered)
        assert after[QUICK_LINKS] == before[QUICK_LINKS]
        assert after[QUICK_LINKS_TWIN] != before[QUICK_LINKS_TWIN]
        assert texts_of(rendered, QUICK_LINKS)["items[0].title"] == "Learn about a team site"
        assert texts_of(rendered, QUICK_LINKS_TWIN)["items[0].title"] == "Twin, renamed"
        # A value both carry (baseUrl) lands in each of them, each once.
        fresh = Canvas.parse(canvas_html)
        both = build_plan(scan_canvas(fresh), {"baseUrl": TARGET["baseUrl"]})
        assert [r.instance_id for r, _ in both.applied] == [NEWS, QUICK_LINKS, QUICK_LINKS_TWIN]
        assert apply_plan_to_canvas(fresh, both) == (NEWS, QUICK_LINKS, QUICK_LINKS_TWIN)
        for instance in (QUICK_LINKS, QUICK_LINKS_TWIN):
            links = web_part(fresh.render(), instance)["serverProcessedContent"]["links"]
            assert links["baseUrl"] == TARGET["baseUrl"]

    def test_dotted_keys_reach_their_value(self):
        # "items[0].title" carries a dot; a location split on "." wrote nowhere.
        plan = build_plan(
            refs_of(), {"textOverrides": {"Learn about a team site": "Team site basics"}}
        )
        assert [(r.instance_id, r.section, r.key) for r, _ in plan.applied] == [
            (QUICK_LINKS, "searchablePlainTexts", "items[0].title")
        ]
        canvas = Canvas.parse(CANVAS)
        assert apply_plan_to_canvas(canvas, plan) == (QUICK_LINKS,)
        texts = texts_of(canvas.render(), QUICK_LINKS)
        assert texts["items[0].title"] == "Team site basics"
        assert texts["items[1].title"] == "Learn how to add a page"

    def test_a_plan_naming_a_control_the_canvas_lacks_is_refused(self):
        ghost = Ref(
            kind="siteId",
            instance_id="ffffffff-0000-0000-0000-000000000000",
            section="properties",
            key="siteId",
            value="x",
            web_part_title="Ghost",
        )
        plan = Plan(applied=[(ghost, TARGET["siteId"])], unresolved=[])
        with pytest.raises(ValueError, match="does not carry"):
            apply_plan_to_canvas(Canvas.parse(CANVAS), plan)

    def test_apply_plan_leaves_unresolved_values_unchanged(self):
        bundle = load_bundle()
        plan = build_plan(scan(bundle), TARGET)
        result = apply_plan(bundle, plan)
        assert DOC_LIBRARY not in result.rewritten
        props = web_part(result.canvas_html, DOC_LIBRARY)["properties"]
        # No list mapping: the original sandbox values survive untouched.
        assert props["selectedListUrl"] == "/sites/TestSampleTeam/Shared Documents"
        assert props["webRelativeListUrl"] == "Shared Documents"
        assert blocks(result.canvas_html)[DOC_LIBRARY] == blocks(bundle.canvas_html)[DOC_LIBRARY]


class TestDirtyRenderUnicode:
    r"""P1 (re-review): the dirty render passes re-escaped JSON to re.sub.

    A string replacement template makes re parse backslash escapes:
    json.dumps emits \uXXXX for non-ASCII (re.error: bad escape) and \n/\t
    silently corrupt the attribute bytes. Found because the P1-2 fix makes
    `process` dirty live controls for the first time.
    """

    def test_curly_apostrophe_in_rewritten_title_survives(self):
        bundle = parse_bundle((FIXTURES / "collabhome.bundle.json").read_text(encoding="utf-8"))
        refs = scan(bundle)
        mapping = {
            "baseUrl": "https://other.example/sites/Other",
            "siteId": "1" * 8 + "-2222-3333-4444-555555555555",
            "webId": "a" * 8 + "-2222-3333-4444-555555555555",
            "lists": {},
            "textOverrides": {"Quick links": "Team\u2019s links"},
        }
        plan = build_plan(refs, mapping)
        final = apply_plan(bundle, plan)
        canvas = Canvas.parse(final.canvas_html)
        quick = next(c for c in canvas.controls if c.web_part_title == "Quick links")
        title = quick.web_part_data["serverProcessedContent"]["searchablePlainTexts"]["title"]
        assert title == "Team\u2019s links"
        # The attribute JSON carries the real character, not an escape.
        assert "Team\u2019s links" in final.canvas_html
        assert "\\u2019" not in final.canvas_html
        # And the rendered control still parses.
        assert canvas.render() == final.canvas_html

    def test_newline_and_backslash_in_rewritten_value_survive(self):
        bundle = parse_bundle((FIXTURES / "collabhome.bundle.json").read_text(encoding="utf-8"))
        refs = scan(bundle)
        mapping = {
            "baseUrl": "https://other.example/sites/Other",
            "siteId": "1" * 8 + "-2222-3333-4444-555555555555",
            "webId": "a" * 8 + "-2222-3333-4444-555555555555",
            "lists": {},
            "textOverrides": {"Quick links": "line one\nline two\\end"},
        }
        plan = build_plan(refs, mapping)
        final = apply_plan(bundle, plan)
        canvas = Canvas.parse(final.canvas_html)
        quick = next(c for c in canvas.controls if c.web_part_title == "Quick links")
        title = quick.web_part_data["serverProcessedContent"]["searchablePlainTexts"]["title"]
        assert title == "line one\nline two\\end"
        # Round-trips: the JSON parses back to the same value.
        assert canvas.render() == final.canvas_html
