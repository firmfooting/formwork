"""Pins from the measured styling evidence, tests/fixtures/discovery.styling.json.

That document is a live ``formwork gen discover`` run carrying the M3 styling
probe (shauntestazure sandbox, "Test Sample Team" site, 2026-09-06). It is
the evidence behind three claims this release makes:

* styled text: seven HTML samples written into text controls came back with
  only the ``:`` to ``&#58;`` rewrite (README, "Styled text");
* emphasis: web-part controls sent with ``emphasis.zoneEmphasis`` 2 and 3
  persisted byte-for-byte through the item MERGE (dsl.py, the emphasis key);
* refusals: section-level emphasis needs the page model's SavePage; theme,
  section background and section spacing are unmeasured (dsl.py,
  UNENCODABLE_PAGE_KEYS / UNENCODABLE_SECTION_KEYS).

The tests read the fixture, the DSL and the README together, so neither the
code nor the documentation can drift from the bytes without a test going red.
"""

import functools
import json
import pathlib
import re
from typing import Any

from formwork.canvas import Canvas
from formwork.catalogue import parse_discovery
from formwork.dsl import (
    UNENCODABLE_PAGE_KEYS,
    UNENCODABLE_SECTION_KEYS,
    ZONE_EMPHASIS_VALUES,
    compile_page,
    stored_text_html,
)
from test_dsl import DISCOVERY

ROOT = pathlib.Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "discovery.styling.json"
README = ROOT / "README.md"

#: The seven styled-text samples, in the order the probe wrote them.
STYLE_LABELS = [
    "color",
    "font-size",
    "background",
    "styled-link",
    "mark",
    "block-align",
    "rte-classes",
]


@functools.cache
def styling_document() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def styling() -> dict[str, Any]:
    return styling_document()["styling"]


