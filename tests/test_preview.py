"""Tests for the standalone page preview and the `formwork preview` command."""

import json
import re

import pytest

from formwork.catalogue import parse_discovery
from formwork.cli import main
from formwork.dsl import DslError
from formwork.preview import build_preview, render_preview
from test_dsl import DISCOVERY

pytest.importorskip("yaml")

SPEC = {
    "page": "Team <home> & more",
    "sections": [
        {
            "type": "two-thirds",
            "parts": [
                {"component": "NewsWebPart"},
                {"text": "# Welcome\n\nA **bold** [link](/x).", "column": 2},
            ],
        },
        {"type": "one", "parts": [{"text": "<p>Raw <em>html</em></p>"}]},
        {"type": "three", "parts": [{"component": "Document library", "column": 3}]},
    ],
}


def rendered(spec=SPEC, cat=None) -> str:
    return render_preview(build_preview(spec, cat))


class TestBuildPreview:
    def test_sections_in_order_with_columns_by_factor(self):
        preview = build_preview(SPEC)
        assert [s.index for s in preview.sections] == [1, 2, 3]
        assert [s.type for s in preview.sections] == ["two-thirds", "one", "three"]
        assert [[c.factor for c in s.columns] for s in preview.sections] == [
            [8, 4],
            [12],
            [4, 4, 4],
        ]

    def test_parts_land_in_their_columns(self):
        preview = build_preview(SPEC)
        first, second, third = preview.sections
        assert [p.alias for p in first.columns[0].parts] == ["NewsWebPart"]
        assert [p.kind for p in first.columns[1].parts] == ["text"]
        assert second.columns[0].parts[0].html == "<p>Raw <em>html</em></p>"
        assert [len(c.parts) for c in third.columns] == [0, 0, 1]

    def test_without_a_catalogue_titles_are_aliases(self):
        preview = build_preview(SPEC)
        news = preview.sections[0].columns[0].parts[0]
        assert (news.title, news.alias, news.resolved) == ("NewsWebPart", "NewsWebPart", False)
        assert preview.resolved is False

    def test_with_a_catalogue_titles_and_descriptions_come_from_it(self):
        preview = build_preview(SPEC, parse_discovery(DISCOVERY))
        news = preview.sections[0].columns[0].parts[0]
        assert (news.title, news.description, news.resolved) == (
            "News",
            "News description",
            True,
        )
        by_title = preview.sections[2].columns[2].parts[0]
        assert by_title.alias == "DocumentLibraryWebPart"
        assert preview.resolved is True

    def test_display_title_wins_over_the_catalogue_title(self):
        spec = {
            "page": "P",
            "sections": [
                {"parts": [{"component": "NewsWebPart", "displayTitle": "Team news"}]}
            ],
        }
        preview = build_preview(spec, parse_discovery(DISCOVERY))
        assert preview.sections[0].columns[0].parts[0].title == "Team news"

    def test_unknown_component_is_shown_unresolved_not_refused(self):
        spec = {"page": "P", "sections": [{"parts": [{"component": "Nope"}]}]}
        part = build_preview(spec, parse_discovery(DISCOVERY)).sections[0].columns[0].parts[0]
        assert (part.alias, part.resolved) == ("Nope", False)

    def test_preview_validates_like_the_compiler(self):
        with pytest.raises(DslError, match="section type"):
            build_preview({"page": "P", "sections": [{"type": "seven-way"}]})
        with pytest.raises(DslError, match="part 1: line 1: tables"):
            build_preview({"page": "P", "sections": [{"parts": [{"text": "a | b"}]}]})


class TestRenderPreview:
    def test_sections_render_in_order_with_their_types(self):
        html = rendered()
        found = re.findall(r'<section data-section="(\d+)" data-type="([\w-]+)">', html)
        assert found == [("1", "two-thirds"), ("2", "one"), ("3", "three")]

    def test_column_widths_follow_the_factors(self):
        html = rendered()
        spans = re.findall(r'data-factor="(\d+)" style="grid-column: span (\d+);"', html)
        assert spans == [
            ("8", "8"),
            ("4", "4"),
            ("12", "12"),
            ("4", "4"),
            ("4", "4"),
            ("4", "4"),
        ]

    def test_text_parts_are_inlined_as_html(self):
        html = rendered()
        assert '<div class="part text"><h1>Welcome</h1>' in html
        assert '<p>A <strong>bold</strong> <a href="/x">link</a>.</p></div>' in html
        assert '<div class="part text"><p>Raw <em>html</em></p></div>' in html

    def test_component_parts_are_placeholder_cards(self):
        html = rendered(cat=parse_discovery(DISCOVERY))
        assert '<p class="title">News</p>' in html
        assert '<p class="alias">NewsWebPart</p>' in html
        assert '<p class="description">News description</p>' in html
        assert "no discovery document given" not in html

    def test_without_a_catalogue_the_header_says_so(self):
        html = rendered()
        assert '<p class="title">NewsWebPart</p>' in html
        assert "titles are aliases (no discovery document given)" in html

    def test_unresolved_parts_are_marked_only_when_a_catalogue_was_given(self):
        spec = {"page": "P", "sections": [{"parts": [{"component": "Nope"}]}]}
        assert "not in the discovery catalogue" in rendered(spec, parse_discovery(DISCOVERY))
        assert "not in the discovery catalogue" not in rendered(spec)

    def test_page_title_is_escaped(self):
        html = rendered()
        assert "<h1>Team &lt;home&gt; &amp; more</h1>" in html
        assert "<title>Team &lt;home&gt; &amp; more · formwork preview</title>" in html

    def test_empty_columns_are_marked(self):
        assert rendered().count('<div class="empty">empty column</div>') == 2

    def test_standalone_document_makes_no_calls(self):
        html = rendered()
        assert html.startswith("<!DOCTYPE html>")
        assert html.endswith("</html>\n")
        assert "<script" not in html
        assert "fetch(" not in html
        assert "_api" not in html


class TestPreviewCommand:
    def write_spec(self, tmp_path):
        spec_path = tmp_path / "page.yaml"
        spec_path.write_text(
            "page: Previewed\n"
            "sections:\n"
            "  - type: two\n"
            "    parts:\n"
            "      - component: NewsWebPart\n"
            "      - text: '## Hello'\n"
            "        column: 2\n",
            encoding="utf-8",
        )
        return spec_path

    def test_writes_html_to_out(self, tmp_path, capsys):
        out = tmp_path / "preview.html"
        rc = main(["preview", str(self.write_spec(tmp_path)), "--out", str(out)])
        assert rc == 0
        html = out.read_text(encoding="utf-8")
        assert "<h2>Hello</h2>" in html
        assert '<p class="title">NewsWebPart</p>' in html
        assert "preview written" in capsys.readouterr().out

    def test_prints_html_to_stdout_by_default(self, tmp_path, capsys):
        rc = main(["preview", str(self.write_spec(tmp_path))])
        assert rc == 0
        assert capsys.readouterr().out.startswith("<!DOCTYPE html>")

    def test_discovery_resolves_titles(self, tmp_path):
        discovery_path = tmp_path / "discovery.json"
        discovery_path.write_text(json.dumps(DISCOVERY), encoding="utf-8")
        out = tmp_path / "preview.html"
        spec_path = self.write_spec(tmp_path)
        rc = main(
            ["preview", str(spec_path), "--discovery", str(discovery_path), "--out", str(out)]
        )
        assert rc == 0
        assert '<p class="title">News</p>' in out.read_text(encoding="utf-8")
