"""Integration test: spec + discovery document through the CLI."""

import json
import pathlib

import pytest

from formwork.cli import main

pytest.importorskip("yaml")

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class TestCompileCommand:
    def test_compile_writes_payload_and_prints_parts(self, tmp_path, capsys):
        discovery_path = tmp_path / "discovery.json"
        spec_path = tmp_path / "page.yaml"
        discovery_path.write_text(
            json.dumps(
                {
                    "schema": "formwork.discovery/v1",
                    "web": {"url": "https://x", "id": "w"},
                    "components": [
                        {
                            "ComponentType": 1,
                            "Id": "11111111-1111-1111-1111-111111111111",
                            "Manifest": __import__("json").dumps(
                                {
                                    "id": "11111111-1111-1111-1111-111111111111",
                                    "alias": "NewsWebPart",
                                    "componentType": "WebPart",
                                    "preconfiguredEntries": [
                                        {
                                            "title": {"default": "News"},
                                            "properties": {"layoutId": "FeaturedNews"},
                                        }
                                    ],
                                }
                            ),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        spec_path.write_text(
            """
page: Compiled page
sections:
  - type: two
    parts:
      - component: NewsWebPart
      - component: News
        column: 2
"""
        )
        out = tmp_path / "payload.json"
        rc = main(["compile", str(spec_path), str(discovery_path), "--out", str(out)])
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["title"] == "Compiled page"
        assert "NewsWebPart" in payload["canvas"] or "FeaturedNews" in payload["canvas"]
        printed = capsys.readouterr().out
        assert "NewsWebPart" in printed