def paired(samples: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(label, requested, persisted) per requested sample, joined by control id."""
    persisted = {row["id"]: row for row in samples["persisted"]}
    rows = []
    for requested in samples["requested"]:
        stored = persisted.get(requested["id"])
        assert stored is not None, f"{requested['label']} was requested but never read back"
        rows.append((requested["label"], requested, stored))
    return rows


def fold(canvas: str) -> str:
    """The one rewrite SharePoint applies to text-control HTML."""
    return canvas.replace("&#58;", ":")


class TestTheDocument:
    def test_is_the_live_run_the_release_cites(self):
        doc = styling_document()
        assert doc["schema"] == "formwork.discovery/v1"
        assert doc["discoveredAt"].startswith("2026-09-06T")
        assert doc["web"]["url"] == "https://shauntestazure.sharepoint.com/sites/TestSampleTeam"
        assert styling()["sectionEmphasisMechanism"]["measuredAt"] == "2026-09-06"


class TestStyledText:
    def test_seven_samples_persisted_with_only_the_colon_rewrite(self):
        rows = paired(styling()["styleSamples"])
        assert [label for label, _, _ in rows] == STYLE_LABELS
        for label, requested, persisted in rows:
            assert fold(persisted["canvas"]) == fold(requested["canvas"]), label
        # The two samples whose HTML carries no ':' came back byte-identical;
        # the other five differ only by the rewrite.
        identical = [label for label, r, p in rows if r["canvas"] == p["canvas"]]
        assert identical == ["mark", "rte-classes"]
        for label, requested, _ in rows:
            assert (":" not in requested["html"]) == (label in identical), label

    def test_compile_emits_the_bytes_sharepoint_stored(self):
        """The compiler writes text HTML in the stored spelling, ':' as
        '&#58;', so apply's byte-exact read-back holds for styled text and
        absolute links instead of failing after the page is created (review
        P1-1, 2026-09-06). Pinned against all seven samples: the fold
        reproduces each persisted inner HTML exactly, and compiling each
        sample's HTML against this very document emits those bytes."""
        cat = parse_discovery(styling_document())
        for label, requested, persisted in paired(styling()["styleSamples"]):
            stored_inner = persisted["canvas"].split('<div data-sp-rte="">', 1)[1]
            stored_inner = stored_inner.split("</div>", 1)[0]
            assert stored_inner == stored_text_html(requested["html"]), label
            spec = {
                "page": "T",
                "sections": [{"type": "one", "parts": [{"text": requested["html"]}]}],
            }
            result = compile_page(spec, cat)
            assert f'<div data-sp-rte="">{stored_inner}</div>' in result.canvas, label
            # The part record keeps the author's HTML; only the canvas is folded.
            assert result.parts[0]["html"] == requested["html"], label

    def test_the_readme_table_lists_exactly_the_measured_samples(self):
        readme = README.read_text(encoding="utf-8")
        section = re.search(r"^### Styled text\n(.*?)(?=^#)", readme, re.S | re.M)
        assert section, "README has no '### Styled text' section"
        body = section.group(1)
        rows = re.findall(r"^\| `([\w-]+)` \| .*? \| (.*?) \|$", body, re.M)
        measured = paired(styling()["styleSamples"])
        assert [label for label, _ in rows] == [label for label, _, _ in measured]
        for (label, stored), (_, requested, persisted) in zip(rows, measured, strict=True):
            assert stored.startswith("yes"), label
            identical = requested["canvas"] == persisted["canvas"]
            assert ("byte-identical" in stored) == identical, label
        assert "tests/fixtures/discovery.styling.json" in body


class TestEmphasis:
    def test_web_part_controls_with_emphasis_persisted_byte_for_byte(self):
        rows = {label: (r, p) for label, r, p in paired(styling()["sectionSamples"])}
        assert set(rows) == {
            "emphasis-soft",
            "emphasis-unknown-key",
            "collapsible",
            "full-width",
            "vertical",
        }
        for label, (requested, persisted) in rows.items():
            assert persisted["canvas"] == requested["canvas"], label
        assert rows["emphasis-soft"][1]["controlData"]["emphasis"] == {"zoneEmphasis": 2}
        assert rows["emphasis-unknown-key"][1]["controlData"]["emphasis"] == {
            "zoneEmphasis": 3,
            "formworkProbe": "unknown key",
        }

    def test_the_measured_values_sit_inside_the_accepted_set(self):
        measured = {
            requested["controlData"]["emphasis"]["zoneEmphasis"]
            for _, requested, _ in paired(styling()["sectionSamples"])
            if requested["controlData"]["emphasis"]
        }
        assert measured == {2, 3}
        # 1 and 4 are accepted on the strength of the editor's swatches only.
        assert measured < set(ZONE_EMPHASIS_VALUES)

    def test_compiled_control_data_has_the_measured_shape(self):
        by_label = {label: persisted for label, _, persisted in paired(styling()["sectionSamples"])}
        persisted = by_label["emphasis-soft"]["controlData"]
        spec = {
            "page": "T",
            "sections": [{"type": "one", "parts": [{"component": "NewsWebPart", "emphasis": 2}]}],
        }
        control = Canvas.parse(compile_page(spec, parse_discovery(DISCOVERY)).canvas).controls[0]
        assert list(control.control_data) == list(persisted)
        assert list(control.control_data["position"]) == list(persisted["position"])
        assert control.control_data["emphasis"] == persisted["emphasis"]
        assert control.control_data["controlType"] == persisted["controlType"] == 3

    def test_every_text_control_read_back_carried_an_empty_emphasis(self):
        # Why emphasis on a text part is refused: nothing measured says
        # anything else about it.
        probes = styling_document()["textControls"]["persisted"]
        rows = probes + styling()["styleSamples"]["persisted"]
        assert len(rows) == 9
        assert all(row["controlData"]["controlType"] == 4 for row in rows)
        assert all(row["controlData"]["emphasis"] == {} for row in rows)


class TestRefusals:
    def test_section_emphasis_refusal_names_the_measured_mechanism(self):
        mechanism = styling()["sectionEmphasisMechanism"]
        assert "SavePage" in mechanism["finding"]
        assert mechanism["evidence"]["saveBodyShape"]["endpoint"] == (
            "/_api/sitepages/pages(<id>)/SavePage"
        )
        assert mechanism["evidence"]["savePageJsonArray"]["newlyMergedControlEmphasis"] == 3
        reason = UNENCODABLE_SECTION_KEYS["emphasis"]
        assert "SavePage" in reason
        assert "zoneId" in reason

    def test_page_model_save_with_an_html_canvas_was_refused(self):
        # Why apply keeps the item MERGE: SavePageAsDraft wanted a JSON array.
        result = styling()["pageModelSave"]
        assert (result["attempted"], result["ok"], result["status"]) == (True, False, 500)
        assert result["reason"].startswith(
            "Unexpected character encountered while parsing value: <"
        )

    def test_every_unmeasured_topic_is_refused_or_documented(self):
        topics = [row["topic"] for row in styling()["unmeasured"]]
        assert topics == ["theme", "section-background", "section-spacing", "rendering"]
        refused = set(UNENCODABLE_PAGE_KEYS) | {
            f"section-{key}" for key in UNENCODABLE_SECTION_KEYS if key != "emphasis"
        }
        assert refused == {"theme", "section-background", "section-spacing"}
        for key, reason in {**UNENCODABLE_PAGE_KEYS, **UNENCODABLE_SECTION_KEYS}.items():
            assert "2026-09-06" in reason, key
        readme = README.read_text(encoding="utf-8")
        for topic in topics:
            assert f"`{topic}`" in readme, topic
