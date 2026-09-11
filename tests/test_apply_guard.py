"""The apply paste-in's provenance guard and its PromotedState leg (M8).

Static pins first: the script reads ``PAYLOAD.provenance`` before it creates
anything, declares the operator switch and its own version constant, and keeps
the version check outside the switch. Then, with node present, the generated
script RUNS against a stubbed SharePoint that answers as the sandbox did and
records every request. So the guard is seen refusing a web-id mismatch with
both values named and no create sent; ``FORCE_SITE_MISMATCH`` is seen letting
the site check pass while the version check stays shut; and the create body is
seen carrying ``PromotedState: 1`` (nothing for 0) with no MERGE of it, the
leg measured in ``page.promoted-state.create-is-effective`` (2026-09-06).
"""

import json
import pathlib
import re
import subprocess

import pytest

import formwork
from formwork.cli import main
from formwork.generator import generate_apply_script
from test_generator import APPLY_PAYLOAD_STAMP, GENERATORS, node_available

#: The web the pagestate fixture was discovered on, as discover records it:
#: web.d.Id, and location.origin plus the web's server-relative root.
ORIGIN = "https://shauntestazure.sharepoint.com"
SERVER_RELATIVE_URL = "/sites/TestSampleTeam"
WEB_ID = APPLY_PAYLOAD_STAMP["discoveryWebId"]
OTHER_WEB_ID = "ffffffff-0000-4000-8000-000000000000"
CANVAS = "<div>canvas</div>"
CREATE_URL = "/_api/sitepages/pages"

#: A SharePoint the script can be run against under node. Every request is
#: recorded; the answers are the shapes the sandbox gave (a 201 create with
#: Id and Url, an etag on the item read, 204 on MERGE, the merged canvas on
#: the verify read). PromotedState reads back as sent at create unless the
#: fixture pins a stored value.
HARNESS = r"""
const fs = require("fs");
const [scriptPath, fixturePath] = process.argv.slice(2);
const fx = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const calls = [], logs = [], warns = [], errors = [];
let merged = null;
let createdFields = null;
globalThis.location = { origin: fx.origin, pathname: fx.pathname };
const reply = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  url: "",
  headers: { get: () => null },
  json: async () => body,
  text: async () => JSON.stringify(body),
});
globalThis.fetch = async (url, init) => {
  const method = (init && init.method) || "GET";
  const headers = (init && init.headers) || {};
  const body = init && typeof init.body === "string" ? init.body : null;
  calls.push({ url, method, headers, body });
  if (url.endsWith("/_api/contextinfo")) {
    return reply(200, { d: { GetContextWebInformation: { FormDigestValue: "digest" } } });
  }
  if (url.endsWith("/_api/web?$select=Id,ServerRelativeUrl")) {
    return reply(200, { d: { Id: fx.webId, ServerRelativeUrl: fx.serverRelativeUrl } });
  }
  if (url.endsWith("/_api/sitepages/pages") && method === "POST") {
    createdFields = JSON.parse(body);
    return reply(201, { d: { Id: 77, Url: fx.serverRelativeUrl + "/SitePages/New.aspx" } });
  }
  if (/\/items\(77\)\?\$select=/.test(url)) {
    const sent = createdFields && createdFields.PromotedState !== undefined
      ? createdFields.PromotedState : 0;
    const stored = fx.storedPromotedState === null ? sent : fx.storedPromotedState;
    return reply(200, { d: { CanvasContent1: merged, Title: "T", PromotedState: stored } });
  }
  if (/\/items\(77\)$/.test(url) && headers["X-HTTP-Method"] === "MERGE") {
    merged = JSON.parse(body).CanvasContent1;
    return reply(204, {});
  }
  if (/\/items\(77\)$/.test(url)) {
    return reply(200, { d: { __metadata: { etag: '"1"' } } });
  }
  return reply(404, { error: { message: { value: "unstubbed " + method + " " + url } } });
};
const text = (a) => a.map((x) => (x instanceof Error ? x.message : String(x))).join(" ");
console.log = (...a) => logs.push(text(a));
console.warn = (...a) => warns.push(text(a));
console.error = (...a) => errors.push(text(a));
process.on("beforeExit", () => {
  process.stdout.write(JSON.stringify({ calls, logs, warns, errors, createdFields }) + "\n");
  process.exit(0);
});
require(scriptPath);
"""


