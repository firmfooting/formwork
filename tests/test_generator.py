"""Tests for the paste-in script generators.

Golden files
------------
``tests/fixtures/expected/{extract,discover,apply}.js`` hold the emitted
scripts byte for byte (apply with its default arguments). Any generator change
fails the golden tests until the fixtures are deliberately regenerated::

    .venv/bin/python tests/test_generator.py

That runs the same generator calls the golden tests do, so the two cannot
drift. Review the resulting diff like code: it is the paste-in the operator
will run. Regeneration is deliberately a separate, explicit act rather than a
flag on the test run; the friction is the point.
"""

import json
import pathlib
import re
import subprocess

import pytest

from formwork.generator import (
    generate_apply_script,
    generate_discover_script,
    generate_extract_script,
)

EXPECTED_SCHEMA = "formwork.bundle/v1"

#: Committed golden files: the emitted scripts, byte for byte.
EXPECTED = pathlib.Path(__file__).parent / "fixtures" / "expected"

#: Every generated script, by the name of its golden file.
GENERATORS = {
    "extract": generate_extract_script,
    "discover": generate_discover_script,
    "apply": generate_apply_script,
}


def write_golden(path: pathlib.Path, text: str) -> None:
    """Explicit newline: the default emits CRLF on Windows, so the file reads
    as modified locally while producing an empty diff."""
    path.write_text(text, encoding="utf-8", newline="\n")


#: One backslash, composed: the pins below must survive any display or
#: transport layer that rewrites escape sequences in source text.
BS = chr(92)


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


@pytest.mark.parametrize("name", sorted(GENERATORS))
class TestTransportFacts:
    """Transport facts ported from dbml-sharepoint v0.4.0 (read 2026-09-06).

    One pin per fact, on every generated script, so the prelude cannot lose a
    fact without a test going red. Each names the partial the fact came from;
    the prelude comment in generator.py carries the same citation.
    """

    def test_throttle_is_detected_on_the_final_url_not_the_status(self, name):
        # A throttled browser session is redirected to the throttling page,
        # which arrives as 406 because the script asked for JSON. Detection
        # keys on the final URL (dbml-sharepoint _http.js.j2:36-44), and one
        # gate holds every lane (_http.js.j2:45-63). Pins are composed with
        # BS (one backslash) so no transport layer can rewrite escapes.
        script = GENERATORS[name]()
        throttle_re = (
            "/" + BS + "/_layouts" + BS + "/15" + BS + "/throttle"
            + BS + ".htm(" + BS + "?|$)/i"
        )
        assert throttle_re in script
        # `||` here, not `&&`: a throttled browser session arrives as 406
        # from the redirect, not 429/503. Pin the expression across both
        # lines so `||` -> `&&` cannot slip through (review P2-2).
        detection = re.search(
            "res" + BS + ".status === 429 [|][|] res" + BS + ".status === 503"
            + BS + "s* [|][|] " + BS + "s*THROTTLE_PAGE" + BS + ".test"
            + BS + "(res" + BS + ".url",
            script,
        )
        assert detection, "throttle detection must key on the final URL"
        assert "Retry-After" in script
        # Pin the call sites with their await: the bare definitions would
        # otherwise satisfy the pin while the calls were deleted (P2-2).
        assert "await passThrottleGate();" in script
        assert "await holdEveryLane(wait);" in script
        # Every request goes out through fetchWithRetry: the one bare fetch()
        # is the wrapper's own call.
        assert script.count("await fetch(") == 1
        assert "await fetchWithRetry(" in script

    def test_non_ok_responses_surface_the_server_reason(self, name):
        # error.message.value is the server's reason; a bare status left a
        # blocked run undiagnosable (dbml-sharepoint _http.js.j2:25-34, live
        # finding 2026-07-24).
        script = GENERATORS[name]()
        assert "?.error?.message?.value" in script
        # No throw is left carrying only the status.
        assert not re.search(r'-> " \+ \w+\.status\)', script)
        # Every non-OK branch raises through failed(), which shapes the body
        # with spError, or shapes it with spError directly (the digest).
        checks = list(re.finditer(r"if \(!\w+\.ok\)", script))
        assert len(checks) >= 6, "the pin is meaningless if nothing is checked"
        for check in checks:
            window = script[check.end() : check.end() + 200]
            assert "failed(" in window or "spError(" in window, window

    def test_contextinfo_parse_is_guarded(self, name):
        # The blind .d.GetContextWebInformation.FormDigestValue chain is what
        # reported dbml-sharepoint #282 as a TypeError in place of the
        # server's reason (dbml-sharepoint _digest_cached.js.j2:9-42).
        script = GENERATORS[name]()
        assert not re.search(r"\)\s*\.d\s*\.GetContextWebInformation", script)
        assert "?.d?.GetContextWebInformation" in script
        assert "contextinfo (request digest) failed: " in script
        for guard in (
            "no response (",
            "with an unreadable body (",
            "carried no GetContextWebInformation",
            "carried no usable FormDigestValue",
        ):
            assert guard in script, guard
        # Still POSTed (GET -> 405), and parsed in exactly one place.
        assert re.search(r'API\("contextinfo"\), \{\n\s*method: "POST"', script)
        assert script.count("?.d?.GetContextWebInformation") == 1

    def test_list_titles_are_odata_quoted(self, name):
        # getbytitle('...') takes an OData literal: an embedded apostrophe is
        # doubled, then the whole is URI-encoded (dbml-sharepoint
        # _site_guard.js.j2:24-27).
        script = GENERATORS[name]()
        assert "const odataLiteral = (s) => String(s).replace(/'/g, \"''\");" in script
        assert "const odataName = (name) => encodeURIComponent(odataLiteral(name));" in script
        # The only getbytitle left is the helper; every list URL goes through it.
        assert script.count("getbytitle(") == 1
        assert "getbytitle('\" + odataName(title) + \"')" in script
        assert "'Site Pages'" not in script
        assert 'listByTitle("Site Pages")' in script


def test_extract_filter_literal_doubles_apostrophes():
    # The same OData rule applies to the $filter literal the extract script
    # builds from the page's file name (a page named "Bob's page.aspx" is
    # legal). Doubling only: the whole filter is URI-encoded once, after.
    script = generate_extract_script()
    assert "\"FileLeafRef eq '\" + odataLiteral(fileName) + \"'\"" in script


@pytest.mark.parametrize("name", sorted(GENERATORS))
def test_script_matches_golden(name):
    """Golden-file regression: each generated script must match its committed
    fixture byte for byte. See the module docstring for the regeneration
    command."""
    golden_path = EXPECTED / f"{name}.js"
    assert golden_path.exists(), f"golden file missing: {golden_path}"
    assert GENERATORS[name]() == golden_path.read_text(encoding="utf-8"), (
        f"the {name} script output has changed. If the change is intentional, "
        "regenerate the golden files (see the module docstring for the command) "
        "and review the diff."
    )


if __name__ == "__main__":  # pragma: no cover
    # Regenerate the goldens. Deliberately not a pytest flag: see
    # test_script_matches_golden. Uses the SAME generator calls the test does.
    EXPECTED.mkdir(parents=True, exist_ok=True)
    for _name, _generate in GENERATORS.items():
        _target = EXPECTED / f"{_name}.js"
        write_golden(_target, _generate())
        print(f"wrote {_target}")
