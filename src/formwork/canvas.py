"""CanvasContent1 parsing and rendering.

SharePoint stores a modern page's layout in CanvasContent1 as HTML-encoded
canvas markup. Each control is a ``<div data-sp-canvascontrol ...>`` whose
``data-sp-controldata`` attribute holds entity-escaped JSON giving the
control's position; web-part controls additionally carry a
``data-sp-webpartdata`` attribute with the web part's id, title, properties
and serverProcessedContent.

Measured escaping style (CollabHome.aspx, shauntestazure sandbox, 2026-09-05):
``&`` -> ``&amp;`` first, then ``< > "`` as named entities and ``{ } :`` as
numeric entities. Slashes and single quotes are NOT escaped. Because the
parser keeps every control's raw attribute text, rendering a parsed, untouched
canvas is byte-exact; only controls marked dirty are re-serialised.

This module is the one serialiser for canvas attributes (architecture
review 2026-09-06 P2-7): :func:`encode_attribute` is the JSON-then-escape
the renderer and the compiler both emit, :func:`decode_attribute` the
unescape-then-JSON the parser and the catalogue both read, and
:meth:`Control.web_part` / :meth:`Control.text` the two control shapes the
compiler writes. Nothing else in the package spells the attribute grammar.
"""

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any

_CONTROL_OPEN = re.compile(r'<div data-sp-canvascontrol=""[^>]*>', re.DOTALL)
_CONTROLDATA = re.compile(r'data-sp-controldata="([^"]*)"')
_WEBPARTDATA = re.compile(r'data-sp-webpartdata="([^"]*)"')

#: One ``data-sp-htmlproperties`` child whose text is a verbatim copy of a
#: ``serverProcessedContent.searchablePlainTexts`` value. Measured on
#: CollabHome.aspx (shauntestazure sandbox, 2026-09-05): a list title persists
#: beside the webpartdata attribute as
#: ``<div data-sp-prop-name="listTitle" data-sp-searchableplaintext="true">``.
#: The mirrors SharePoint derives rather than copies — a ``links`` href is
#: server-relative where the JSON value is absolute, and a ``links`` URL or a
#: ``componentDependencies`` GUID is re-spelled into an attribute — do not
#: match this shape and are never rewritten.
_MIRROR_TEXT = re.compile(
    r'(<div data-sp-prop-name="(?P<name>[^"]+)" data-sp-searchableplaintext="true">)'
    r'(?P<text>[^<]*)</div>'
)


def _plain_texts(data: Any) -> dict[str, Any]:
    """The ``serverProcessedContent.searchablePlainTexts`` mapping, or empty."""
    if not isinstance(data, dict):
        return {}
    processed = data.get("serverProcessedContent")
    if not isinstance(processed, dict):
        return {}
    texts = processed.get("searchablePlainTexts")
    return texts if isinstance(texts, dict) else {}


#: How SharePoint spells a colon inside canvas markup: in every attribute it
#: escapes (below) and, measured 2026-09-06, in the inner HTML of a text
#: control's ``data-sp-rte`` child on the item MERGE path
#: (:func:`formwork.dsl.stored_text_html`; folded back on the read side by
#: :mod:`formwork.catalogue`).
COLON_ENTITY = "&#58;"

#: The opening of every canvas control the compiler writes: the shape the
#: discover probe sends and the live canvas stores (data version 1.0).
_CONTROL_OPEN_PREFIX = '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0" '


