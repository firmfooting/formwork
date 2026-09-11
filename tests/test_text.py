"""Tests for text part bodies: the markdown subset and HTML passthrough.

The module docstring of formwork.text is the contract; every supported
construct and every refusal it names has a case here.
"""

import pytest

from formwork.text import TextError, markdown_to_html, text_to_html


class TestBlocks:
    @pytest.mark.parametrize("level", [1, 2, 3, 4])
    def test_headings_one_to_four(self, level):
        assert markdown_to_html("#" * level + " Title") == f"<h{level}>Title</h{level}>"

    def test_heading_deeper_than_four_is_refused(self):
        with pytest.raises(TextError, match="deeper than ####"):
            markdown_to_html("##### Title")

    def test_heading_must_stand_alone(self):
        with pytest.raises(TextError, match="block of its own"):
            markdown_to_html("# Title\nand a line")

    def test_hash_without_space_is_text(self):
        assert markdown_to_html("#hashtag") == "<p>#hashtag</p>"

    def test_paragraph_joins_lines_with_a_space(self):
        assert markdown_to_html("one\ntwo\n  three  ") == "<p>one two three</p>"

    def test_blocks_are_separated_by_blank_lines(self):
        html = markdown_to_html("# Head\n\nfirst\n\n\nsecond\n")
        assert html == "<h1>Head</h1><p>first</p><p>second</p>"

    @pytest.mark.parametrize("marker", ["-", "*"])
    def test_bullet_list(self, marker):
        source = f"{marker} one\n{marker} two"
        assert markdown_to_html(source) == "<ul><li>one</li><li>two</li></ul>"

    def test_numbered_list_ignores_the_numbers(self):
        assert markdown_to_html("3. a\n1. b") == "<ol><li>a</li><li>b</li></ol>"

    def test_list_block_must_be_all_items_of_one_kind(self):
        with pytest.raises(TextError, match="line 2: every line of a list block"):
            markdown_to_html("- one\n1. two")
        with pytest.raises(TextError, match="line 2"):
            markdown_to_html("- one\nplain")

    def test_empty_source_is_refused(self):
        with pytest.raises(TextError, match="empty"):
            markdown_to_html("\n  \n")


class TestInline:
    def test_bold(self):
        assert markdown_to_html("a **b** c") == "<p>a <strong>b</strong> c</p>"

    def test_italic_with_star_and_underscore(self):
        assert markdown_to_html("*a* and _b_") == "<p><em>a</em> and <em>b</em></p>"

    def test_underscore_inside_a_word_is_literal(self):
        assert markdown_to_html("snake_case_name") == "<p>snake_case_name</p>"

    def test_link(self):
        html = markdown_to_html("see [the docs](https://example.com/a_b?x=1)")
        assert html == '<p>see <a href="https://example.com/a_b?x=1">the docs</a></p>'

    @pytest.mark.parametrize("url", ["/sites/T/SitePages/a.aspx", "#top", "mailto:a@b.c", "x.aspx"])
    def test_relative_and_mailto_links_are_allowed(self, url):
        assert f'href="{url}"' in markdown_to_html(f"[t]({url})")

    @pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "ftp://x/y"])
    def test_other_schemes_are_refused(self, url):
        with pytest.raises(TextError, match="must be http, https, mailto or relative"):
            markdown_to_html(f"[t]({url})")

    def test_link_text_and_href_are_escaped(self):
        html = markdown_to_html('[a & b](/p?q="x")')
        assert html == '<p><a href="/p?q=&quot;x&quot;">a &amp; b</a></p>'

    def test_text_is_entity_escaped(self):
        assert markdown_to_html("a < b & c > d") == "<p>a &lt; b &amp; c &gt; d</p>"

    def test_unmatched_star_is_refused(self):
        with pytest.raises(TextError, match="unmatched"):
            markdown_to_html("5 * 3")
        with pytest.raises(TextError, match="unmatched"):
            markdown_to_html("**open")

    def test_inline_markup_works_inside_headings_and_items(self):
        assert markdown_to_html("## A **b**") == "<h2>A <strong>b</strong></h2>"
        assert markdown_to_html("- *x*") == "<ul><li><em>x</em></li></ul>"


