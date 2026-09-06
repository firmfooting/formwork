"""Extraction bundle parsing and validation.

A bundle is the JSON file the extract paste-in downloads from the source
page: schema envelope, source identity, page fields, section plan and
web part inventory. Everything downstream (processing, apply) reads the
bundle through the typed view built here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from formwork import BUNDLE_SCHEMA


@dataclass(frozen=True)
class Source:
    """Identity of the page the bundle was extracted from."""

    web_url: str
    web_path: str
    page_path: str


@dataclass(frozen=True)
class Bundle:
    """Typed view over an extraction bundle."""

    schema: str
    extracted_at: str
    source: Source
    meta: dict[str, Any] = field(default_factory=dict)
    page: dict[str, Any] = field(default_factory=dict)
    sections: list[dict[str, Any]] = field(default_factory=list)
    web_parts: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def canvas_html(self) -> str | None:
        """Classic page layout HTML, when the source page carries one."""
        return self.page.get("CanvasContent1")


def _require(data: dict[str, Any], key: str) -> None:
    if key not in data:
        raise ValueError(f"bundle is missing required key: {key}")


def parse_bundle(data: dict[str, Any] | str) -> Bundle:
    """Validate an extraction bundle and return its typed view.

    Accepts an already-parsed dict or a raw JSON string (as downloaded
    by the extract paste-in).
    """
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        # ValueError, not TypeError: this is data content, and the tests pin it.
        raise ValueError("bundle must be a JSON object")

    _require(data, "schema")
    if data["schema"] != BUNDLE_SCHEMA:
        raise ValueError(
            f"unsupported bundle schema: {data['schema']!r} (expected {BUNDLE_SCHEMA!r})"
        )

    _require(data, "page")
    source = data.get("source", {})
    for key in ("webUrl", "webPath", "pagePath"):
        if key not in source:
            raise ValueError(f"bundle source is missing required key: {key}")

    return Bundle(
        schema=data["schema"],
        extracted_at=data.get("extractedAt", ""),
        source=Source(
            web_url=source["webUrl"],
            web_path=source["webPath"],
            page_path=source["pagePath"],
        ),
        meta=data.get("meta", {}),
        page=data["page"],
        sections=data.get("sections", []),
        web_parts=data.get("webParts", []),
        raw=data,
    )
