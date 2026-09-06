"""Tests for the command-line interface."""

import json
import pathlib
import re

import pytest

from formwork.cli import main

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture()
def bundle_path() -> pathlib.Path:
    return FIXTURES / "collabhome.bundle.json"


class TestGenExtract:
    def test_prints_extract_script(self, capsys):
        assert main(["gen", "extract"]) == 0
        out = capsys.readouterr().out
        assert "formwork-bundle.json" in out
        assert "SitePages" in out


class TestInspect:
    def test_inspect_reports_refs(self, bundle_path, capsys):
        assert main(["inspect", str(bundle_path)]) == 0
        out = capsys.readouterr().out
        assert "baseUrl" in out
        assert "Document library" in out
        assert "selectedListId" in out

    def test_inspect_json_output(self, bundle_path, capsys):
        assert main(["inspect", str(bundle_path), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list) and data


class TestProcess:
    def test_process_writes_payload(self, bundle_path, tmp_path, capsys):
        out_path = tmp_path / "payload.json"
        mapping = {
            "baseUrl": "https://shauntestazure.sharepoint.com/sites/TestSampleTeam",
            "siteId": "1" * 8 + "-2222-3333-4444-555555555555",
            "webId": "a" * 8 + "-2222-3333-4444-555555555555",
            "textOverrides": {"Documents": "Reports library"},
        }
        mapping_path = tmp_path / "mapping.json"
        mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
        rc = main(
            [
                "process",
                str(bundle_path),
                "--mapping",
                str(mapping_path),
                "--page-name",
                "Formwork live test",
                "--out",
                str(out_path),
            ]
        )
        assert rc == 0
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["title"] == "Formwork live test"
        assert "CanvasContent1" not in payload["canvas"]  # canvas is raw markup
        assert payload["unresolved"]  # quick-links items stay flagged

    def test_process_reports_unresolved_to_stderr(self, bundle_path, tmp_path, capsys):
        mapping = {"baseUrl": "https://x/sites/T"}
        mapping_path = tmp_path / "mapping.json"
        mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
        rc = main(
            [
                "process",
                str(bundle_path),
                "--mapping",
                str(mapping_path),
                "--out",
                str(tmp_path / "payload.json"),
            ]
        )
        assert rc == 0
        assert "unresolved" in capsys.readouterr().err.lower()


class TestGenApply:
    def test_prints_apply_script_with_embedded_payload(
        self, bundle_path, tmp_path, capsys
    ):
        payload_path = tmp_path / "payload.json"
        payload_path.write_text(
            json.dumps({"title": "T", "canvas": "<div></div>", "unresolved": []}),
            encoding="utf-8",
        )
        assert main(["gen", "apply", str(payload_path), "--name", "Copied page"]) == 0
        out = capsys.readouterr().out
        assert '"Copied page"' in out
        assert "contextinfo" in out
        # The embedded JSON.parse literal decodes to exactly the payload file.
        match = re.search(r'JSON\.parse\("(.+)"\)', out)
        assert match, "no embedded payload literal found"
        decoded = json.loads(json.loads(f'"{match.group(1)}"'))
        assert decoded["canvas"] == "<div></div>"
        assert decoded["title"] == "T"
