"""Text part bodies: HTML passthrough, or a small markdown subset.

A text part in a page spec is ``{"text": "..."}`` with an optional
``format`` of ``html`` or ``markdown``. Without one, a body whose first
non-blank character is ``<`` is HTML and anything else is markdown.

HTML is passed through as written (outer whitespace stripped). Two things are
refused because they would break the canvas contract rather than the text:
any ``data-sp-`` attribute (the control wrapper owns those) and unbalanced
``<div>`` tags (the wrapper's own closing tag would be swallowed).

The markdown converter is deliberately tiny and dependency-free. It converts
exactly the following and refuses everything else with a :class:`TextError`
that names the line, so nothing is silently dropped or guessed.

Blocks are separated by blank lines:

* ``# Heading`` to ``#### Heading`` -> ``<h1>`` to ``<h4>`` (one line each)
* ``- item`` or ``* item``, one per line -> ``<ul><li>``
* ``1. item``, one per line -> ``<ol><li>`` (the numbers are ignored)
* anything else -> ``<p>``, with the block's lines joined by a space

Inline, inside any block:

* ``**text**`` -> ``<strong>``
* ``*text*`` or ``_text_`` -> ``<em>`` (an ``_`` inside a word is literal)
* ``[text](url)`` -> ``<a href="url">``; the url must be http, https, mailto
  or relative, and the link text is plain
* ``<``, ``>`` and ``&`` are written as entities: the text cannot inject
  markup, and ``a < b`` reads as written

Refused: blockquotes (``>``), tables (any ``|``), code spans and fences
(any backtick), images (``![``), horizontal rules, indented lines (nested
lists, code blocks), headings deeper than ``####``, a heading sharing its
block with other lines, a list block mixing kinds or plain lines, an
unmatched ``*``, and raw HTML tags (use ``format: html`` for an HTML part).
"""

import html
import re

_ALLOWED_SCHEMES = ("http://", "https://", "mailto:")
_MAX_HEADING = 4

_HEADING = re.compile(r"^(#+)\s+(.*)$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^\d+\.\s+(.*)$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_STRONG = re.compile(r"\*\*(.+?)\*\*")
_EM = re.compile(
    r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])"  # *text*
    r"|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)"  # _text_
)
_PLACEHOLDER = re.compile("\x00(\\d+)\x00")

#: Each unsupported construct, matched per line, with the reason given back.
_REFUSED: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$"), "horizontal rules are not supported"),
    (re.compile(r"^(?:\t| {4})"), "indented lines (nested lists, code blocks) are not supported"),
    (re.compile(r"^>"), "blockquotes are not supported"),
    (re.compile(r"\|"), "tables (and any '|') are not supported"),
    (re.compile(r"`"), "code spans and fences are not supported"),
    (re.compile(r"!\["), "images are not supported"),
    (re.compile(r"<[A-Za-z/!]"), "raw HTML inside markdown is not supported (use format: html)"),
)


class TextError(ValueError):
    """A text part's body cannot be converted to HTML."""


def text_to_html(text: str, fmt: str | None = None) -> str:
    """Convert a text part's body to the HTML the canvas will carry."""
    if fmt not in (None, "html", "markdown"):
        raise TextError(f"unknown text format {fmt!r} (use 'html' or 'markdown')")
    if fmt is None:
        fmt = "html" if text.lstrip().startswith("<") else "markdown"
    if fmt == "html":
        return _checked_html(text)
    return markdown_to_html(text)


def markdown_to_html(source: str) -> str:
    """Convert the markdown subset documented in the module docstring."""
    blocks = [_block_to_html(lines, start) for start, lines in _blocks(source)]
    if not blocks:
        raise TextError("text is empty")
    return "".join(blocks)


def _checked_html(source: str) -> str:
    body = source.strip()
    if "data-sp-" in body:
        raise TextError("HTML must not carry data-sp- attributes: the canvas wrapper owns them")
    if body.count("<div") != body.count("</div>"):
        raise TextError("HTML has unbalanced <div> tags: the canvas wrapper would be broken")
    if not body:
        raise TextError("text is empty")
    return body


def _blocks(source: str) -> list[tuple[int, list[str]]]:
    """Split into (first line number, lines) blocks at blank lines."""
    blocks: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start = 0
    for number, line in enumerate(source.splitlines(), start=1):
        if line.strip():
            if not current:
                start = number
            current.append(line)
        elif current:
            blocks.append((start, current))
            current = []
    if current:
        blocks.append((start, current))
    return blocks


def _block_to_html(lines: list[str], start: int) -> str:
    for offset, line in enumerate(lines):
        for pattern, reason in _REFUSED:
            if pattern.search(line):
                raise TextError(f"line {start + offset}: {reason}")
    heading = _HEADING.match(lines[0])
    if heading:
        if len(lines) > 1:
            raise TextError(f"line {start}: a heading must be a block of its own")
        level = len(heading.group(1))
        if level > _MAX_HEADING:
            raise TextError(f"line {start}: headings deeper than #### are not supported")
        return f"<h{level}>{_inline(heading.group(2), start)}</h{level}>"
    if _BULLET.match(lines[0]):
        return _list("ul", _BULLET, lines, start)
    if _NUMBERED.match(lines[0]):
        return _list("ol", _NUMBERED, lines, start)
    return "<p>" + _inline(" ".join(line.strip() for line in lines), start) + "</p>"


def _list(tag: str, item: re.Pattern[str], lines: list[str], start: int) -> str:
    items: list[str] = []
    for offset, line in enumerate(lines):
        matched = item.match(line)
        if not matched:
            raise TextError(
                f"line {start + offset}: every line of a list block must be a list item "
                "of the same kind"
            )
        items.append(f"<li>{_inline(matched.group(1), start + offset)}</li>")
    return f"<{tag}>{''.join(items)}</{tag}>"


def _inline(text: str, line: int) -> str:
    # Links first, held as placeholders: their urls carry '_' and '*' that
    # the emphasis passes must not see, and their text stays plain.
    links: list[str] = []

    def hold_link(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        if not _href_allowed(url):
            raise TextError(
                f"line {line}: link {url!r} must be http, https, mailto or relative"
            )
        links.append(
            f'<a href="{html.escape(url, quote=True)}">{html.escape(label, quote=False)}</a>'
        )
        return f"\x00{len(links) - 1}\x00"

    text = _LINK.sub(hold_link, text)
    text = html.escape(text, quote=False)
    text = _STRONG.sub(r"<strong>\1</strong>", text)
    text = _EM.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text)
    if "*" in text:
        raise TextError(f"line {line}: unmatched '*' (bold is **text**, italic is *text*)")
    return _PLACEHOLDER.sub(lambda m: links[int(m.group(1))], text)


def _href_allowed(url: str) -> bool:
    if url.lower().startswith(_ALLOWED_SCHEMES):
        return True
    # Relative: no scheme, which means no ':' before the first '/', '?' or '#'.
    head = re.split(r"[/?#]", url, maxsplit=1)[0]
    return ":" not in head