def payload(stamp=APPLY_PAYLOAD_STAMP, **fields):
    """A compile-shaped payload; ``stamp=None`` leaves the provenance out."""
    body = {"schema": "formwork.payload/v1", "title": "T", "canvas": CANVAS, "unresolved": []}
    if stamp is not None:
        body["provenance"] = stamp
    body.update(fields)
    return json.dumps(body)


def forced(script: str) -> str:
    """The script with the operator's one edit made: the switch flipped."""
    switch = "const FORCE_SITE_MISMATCH = false;"
    assert script.count(switch) == 1
    return script.replace(switch, "const FORCE_SITE_MISMATCH = true;")


def run_apply(
    tmp_path: pathlib.Path,
    script: str,
    *,
    web_id: str = WEB_ID,
    server_relative_url: str = SERVER_RELATIVE_URL,
    stored_promoted: int | None = None,
) -> dict:
    (tmp_path / "apply.js").write_text(script, encoding="utf-8")
    (tmp_path / "harness.js").write_text(HARNESS, encoding="utf-8")
    fixture = {
        "origin": ORIGIN,
        "pathname": server_relative_url + "/SitePages/Home.aspx",
        "webId": web_id,
        "serverRelativeUrl": server_relative_url,
        "storedPromotedState": stored_promoted,
    }
    (tmp_path / "fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
    result = subprocess.run(
        [
            "node",
            str(tmp_path / "harness.js"),
            str(tmp_path / "apply.js"),
            str(tmp_path / "fixture.json"),
        ],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    return json.loads(result.stdout.decode("utf-8").splitlines()[-1])


def creates(run: dict) -> list:
    return [c for c in run["calls"] if c["url"].endswith(CREATE_URL)]


def bodies(run: dict) -> list:
    return [c["body"] for c in run["calls"] if c["body"]]


class TestTheGuardIsInTheScript:
    def test_the_stamp_is_read_before_anything_is_created(self):
        script = generate_apply_script()
        read = script.index("const STAMP = PAYLOAD.provenance;")
        web = script.index('API("web?$select=Id,ServerRelativeUrl")')
        create = script.index("await createSitePage(")
        assert read < web < create
        # Every refusal is a throw with nothing created, and says so: no stamp,
        # newer formwork, site mismatch, and a stamp naming neither a discovery
        # nor a bundle (the fail-closed shape check).
        assert script.count("Nothing was created.") == 4

    def test_the_site_check_is_keyed_on_the_stamp_shape_not_one_field_type(self):
        """The site check must run for every stamp compile writes, whatever
        type one field happens to have: keying it on
        ``typeof STAMP.discoveryWebId === "string"`` skipped it in silence for a
        compile stamp that had lost that field (see the node tests below)."""
        script = generate_apply_script()
        # The old gate (the whole site check hung on one field's type) is gone.
        assert 'if (typeof STAMP.discoveryWebId === "string") {' not in script
        assert "const isCompileStamp = COMPILE_MARKERS.some(" in script
        assert 'const COMPILE_MARKERS = ["discoverySha256", "discoveryWebId",' in script

    def test_the_switch_and_the_version_constant_are_declared_and_documented(self):
        script = generate_apply_script()
        assert "const FORCE_SITE_MISMATCH = false;" in script
        assert f'const FORMWORK_VERSION = "{formwork.__version__}";' in script
        # The header, above the prelude, is where the operator reads about the
        # switch: it names it and says what it does not cover.
        header = script[: script.index("(async () => {")]
        assert "FORCE_SITE_MISMATCH" in header
        assert "Nothing overrides the version check" in header
        assert "architecture review 2026-09-06, P2-1" in header

    def test_the_version_check_stands_outside_the_switch(self):
        script = generate_apply_script()
        version_check = "if (newerThan(STAMP.formwork, FORMWORK_VERSION)) {"
        site_check = "if (mismatches.length && !FORCE_SITE_MISMATCH) {"
        assert version_check in script
        assert site_check in script
        assert script.index(version_check) < script.index(site_check)
        # The version refusal itself states that the switch does not cover it.
        refusal = script[script.index(version_check) : script.index("const webRes")]
        assert "FORCE_SITE_MISMATCH does not cover this" in refusal

    def test_the_web_is_read_the_way_discover_recorded_it(self):
        apply = generate_apply_script()
        discover = GENERATORS["discover"]()
        # discover records web.url as location.origin plus the server-relative
        # root, "" on the root web; apply builds hereUrl the same way.
        root_web_rule = '=== "/" ? "" :'
        assert root_web_rule in discover
        assert root_web_rule in apply
        assert "web.d.Id, and location.origin plus the web's server-relative root" in apply

    def test_every_refusal_names_the_stamp_beside_the_observed_value(self):
        script = generate_apply_script()
        assert '"web id: stamp " + STAMP.discoveryWebId + ", this web " + here.Id' in script
        assert '"web url: stamp " + STAMP.discoveryWebUrl + ", this web " + hereUrl' in script
        assert (
            '"provenance: the payload was compiled by formwork " + STAMP.formwork +\n'
            "      \", newer than this script's v\" + FORMWORK_VERSION" in script
        )

    def test_the_promoted_leg_is_the_create_body_and_cites_its_measurement(self):
        for name in ("apply", "apply-payload"):
            script = GENERATORS[name]()
            assert "PROMOTED_STATE === 1 ? { PromotedState: 1 } : {}" in script, name
            assert "created.setFields(" not in script, name
            assert "page.promoted-state.create-is-effective, measured 2026-09-06" in script, name
            assert "pageState.samples.3" in script, name
            assert "$select=CanvasContent1,Title,PromotedState" in script, name
        assert "const PROMOTED_STATE = 1;" in GENERATORS["apply-payload"]()
        assert "const PROMOTED_STATE = 0;" in GENERATORS["apply"]()

    def test_the_generator_refuses_a_promoted_state_other_than_0_or_1(self):
        with pytest.raises(ValueError, match="promoted_state must be 0 or 1, not 2"):
            generate_apply_script(promoted_state=2)

    def test_the_cli_flag_accepts_only_0_or_1(self, tmp_path, capsys):
        path = tmp_path / "payload.json"
        path.write_text(payload(), encoding="utf-8")
        assert main(["gen", "apply", str(path), "--name", "P", "--promoted-state", "1"]) == 0
        with pytest.raises(SystemExit):
            main(["gen", "apply", str(path), "--name", "P", "--promoted-state", "2"])
        err = capsys.readouterr().err
        # argparse's %r rendering of the value changed across versions
        # (3.11 unquoted, 3.12+ quoted): accept either.
        assert re.search(r"invalid choice: '?2'?", err), err


@pytest.mark.skipif(not node_available(), reason="node is not installed")
class TestTheGuardUnderNode:
    def test_a_web_id_mismatch_refuses_naming_both_values_and_creates_nothing(self, tmp_path):
        run = run_apply(tmp_path, generate_apply_script("P", payload()), web_id=OTHER_WEB_ID)
        assert len(run["errors"]) == 1
        err = run["errors"][0]
        assert err.startswith("[formwork] apply failed: provenance mismatch: ")
        assert f"web id: stamp {WEB_ID}, this web {OTHER_WEB_ID}" in err
        assert "web url" not in err  # the URL matched, so it is not listed
        assert APPLY_PAYLOAD_STAMP["discoverySha256"] in err
        assert APPLY_PAYLOAD_STAMP["discoveredAt"] in err
        assert "spec home.yaml compiled 2026-09-07T00:00:00Z" in err
        assert "Nothing was created." in err
        assert "FORCE_SITE_MISMATCH = true" in err
        assert creates(run) == []
        # Refused before the digest was even fetched: the web read is the only call.
        assert [c["url"] for c in run["calls"]] == [
            SERVER_RELATIVE_URL + "/_api/web?$select=Id,ServerRelativeUrl"
        ]

    def test_a_web_url_mismatch_refuses_too(self, tmp_path):
        run = run_apply(
            tmp_path, generate_apply_script("P", payload()), server_relative_url="/sites/Other"
        )
        assert len(run["errors"]) == 1
        assert (
            f"web url: stamp {ORIGIN}{SERVER_RELATIVE_URL}, this web {ORIGIN}/sites/Other"
            in run["errors"][0]
        )
        assert creates(run) == []

    def test_a_payload_without_a_stamp_is_refused(self, tmp_path):
        for script in (generate_apply_script("P", payload(stamp=None)), GENERATORS["apply"]()):
            run = run_apply(tmp_path, script)
            assert len(run["errors"]) == 1
            assert "carries no stamp (PAYLOAD.provenance)" in run["errors"][0]
            assert "Nothing was created." in run["errors"][0]
            assert run["calls"] == []

    def test_a_compile_stamp_that_lost_a_web_value_is_refused_not_applied(self, tmp_path):
        """FAIL-CLOSED REGRESSION. The site check used to be gated on
        ``typeof STAMP.discoveryWebId === "string"``: a compile stamp that had
        lost that one field fell into the process branch, the guard printed
        "no discovery binding (process payload): site check not applicable" (for
        a stamp still carrying discoverySha256, spec and compiledAt) and the
        payload was created on a web it was never compiled for. Every compile
        stamp must now be checked, whatever type that field has."""
        drop_id = {k: v for k, v in APPLY_PAYLOAD_STAMP.items() if k != "discoveryWebId"}
        drop_url = {k: v for k, v in APPLY_PAYLOAD_STAMP.items() if k != "discoveryWebUrl"}
        stamps = {
            "missing web id": drop_id,
            "null web id": {**APPLY_PAYLOAD_STAMP, "discoveryWebId": None},
            "numeric web id": {**APPLY_PAYLOAD_STAMP, "discoveryWebId": 12345},
            "missing web url": drop_url,
        }
        for label, stamp in stamps.items():
            run = run_apply(
                tmp_path, generate_apply_script("P", payload(stamp=stamp)), web_id=OTHER_WEB_ID
            )
            assert len(run["errors"]) == 1, label
            err = run["errors"][0]
            assert err.startswith("[formwork] apply failed: provenance mismatch: "), label
            # Still recognised as a compile stamp: the refusal names its sha256.
            assert APPLY_PAYLOAD_STAMP["discoverySha256"] in err, label
            assert "Nothing was created." in err, label
            assert creates(run) == [], label
            # The misleading skip line must not be printed for a compile stamp.
            assert run["logs"] == [], label

    def test_force_covers_a_missing_web_value_and_prints_the_difference(self, tmp_path):
        drop_id = {k: v for k, v in APPLY_PAYLOAD_STAMP.items() if k != "discoveryWebId"}
        script = forced(generate_apply_script("P", payload(stamp=drop_id)))
        run = run_apply(tmp_path, script, web_id=OTHER_WEB_ID)
        assert run["errors"] == []
        assert len(creates(run)) == 1
        assert run["warns"] == [
            "[formwork] FORCE_SITE_MISMATCH: applying despite web id: the stamp carries none"
        ]

    def test_a_stamp_naming_neither_a_discovery_nor_a_bundle_is_refused(self, tmp_path):
        """The process stamp is the ONLY shape that may skip the site check: a
        stamp that names no discovery field at all and no bundle binds the
        payload to nothing, so it is refused rather than applied unbound."""
        run = run_apply(
            tmp_path,
            generate_apply_script("P", payload(stamp={"formwork": formwork.__version__})),
            web_id=OTHER_WEB_ID,
        )
        assert len(run["errors"]) == 1
        assert "names neither a discovery document nor a bundle" in run["errors"][0]
        assert "Nothing was created." in run["errors"][0]
        assert creates(run) == []

    def test_force_site_mismatch_applies_anyway_and_prints_the_difference(self, tmp_path):
        script = forced(generate_apply_script("P", payload()))
        run = run_apply(tmp_path, script, web_id=OTHER_WEB_ID)
        assert run["errors"] == []
        assert len(creates(run)) == 1
        assert run["warns"] == [
            "[formwork] FORCE_SITE_MISMATCH: applying despite "
            f"web id: stamp {WEB_ID}, this web {OTHER_WEB_ID}"
        ]
        assert any(line.startswith("[formwork] verify OK") for line in run["logs"])

    def test_a_newer_payload_is_refused_even_under_force(self, tmp_path):
        newer = {**APPLY_PAYLOAD_STAMP, "formwork": "99.0.0"}
        for script in (
            generate_apply_script("P", payload(stamp=newer)),
            forced(generate_apply_script("P", payload(stamp=newer))),
        ):
            run = run_apply(tmp_path, script)
            assert len(run["errors"]) == 1
            err = run["errors"][0]
            assert (
                "compiled by formwork 99.0.0, newer than this script's v"
                f"{formwork.__version__}." in err
            )
            assert "FORCE_SITE_MISMATCH does not cover this" in err
            assert "Nothing was created." in err
            assert run["calls"] == []

    def test_an_older_or_equal_payload_passes_the_version_check(self, tmp_path):
        for version in ("0.1.0", "0.4.10", formwork.__version__):
            stamp = {**APPLY_PAYLOAD_STAMP, "formwork": version}
            run = run_apply(tmp_path, generate_apply_script("P", payload(stamp=stamp)))
            assert run["errors"] == [], version
            assert len(creates(run)) == 1, version
            assert run["logs"][0].startswith(f"[formwork] provenance OK: formwork {version},")
            here = f"web {WEB_ID} at {ORIGIN}{SERVER_RELATIVE_URL} matches the stamp"
            assert here in run["logs"][0]

    def test_a_process_stamp_gets_the_version_check_and_no_site_check(self, tmp_path):
        stamp = {
            "formwork": formwork.__version__,
            "bundle": "formwork-bundle.json",
            "processedAt": "2026-09-07T00:00:00Z",
        }
        # A web the stamp knows nothing about: no site check applies.
        script = generate_apply_script("P", payload(stamp=stamp))
        run = run_apply(tmp_path, script, web_id=OTHER_WEB_ID)
        assert run["errors"] == []
        assert len(creates(run)) == 1
        assert run["logs"][0] == (
            f"[formwork] provenance: formwork {formwork.__version__}, bundle formwork-bundle.json"
            " processed 2026-09-07T00:00:00Z | no discovery binding (process payload):"
            " site check not applicable"
        )
        newer = {**stamp, "formwork": "99.0.0"}
        run = run_apply(tmp_path, generate_apply_script("P", payload(stamp=newer)))
        assert len(run["errors"]) == 1
        assert "newer than this script's v" in run["errors"][0]
        assert creates(run) == []

    def test_the_golden_payload_script_applies_on_the_web_it_was_compiled_against(self, tmp_path):
        run = run_apply(tmp_path, GENERATORS["apply-payload"]())
        assert run["errors"] == []
        assert run["createdFields"] == {
            "__metadata": {"type": "SP.Publishing.SitePage"},
            "PageLayoutType": "Home",
            "PromotedState": 1,
        }
        assert any(line.startswith("[formwork] verify OK") for line in run["logs"])
        assert "| byte-exact: true | PromotedState: 1 (requested 1)" in run["logs"][1]


@pytest.mark.skipif(not node_available(), reason="node is not installed")
class TestThePromotedLegUnderNode:
    def test_promoted_state_1_rides_in_the_create_body_and_in_no_merge(self, tmp_path):
        run = run_apply(tmp_path, generate_apply_script("P", payload(), 1))
        assert run["errors"] == []
        assert run["createdFields"]["PromotedState"] == 1
        assert run["createdFields"]["PageLayoutType"] == "Home"
        merges = [c for c in run["calls"] if c["headers"].get("X-HTTP-Method") == "MERGE"]
        assert len(merges) == 1  # the canvas write, and nothing else
        assert "PromotedState" not in merges[0]["body"]
        verify = [c for c in run["calls"] if "?$select=" in c["url"]]
        assert verify[-1]["url"].endswith("?$select=CanvasContent1,Title,PromotedState")

    def test_promoted_state_0_sends_nothing_extra(self, tmp_path):
        run = run_apply(tmp_path, generate_apply_script("P", payload(), 0))
        assert run["errors"] == []
        assert run["createdFields"] == {
            "__metadata": {"type": "SP.Publishing.SitePage"},
            "PageLayoutType": "Home",
        }
        assert all("PromotedState" not in body for body in bodies(run))
        assert run["warns"] == []

    def test_a_promoted_state_that_did_not_persist_warns_and_still_verifies(self, tmp_path):
        # The Home layout with PromotedState at create is not yet a sample of
        # its own; if it reads back 0 the operator is told, and the page stands.
        run = run_apply(tmp_path, generate_apply_script("P", payload(), 1), stored_promoted=0)
        assert run["errors"] == []
        assert len(run["warns"]) == 1
        assert run["warns"][0].startswith("[formwork] PromotedState read back 0, requested 1:")
        assert "page.page-state.promoted-state" in run["warns"][0]
        assert "formwork gen findprobe" in run["warns"][0]
        assert any(line.startswith("[formwork] verify OK") for line in run["logs"])
