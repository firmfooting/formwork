"""Integration test: spec + discovery document through the CLI."""

import json
import pathlib

import pytest

from formwork.cli import main
from test_dsl import DISCOVERY

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

    def test_compile_prints_a_part_s_emphasis(self, tmp_path, capsys):
        discovery_path = tmp_path / "discovery.json"
        discovery_path.write_text(json.dumps(DISCOVERY), encoding="utf-8")
        spec_path = tmp_path / "page.yaml"
        spec_path.write_text(
            "page: Emphasised\n"
            "sections:\n"
            "  - type: two\n"
            "    parts:\n"
            "      - component: NewsWebPart\n"
            "        emphasis: 2\n"
            "      - component: NewsWebPart\n"
            "        column: 2\n",
            encoding="utf-8",
        )
        out = tmp_path / "payload.json"
        rc = main(["compile", str(spec_path), str(discovery_path), "--out", str(out)])
        assert rc == 0
        lines = capsys.readouterr().out.splitlines()
        assert "  section 1, column 1: NewsWebPart (News, zoneEmphasis 2)" in lines
        assert "  section 1, column 2: NewsWebPart (News)" in lines
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert "&quot;zoneEmphasis&quot;&#58;2" in payload["canvas"]

    def test_a_refused_spec_is_one_error_line_not_a_traceback(self, tmp_path, capsys):
        # Review P3-6 (2026-09-06): main() catches DslError and prints the
        # message; nothing is written and there is no traceback.
        discovery_path = tmp_path / "discovery.json"
        discovery_path.write_text(json.dumps(DISCOVERY), encoding="utf-8")
        spec_path = tmp_path / "page.yaml"
        spec_path.write_text(
            "page: P\nsections:\n  - parts:\n      - component: Nope\n", encoding="utf-8"
        )
        out = tmp_path / "payload.json"
        rc = main(["compile", str(spec_path), str(discovery_path), "--out", str(out)])
        assert rc == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("error: component 'Nope' is not placeable on this site")
        assert captured.err.count("\n") == 1
        assert "Traceback" not in captured.err
        assert not out.exists()

    def test_a_missing_spec_file_is_one_error_line_not_a_traceback(self, tmp_path, capsys):
        discovery_path = tmp_path / "discovery.json"
        discovery_path.write_text(json.dumps(DISCOVERY), encoding="utf-8")
        rc = main(["compile", str(tmp_path / "absent.yaml"), str(discovery_path)])
        assert rc == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("error: ")
        assert "absent.yaml" in captured.err
        assert captured.err.count("\n") == 1
        assert "Traceback" not in captured.err
