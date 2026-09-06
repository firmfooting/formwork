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
"""

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any

_CONTROL_OPEN = re.compile(r'<div data-sp-canvascontrol=""[^>]*>', re.DOTALL)
_CONTROLDATA = re.compile(r'data-sp-controldata="([^"]*)"')
_WEBPARTDATA = re.compile(r'data-sp-webpartdata="([^"]*)"')


def escape_attribute(value: str) -> str:
    """Escape a JSON string the way SharePoint escapes canvas attributes."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("{", "&#123;")
        .replace("}", "&#125;")
        .replace(":", "&#58;")
    )


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
        controldata = escape_attribute(
            json.dumps(self.control_data, separators=(",", ":"), ensure_ascii=False)
        )
        full = _CONTROLDATA.sub(lambda _m: f'data-sp-controldata="{controldata}"', full, count=1)
        if self.web_part_data is not None:
            webpartdata = escape_attribute(
                json.dumps(self.web_part_data, separators=(",", ":"), ensure_ascii=False)
            )
            full = _WEBPARTDATA.sub(
                lambda _m: f'data-sp-webpartdata="{webpartdata}"', full, count=1
            )
        return full


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
                json.loads(html.unescape(controldata_match.group(1)))
                if controldata_match
                else {}
            )
            web_part_data = (
                json.loads(html.unescape(webpartdata_match.group(1)))
                if webpartdata_match
                else None
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