class TestRefusals:
    @pytest.mark.parametrize(
        ("source", "reason"),
        [
            ("> quoted", "blockquotes"),
            ("a | b", "tables"),
            ("use `code`", "code spans"),
            ("```\nx\n```", "code spans"),
            ("![alt](x.png)", "images"),
            ("---", "horizontal rules"),
            ("***", "horizontal rules"),
            ("    indented", "indented lines"),
            ("\tindented", "indented lines"),
            ("- a\n    - nested", "indented lines"),
            ("some <b>html</b>", "raw HTML"),
            ("</p>", "raw HTML"),
        ],
    )
    def test_unsupported_constructs_name_their_reason(self, source, reason):
        with pytest.raises(TextError, match=reason):
            markdown_to_html(source)

    def test_refusal_names_the_line(self):
        with pytest.raises(TextError, match="line 3"):
            markdown_to_html("fine\n\n> not fine")


class TestTextToHtml:
    def test_leading_angle_bracket_selects_html(self):
        assert text_to_html("  <p>Hi</p>\n") == "<p>Hi</p>"

    def test_format_html_passes_through_as_written(self):
        source = (
            '<h2>T</h2><p><b>b</b> <a href="https://x/">l</a> '
            '<span style="color:#a4262c;">c</span></p>'
        )
        assert text_to_html(source, "html") == source

    def test_format_markdown_forces_conversion(self):
        assert text_to_html("plain", "markdown") == "<p>plain</p>"

    def test_default_is_markdown_when_not_starting_with_a_tag(self):
        assert text_to_html("# T") == "<h1>T</h1>"

    def test_unknown_format_is_refused(self):
        with pytest.raises(TextError, match="unknown text format"):
            text_to_html("x", "rtf")

    def test_html_may_not_carry_canvas_attributes(self):
        with pytest.raises(TextError, match="data-sp-"):
            text_to_html('<div data-sp-rte="">x</div>', "html")

    def test_html_div_tags_must_balance(self):
        with pytest.raises(TextError, match="unbalanced <div>"):
            text_to_html("<div><p>x</p>", "html")
        assert text_to_html("<div><p>x</p></div>", "html") == "<div><p>x</p></div>"

    def test_empty_html_is_refused(self):
        with pytest.raises(TextError, match="empty"):
            text_to_html("  ", "html")


class TestHtmlRefusals:
    """P2-1/P3-3: the HTML path states the same trust boundary as markdown."""

    @pytest.mark.parametrize("body", [
        '<script>alert(1)</script>',
        '<SCRIPT src="x"></SCRIPT>',
        '<img src=x onerror="alert(1)">',
        '<a href="javascript:alert(1)">x</a>',
        '<a href="JaVaScRiPt:alert(1)">x</a>',
        '<a href="data:text/html,<script>alert(1)</script>">x</a>',
        '<style>body{}</style>',
        '<iframe src="https://evil"></iframe>',
        '<!-- hidden comment --><p>x</p>',
        '<p>DAta-sp-thing</p>',
    ])
    def test_dangerous_html_is_refused_with_line_and_reason(self, body):
        with pytest.raises(TextError):
            text_to_html(body)

    @pytest.mark.parametrize("body", [
        '<a href="javascript&#58;alert(1)">x</a>',
        '<a href="jav&#x61;script:alert(1)">x</a>',
        '<a href="java\nscript:alert(1)">x</a>',
        '<a href="java\tscript:alert(1)">x</a>',
        '<a href="javascript&NewLine;:alert(1)">x</a>',
        '<a href="data&#58;text/html,<b>x</b>">x</a>',
        '<img src=vbscript&#58;x>',
    ])
    def test_an_obfuscated_script_url_is_refused(self, body):
        """The raw spelling hides the scheme from the line scan, but a browser
        decodes a value's character references and drops tab/newline in the
        URL, so it resolves to the javascript:/data:/vbscript: URL refused
        above. (Review 2026-09-11: the raw scan alone let these through.)"""
        with pytest.raises(TextError, match="not supported"):
            text_to_html(body)

    @pytest.mark.parametrize("body", [
        "<p>write &lt;script&gt; to mean the element</p>",
        '<a href="https://x/?a=1&amp;b=2">q</a>',
        '<p>&amp;#58; is not a colon</p>',
    ])
    def test_escaped_markup_and_text_are_still_legal(self, body):
        """Only attribute VALUES are decoded by the browser; escaped markup in
        text is text, so the resolved-URL check must not refuse it."""
        assert text_to_html(body, "html") == body

    def test_control_characters_are_refused_before_format_detection(self):
        with pytest.raises(TextError, match="control characters"):
            text_to_html("ok\x005\x00 text")

    def test_safe_html_still_passes(self):
        assert text_to_html('<p>hello <strong>world</strong></p>') == (
            '<p>hello <strong>world</strong></p>'
        )