def escape_attribute(value: str) -> str:
    """Escape a JSON string the way SharePoint escapes canvas attributes."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("{", "&#123;")
        .replace("}", "&#125;")
        .replace(":", COLON_ENTITY)
    )


def encode_attribute(data: Any) -> str:
    """A controldata/webpartdata attribute value: compact JSON, then escaped.

    Non-ASCII stays literal (``ensure_ascii=False``): the live canvas stores
    a curly apostrophe as the character, not ``\\u2019``, and the attribute
    is entity-escaped anyway.
    """
    return escape_attribute(json.dumps(data, separators=(",", ":"), ensure_ascii=False))


def decode_attribute(raw: str) -> Any:
    """The JSON value of a controldata/webpartdata attribute's raw text.

    The inverse of :func:`encode_attribute` and of SharePoint's own
    escaping; the same unescape-then-parse the discover probe does with
    DOMParser and ``JSON.parse``. Raises ``ValueError`` (``JSONDecodeError``)
    for an attribute that does not hold JSON.
    """
    return json.loads(html.unescape(raw))


@dataclass
class Control:
    """One canvas control, holding both its raw and decoded forms."""

    open_tag: str
    control_data: dict[str, Any]
    web_part_data: dict[str, Any] | None
    controldata_raw: str
    webpartdata_raw: str | None
    body: str = ""
    dirty: bool = field(default=False, repr=False)

    @classmethod
    def web_part(cls, control_data: dict[str, Any], web_part_data: dict[str, Any]) -> "Control":
        """A web-part control: the control div wrapping a webpartdata child.

        The same shape the live canvas writes and the discover probe sends
        (discover.js.j2 step 3): the web-part child carries an empty
        ``data-sp-htmlproperties``, then the control div closes. The raw
        attributes are the encoded dicts, so the control renders byte-for-
        byte as a parsed-then-dirtied one would, without being dirty.
        """
        controldata = encode_attribute(control_data)
        webpartdata = encode_attribute(web_part_data)
        # The web-part child div, then the close of the control div itself.
        body = f'<div data-sp-webpartdata="{webpartdata}" data-sp-htmlproperties=""></div></div>'
        return cls(
            open_tag=f'{_CONTROL_OPEN_PREFIX}data-sp-controldata="{controldata}">',
            control_data=control_data,
            web_part_data=web_part_data,
            controldata_raw=controldata,
            webpartdata_raw=webpartdata,
            body=body,
        )

    @classmethod
    def text(cls, control_data: dict[str, Any], inner_html: str) -> "Control":
        """A text control: the control div wrapping a ``data-sp-rte`` child.

        ``inner_html`` is stored as given; the caller spells it the way
        SharePoint stores it (:func:`formwork.dsl.stored_text_html`).
        """
        controldata = encode_attribute(control_data)
        return cls(
            open_tag=f'{_CONTROL_OPEN_PREFIX}data-sp-controldata="{controldata}">',
            control_data=control_data,
            web_part_data=None,
            controldata_raw=controldata,
            webpartdata_raw=None,
            body=f'<div data-sp-rte="">{inner_html}</div></div>',
        )

    @property
    def web_part_title(self) -> str | None:
        if self.web_part_data is None:
            return None
        title = self.web_part_data.get("title")
        return title if isinstance(title, str) else None

    def mark_dirty(self) -> None:
        self.dirty = True

    def render(self) -> str:
        if not self.dirty:
            return self.open_tag + self.body
        # The controldata attribute sits on the control's own tag; the
        # webpartdata attribute sits on a child div. Substitute over the
        # whole block so both are covered.
        #
        # The replacement is a CALLABLE, not an f-string: re.sub parses
        # backslash escapes in a string template, so re-escaped JSON
        # (json.dumps emits \uXXXX for non-ASCII, \n, \\ …) either crashed
        # the render with re.error: bad escape or silently corrupted the
        # attribute bytes (found by the 2026-09-06 P1-fix re-review; a
        # curly apostrophe in a Quick links title was enough).
        full = self.open_tag + self.body
        controldata = encode_attribute(self.control_data)
        full = _CONTROLDATA.sub(lambda _m: f'data-sp-controldata="{controldata}"', full, count=1)
        if self.web_part_data is not None:
            webpartdata = encode_attribute(self.web_part_data)
            full = _WEBPARTDATA.sub(
                lambda _m: f'data-sp-webpartdata="{webpartdata}"', full, count=1
            )
            full = self._sync_mirrors(full)
        return full

    def _sync_mirrors(self, full: str) -> str:
        """Rewrite the plain-text ``data-sp-htmlproperties`` mirrors this render changed.

        SharePoint keeps a web part's values twice: in the ``data-sp-webpartdata``
        attribute, and in a ``data-sp-htmlproperties`` child that mirrors them for
        the page model (measured on CollabHome.aspx, 2026-09-05). :meth:`render`
        rewrites the attribute; the mirror is inner content and would otherwise
        keep the value the control was parsed with, so a page rewritten for
        another site carried the source site's list title and hrefs (raised as P2
        by the 2026-09-06 P1-fix re-review and left unactioned). A mirror is
        rewritten only when it provably carried the old value verbatim and the new
        value needs no HTML escaping, so a mirror whose spelling SharePoint
        derives rather than copies (the ``links`` hrefs) and the byte-exact render
        of an unchanged dirty control are both left exactly as they were.
        """
        if self.webpartdata_raw is None:
            return full
        old_texts = _plain_texts(decode_attribute(self.webpartdata_raw))
        changed = {
            name: value
            for name, value in _plain_texts(self.web_part_data).items()
            if isinstance(value, str) and old_texts.get(name) != value
        }
        if not changed:
            return full

        def mirror(match: re.Match[str]) -> str:
            value = changed.get(match.group("name"))
            if value is None or match.group("text") != old_texts.get(match.group("name")):
                return match.group(0)
            if any(character in value for character in "&<>"):
                return match.group(0)
            return f"{match.group(1)}{value}</div>"

        return _MIRROR_TEXT.sub(mirror, full)


@dataclass
class Canvas:
    """A parsed CanvasContent1 string."""

    controls: list[Control]
    preamble: str = ""

    @classmethod
    def parse(cls, canvas_content: str) -> "Canvas":
        controls: list[Control] = []
        first = _CONTROL_OPEN.search(canvas_content)
        preamble = canvas_content[: first.start()] if first else canvas_content
        if first is None:
            return cls(controls=[], preamble=preamble)
        for match in _CONTROL_OPEN.finditer(canvas_content):
            open_tag = match.group(0)
            # Control extends to the next control's opening tag, or the end.
            next_match = _CONTROL_OPEN.search(canvas_content, match.end())
            end = next_match.start() if next_match else len(canvas_content)
            body = canvas_content[match.end() : end]
            block = open_tag + body

            controldata_match = _CONTROLDATA.search(block)
            webpartdata_match = _WEBPARTDATA.search(block)
            control_data = (
                decode_attribute(controldata_match.group(1)) if controldata_match else {}
            )
            web_part_data = (
                decode_attribute(webpartdata_match.group(1)) if webpartdata_match else None
            )
            controls.append(
                Control(
                    open_tag=open_tag,
                    control_data=control_data,
                    web_part_data=web_part_data,
                    controldata_raw=controldata_match.group(1) if controldata_match else "",
                    webpartdata_raw=webpartdata_match.group(1) if webpartdata_match else None,
                    body=body,
                )
            )
        return cls(controls=controls, preamble=preamble)

    def render(self) -> str:
        parts = [control.render() for control in self.controls]
        if self.preamble:
            parts.insert(0, self.preamble)
        return "".join(parts)

    def web_part_controls(self) -> list[Control]:
        return [control for control in self.controls if control.web_part_data is not None]
