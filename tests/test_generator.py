"""Tests for the paste-in script generators."""

import json
import pathlib
import subprocess

import pytest

from formwork.generator import (
    generate_apply_script,
    generate_discover_script,
    generate_extract_script,
)

EXPECTED_SCHEMA = "formwork.bundle/v1"


def node_available() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


def node_check(script: str, tmp_path: pathlib.Path) -> subprocess.CompletedProcess:
    path = tmp_path / "script.js"
    path.write_text(script, encoding="utf-8")
    return subprocess.run(["node", "--check", str(path)], capture_output=True, check=False)


@pytest.mark.skipif(not node_available(), reason="node is not installed")
class TestExtractScript:
    def test_script_is_syntactically_valid_javascript(self, tmp_path):
        result = node_check(generate_extract_script(), tmp_path)
        assert result.returncode == 0, result.stderr.decode()

    def test_script_fetches_page_by_relative_site_pages_path(self):
        script = generate_extract_script()
        assert 'API("web/lists/getbytitle' in script
        assert "SitePages" in script
        assert "https://" + "placeholder" not in script  # no hardcoded tenant
        # Site-prefixed calls: unprefixed /_api hits the tenant root (measured).
        # The single '"/_api' occurrence is the API helper definition itself.
        assert script.count('"/_api') == 1

    def test_script_builds_expected_bundle_shape(self):
        """The bundle the script assembles must match the wire contract."""
        script = generate_extract_script()
        assert EXPECTED_SCHEMA in script
        for key in ("source", "webUrl", "webPath", "pagePath", "page", "CanvasContent1"):
            assert key in script

    def test_script_uses_camouflage_free_download(self):
        """Download via Blob + anchor, no external libraries."""
        script = generate_extract_script()
        assert "URL.createObjectURL" in script
        assert "formwork-bundle" in script


@pytest.mark.skipif(not node_available(), reason="node is not installed")
class TestDiscoverScript:
    def test_script_is_syntactically_valid_javascript(self, tmp_path):
        result = node_check(generate_discover_script(), tmp_path)
        assert result.returncode == 0, result.stderr.decode()

    def test_script_enumerates_components_and_places_them(self):
        script = generate_discover_script()
        assert "GetClientSideWebParts" in script
        assert "sectionFactor" in script
        assert "recycle" in script
        assert "formwork-discovery.json" in script

    def test_script_cleans_up_the_scratch_page(self):
        script = generate_discover_script()
        # recycle happens before download: no residue if the download stalls
        assert script.index("recycle") < script.index("URL.createObjectURL")


@pytest.mark.skipif(not node_available(), reason="node is not installed")
class TestApplyScript:
    def test_script_is_syntactically_valid_javascript(self, tmp_path):
        result = node_check(generate_apply_script(), tmp_path)
        assert result.returncode == 0, result.stderr.decode()

    def test_script_creates_page_then_patches_canvas(self):
        script = generate_apply_script()
        assert "AddFolder" not in script  # legacy: no misleading calls
        assert 'API("web/lists/getbytitle' in script
        assert "sitepages/pages" in script  # measured: Files/add of .aspx -> 403
        # digest + MERGE + etag concurrency control
        assert "contextinfo" in script
        assert "X-HTTP-Method" in script
        assert "IF-MATCH" in script.upper().replace("_", "-") or "If-Match" in script

    def test_script_reports_verification_step(self):
        script = generate_apply_script()
        assert "CanvasContent1" in script
        assert "verify" in script.lower()

    def test_digest_is_posted_not_get(self):
        # GET /_api/contextinfo is refused with 405 (measured live).
        for script in (generate_apply_script(), generate_discover_script()):
            assert "getDigest" in script
            assert 'getJson("/_api/contextinfo")' not in script

    def test_script_accepts_page_name_variable(self):
        script = generate_apply_script("My Copied Page")
        assert '"My Copied Page"' in script

    def test_embedded_payload_is_configurable(self):
        script = generate_apply_script(page_name="X", canvas_payload='{"k":1}')
        assert '"X"' in script
        assert json.dumps('{"k":1}') in script  # JSON-embedded, quotes escaped
