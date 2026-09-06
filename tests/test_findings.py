"""The findings registry (M6): FINDINGS.md as data, compile's staleness
warning, and the findprobe re-probe lane.

FINDINGS.md holds one row per measured claim. These tests read the file, the
fixtures it points at, the DSL and the two generated probes together, so a
row cannot name evidence that is not there, a claim cannot outlive its
re-probe, and the compiler cannot rely on a measurement the registry does
not record.
"""

import dataclasses
import datetime as dt
import json
import pathlib
import re
import subprocess

import pytest

from formwork.catalogue import parse_discovery
from formwork.cli import main
from formwork.dsl import MEASURED_FACTOR_SETS, compile_page
from formwork.findings import (
    COLUMNS,
    DEFAULT_MAX_AGE_DAYS,
    FACTOR_CHECK_IDS,
    REPROBE_COMMANDS,
    Finding,
    FindingsError,
    Registry,
    alias_slug,
    load_findings,
    load_findings_if_present,
    parse_findings,
    reliances,
    render_findings,
    stale_findings,
)
from formwork.generator import generate_discover_script, generate_findprobe_script
from test_dsl import DISCOVERY

ROOT = pathlib.Path(__file__).parent.parent
FINDINGS = ROOT / "FINDINGS.md"
TEMPLATES = ROOT / "src" / "formwork" / "templates"

#: The date of the two live runs every seeded row was derived from.
MEASURED = dt.date(2026, 9, 6)

#: The seeded rows, in registry order. Two are re-derived by the catalogue
#: run (`formwork gen discover`), the rest by the findprobe lane.
DISCOVER_LANE = [
    "page.components.merge-byte-exact",
    "page.layout.default-factors",
]
FINDPROBE_LANE = [
    "page.text.colon-rewrite",
    "page.text.styled-html",
    "page.emphasis.control-merge",
    "page.section.variants-merge",
    "page.page-model.draft-refuses-html",
    "page.emphasis.section-savepage",
    "page.properties.news-web-part",
    "page.properties.quick-links-web-part",
    "page.properties.image-web-part",
    "page.properties.events-web-part",
    "page.properties.hero-web-part",
    "page.properties.list-web-part",
    "page.layout.factors-8-4",
    "page.layout.factors-4-8",
    "page.bind.list-library-keys",
]

GUID = "12345678-1234-1234-1234-123456789abc"


def table(*rows: tuple[str, ...]) -> str:
    """A minimal FINDINGS.md body: the header, the rule, the given rows."""
    lines = ["| " + " | ".join(COLUMNS) + " |", "| " + " | ".join("---" for _ in COLUMNS) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "# Findings\n\n## Registry\n\n" + "\n".join(lines) + "\n"


def row(
    check_id: str = "page.text.colon-rewrite",
    measured: str = "2026-09-06",
    reprobe: str = "formwork gen findprobe",
    evidence: str = "tests/fixtures/discovery.styling.json#textControls",
) -> tuple[str, ...]:
    return (check_id, "claim", measured, "result", evidence, reprobe)


def registry_dated(day: dt.date) -> Registry:
    """The repo's registry with every row re-dated to ``day``."""
    return Registry(
        tuple(dataclasses.replace(f, measured=day) for f in load_findings(FINDINGS))
    )


def walk(document: object, dotted: str) -> object:
    node = document
    for key in dotted.split("."):
        assert isinstance(node, dict), f"{dotted}: {key} is not under a mapping"
        assert key in node, f"{dotted}: no key {key!r}"
        node = node[key]
    return node


class TestTheRepoRegistry:
    def test_seeds_every_measured_claim_in_lane_order(self):
        registry = load_findings(FINDINGS)
        assert [f.check_id for f in registry] == DISCOVER_LANE + FINDPROBE_LANE
        assert {f.measured for f in registry} == {MEASURED}
        assert [f.check_id for f in registry.lane("discover")] == DISCOVER_LANE
        assert [f.check_id for f in registry.lane("findprobe")] == FINDPROBE_LANE
        assert registry.check_ids == tuple(DISCOVER_LANE + FINDPROBE_LANE)

    def test_the_file_ends_with_its_own_canonical_rendering(self):
        # Data, not decoration: the table is the last thing in the file and
        # is byte-identical to what the parser would write back.
        text = FINDINGS.read_text(encoding="utf-8")
        registry = load_findings(FINDINGS)
        assert text.endswith(render_findings(registry))
        assert parse_findings(render_findings(registry)) == registry

    def test_every_evidence_pointer_resolves_to_a_fixture_key(self):
        for finding in load_findings(FINDINGS):
            path, _, dotted = finding.evidence.partition("#")
            assert path.startswith("tests/fixtures/"), finding.check_id
            assert dotted, finding.check_id
            document = json.loads((ROOT / path).read_text(encoding="utf-8"))
            assert walk(document, dotted), finding.check_id

    def test_every_row_is_dated_by_the_run_that_produced_it(self):
        for finding in load_findings(FINDINGS):
            path, _, dotted = finding.evidence.partition("#")
            document = json.loads((ROOT / path).read_text(encoding="utf-8"))
            node = walk(document, dotted)
            if isinstance(node, dict) and "measuredAt" in node:
                assert node["measuredAt"] == finding.measured.isoformat(), finding.check_id
            else:
                assert document["discoveredAt"][:10] == finding.measured.isoformat(), (
                    finding.check_id
                )

    def test_the_promoted_section_emphasis_row_names_the_hand_measured_mechanism(self):
        # The hand-authored fixture rows became an ordinary registry row: its
        # evidence is the fixture block, its re-probe the findprobe lane.
        finding = load_findings(FINDINGS).newest("page.emphasis.section-savepage")
        assert finding is not None
        assert finding.evidence.endswith("#styling.sectionEmphasisMechanism")
        assert finding.reprobe == "formwork gen findprobe"
        assert "SavePage" in finding.claim and "zoneId" in finding.claim
        assert finding.result == "SavePage 200; zoneEmphasis survived 2, 3; merged control 3"

    def test_the_property_rows_carry_the_measured_values(self):
        registry = load_findings(FINDINGS)
        document = json.loads(
            (ROOT / "tests/fixtures/discovery.m5.json").read_text(encoding="utf-8")
        )
        modified = {
            r["component"]: r
            for r in document["webpartProperties"]["requested"]
            if r["variant"] == "modified"
        }
        assert len(modified) == 6
        for alias, requested in modified.items():
            finding = registry.newest(f"page.properties.{alias_slug(alias)}")
            assert finding is not None, alias
            expected = (
                f"2/2 byte-exact; {requested['propertyPath']} {json.dumps(requested['oldValue'])}"
                f" to {json.dumps(requested['newValue'])} round-tripped"
            )
            assert finding.result == expected, alias

    def test_the_measured_factor_sets_all_have_a_row(self):
        registry = load_findings(FINDINGS)
        assert set(FACTOR_CHECK_IDS) == set(MEASURED_FACTOR_SETS)
        for check_id in set(FACTOR_CHECK_IDS.values()):
            assert registry.newest(check_id) is not None, check_id


class TestParsing:
    def test_round_trips_cells_with_pipes_and_backslashes(self):
        finding = Finding(
            check_id="page.text.colon-rewrite",
            claim="a | b \\ c",
            measured=dt.date(2026, 9, 6),
            result="1/1",
            evidence="tests/fixtures/discovery.styling.json#textControls",
            reprobe="formwork gen findprobe",
        )
        registry = Registry((finding,))
        text = render_findings(registry)
        assert "a \\| b \\\\ c" in text
        assert parse_findings(text) == registry

    def test_rows_keep_registry_order_and_newest_wins(self):
        registry = parse_findings(
            table(
                row(measured="2026-09-06"),
                row(measured="2026-12-01"),
                row(measured="2026-10-01"),
            )
        )
        newest = registry.newest("page.text.colon-rewrite")
        assert newest is not None and newest.measured == dt.date(2026, 12, 1)
        assert [f.measured.month for f in registry.rows("page.text.colon-rewrite")] == [9, 12, 10]
        assert registry.newest("page.text.nothing") is None

    @pytest.mark.parametrize(
        "check_id",
        [
            "Page.text.colon-rewrite",  # case
            "page.text",  # two segments
            "page.text.colon.rewrite",  # four segments
            "page.text.colon_rewrite",  # underscore
            "page.text.-colon",  # leading hyphen
            "page..colon",  # empty scope
            "web.text.colon-rewrite",  # unknown surface
        ],
    )
    def test_check_id_grammar_is_validated_on_load(self, check_id):
        with pytest.raises(FindingsError, match=re.escape(check_id)):
            parse_findings(table(row(check_id=check_id)))

    @pytest.mark.parametrize("measured", ["2026-9-6", "06/09/2026", "yesterday", "2026-13-01"])
    def test_dates_are_iso_and_validated_on_load(self, measured):
        with pytest.raises(FindingsError, match=re.escape(measured)):
            parse_findings(table(row(measured=measured)))

    def test_reprobe_must_be_a_generator_command(self):
        with pytest.raises(FindingsError, match="formwork gen discover"):
            parse_findings(table(row(reprobe="run it by hand")))
        assert REPROBE_COMMANDS == ("formwork gen discover", "formwork gen findprobe")

    def test_evidence_must_point_into_the_fixtures(self):
        with pytest.raises(FindingsError, match="tests/fixtures/"):
            parse_findings(table(row(evidence="see the README")))

    def test_the_header_and_cell_count_are_checked(self):
        with pytest.raises(FindingsError, match="check-id"):
            parse_findings("| id | claim |\n| --- | --- |\n| a | b |\n")
        with pytest.raises(FindingsError, match="6 cells"):
            parse_findings(table(("page.text.colon-rewrite", "claim", "2026-09-06")))
        with pytest.raises(FindingsError, match="empty"):
            parse_findings(table(("page.text.colon-rewrite", "", "2026-09-06", "r", "e", "x")))

    def test_a_duplicate_row_is_refused(self):
        with pytest.raises(FindingsError, match="twice"):
            parse_findings(table(row(), row()))

    def test_a_file_without_the_table_is_refused(self):
        with pytest.raises(FindingsError, match="no registry table"):
            parse_findings("# Findings\n\nnothing here\n")

    def test_a_missing_file_is_none_only_on_the_lenient_path(self, tmp_path):
        assert load_findings_if_present(tmp_path / "FINDINGS.md") is None
        with pytest.raises(FileNotFoundError):
            load_findings(tmp_path / "FINDINGS.md")

    def test_alias_slug(self):
        assert alias_slug("NewsWebPart") == "news-web-part"
        assert alias_slug("QuickLinksWebPart") == "quick-links-web-part"
        assert alias_slug("ListWebPart") == "list-web-part"
        assert re.fullmatch(r"[a-z][a-z0-9-]*", alias_slug("PageContextWebPart2"))


#: A spec that relies on every kind of measurement the registry records.
RELYING_SPEC = {
    "page": "Relying",
    "sections": [
        {
            "type": "two",
            "parts": [
                {"component": "NewsWebPart", "properties": {"layoutId": "List"}, "emphasis": 2},
                {
                    "component": "Document library",
                    "column": 2,
                    "bind": {"listId": GUID, "listUrl": "Shared Documents"},
                },
            ],
        },
        {"columns": [8, 4], "parts": [{"text": "<p>plain</p>"}]},
        {"columns": [4, 8], "parts": [{"text": '<p style="color:red;">styled</p>'}]},
    ],
}

#: A spec that compiles against test_dsl.DISCOVERY with no text measurement.
SIMPLE_SPEC = {
    "page": "Simple",
    "sections": [
        {"type": "two", "parts": [{"component": "NewsWebPart", "emphasis": 2}]},
        {"columns": [8, 4], "parts": [{"component": "NewsWebPart"}]},
    ],
}


class TestReliances:
    def test_a_spec_relies_on_the_rows_its_parts_and_sections_use(self):
        registry = load_findings(FINDINGS)
        found = reliances(RELYING_SPEC, parse_discovery(DISCOVERY), registry)
        by_id: dict[str, list[str]] = {}
        for reliance in found:
            by_id.setdefault(reliance.check_id, []).append(reliance.where)
        assert by_id == {
            "page.layout.default-factors": ["section 1"],
            "page.components.merge-byte-exact": ["part 1", "part 2"],
            "page.properties.news-web-part": ["part 1"],
            "page.emphasis.control-merge": ["part 1"],
            "page.bind.list-library-keys": ["part 2"],
            "page.layout.factors-8-4": ["section 2"],
            "page.text.colon-rewrite": ["part 3", "part 4"],
            "page.text.styled-html": ["part 4"],
            "page.layout.factors-4-8": ["section 3"],
        }

    def test_properties_on_a_part_without_its_own_row_rely_on_the_newest_properties_row(self):
        registry = load_findings(FINDINGS)
        spec = {
            "page": "P",
            "sections": [
                {"parts": [{"component": "Document library", "properties": {"x": 1}}]}
            ],
        }
        ids = {r.check_id for r in reliances(spec, parse_discovery(DISCOVERY), registry)}
        assert "page.properties.document-library-web-part" not in ids
        assert ids == {"page.components.merge-byte-exact", "page.properties.news-web-part",
                       "page.layout.default-factors"}

    def test_a_relied_on_claim_with_no_row_is_reported_as_unrecorded(self):
        without_bind = Registry(
            tuple(f for f in load_findings(FINDINGS) if not f.check_id.startswith("page.bind."))
        )
        spec = {
            "page": "P",
            "sections": [
                {
                    "parts": [
                        {
                            "component": "Document library",
                            "bind": {"listId": GUID, "listUrl": "Shared Documents"},
                        }
                    ]
                }
            ],
        }
        stale = stale_findings(
            spec, parse_discovery(DISCOVERY), without_bind, max_age_days=90, today=MEASURED
        )
        assert [s.check_id for s in stale] == ["page.bind.list-library-keys"]
        assert stale[0].finding is None
        message = stale[0].message(90)
        assert message.startswith("page.bind.list-library-keys: no row in FINDINGS.md")
        assert "part 1" in message and "formwork gen findprobe" in message


class TestStaleness:
    @pytest.mark.parametrize(("age", "warns"), [(89, False), (90, False), (91, True)])
    def test_the_boundary_is_strictly_older_than_max_age(self, age, warns):
        registry = registry_dated(MEASURED)
        today = MEASURED + dt.timedelta(days=age)
        stale = stale_findings(
            SIMPLE_SPEC, parse_discovery(DISCOVERY), registry, max_age_days=90, today=today
        )
        assert bool(stale) == warns
        if warns:
            assert [s.check_id for s in stale] == [
                "page.layout.default-factors",
                "page.components.merge-byte-exact",
                "page.emphasis.control-merge",
                "page.layout.factors-8-4",
            ]
            for entry in stale:
                assert entry.age_days == 91
                message = entry.message(90)
                assert message.startswith(f"{entry.check_id}: measured {MEASURED.isoformat()},")
                assert "91 days ago" in message
                assert "--findings-max-age 90" in message
                assert entry.finding is not None
                assert message.endswith(f"re-probe: {entry.finding.reprobe}")

    def test_the_default_max_age_is_ninety_days(self):
        assert DEFAULT_MAX_AGE_DAYS == 90

    def test_the_newest_row_for_a_check_id_is_the_one_judged(self):
        old = registry_dated(MEASURED - dt.timedelta(days=400))
        fresh = registry_dated(MEASURED)
        both = Registry(old.findings + fresh.findings)
        stale = stale_findings(
            SIMPLE_SPEC, parse_discovery(DISCOVERY), both, max_age_days=90, today=MEASURED
        )
        assert stale == []

    def test_a_stale_entry_groups_every_location_that_relies_on_it(self):
        registry = registry_dated(MEASURED - dt.timedelta(days=100))
        stale = stale_findings(
            RELYING_SPEC, parse_discovery(DISCOVERY), registry, max_age_days=90, today=MEASURED
        )
        by_id = {s.check_id: s for s in stale}
        assert by_id["page.components.merge-byte-exact"].where == ("part 1", "part 2")
        assert "relied on by part 1, part 2;" in by_id["page.components.merge-byte-exact"].message(
            90
        )


class TestCompileCommand:
    def write_inputs(self, tmp_path: pathlib.Path, spec: dict) -> tuple[str, str, str]:
        discovery_path = tmp_path / "discovery.json"
        discovery_path.write_text(json.dumps(DISCOVERY), encoding="utf-8")
        spec_path = tmp_path / "page.json"  # YAML is a superset of JSON
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        return str(spec_path), str(discovery_path), str(tmp_path / "payload.json")

    def test_warns_on_stderr_and_still_writes_the_payload(self, tmp_path, capsys):
        spec, discovery, out = self.write_inputs(tmp_path, SIMPLE_SPEC)
        findings = tmp_path / "old.md"
        findings.write_text(
            render_findings(registry_dated(dt.date.today() - dt.timedelta(days=200))),
            encoding="utf-8",
        )
        rc = main(["compile", spec, discovery, "--out", out, "--findings", str(findings)])
        assert rc == 0
        captured = capsys.readouterr()
        assert json.loads(pathlib.Path(out).read_text(encoding="utf-8"))["title"] == "Simple"
        assert "payload written:" in captured.out
        warnings = captured.err.splitlines()
        assert warnings and all(line.startswith("warning: ") for line in warnings)
        assert any("page.components.merge-byte-exact: measured" in line for line in warnings)
        assert any(line.endswith("re-probe: formwork gen discover") for line in warnings)
        assert any(line.endswith("re-probe: formwork gen findprobe") for line in warnings)
        assert all("200 days ago (--findings-max-age 90)" in line for line in warnings)

    def test_max_age_is_configurable(self, tmp_path, capsys):
        spec, discovery, out = self.write_inputs(tmp_path, SIMPLE_SPEC)
        findings = tmp_path / "old.md"
        findings.write_text(
            render_findings(registry_dated(dt.date.today() - dt.timedelta(days=200))),
            encoding="utf-8",
        )
        rc = main(
            ["compile", spec, discovery, "--out", out, "--findings", str(findings),
             "--findings-max-age", "365"]
        )
        assert rc == 0
        assert capsys.readouterr().err == ""

    def test_the_default_registry_is_the_one_in_the_working_directory(
        self, tmp_path, monkeypatch, capsys
    ):
        spec, discovery, out = self.write_inputs(tmp_path, SIMPLE_SPEC)
        (tmp_path / "FINDINGS.md").write_text(
            render_findings(registry_dated(dt.date.today() - dt.timedelta(days=200))),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        assert main(["compile", spec, discovery, "--out", out]) == 0
        assert "warning: page.components.merge-byte-exact" in capsys.readouterr().err

    def test_without_a_registry_the_dsl_is_unchanged(self, tmp_path, monkeypatch, capsys):
        # No FINDINGS.md in the working directory: no warning, the same
        # payload and the same part lines as before the registry existed.
        spec, discovery, out = self.write_inputs(tmp_path, SIMPLE_SPEC)
        monkeypatch.chdir(tmp_path)
        assert main(["compile", spec, discovery, "--out", out]) == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        expected = compile_page(SIMPLE_SPEC, parse_discovery(DISCOVERY))
        payload = json.loads(pathlib.Path(out).read_text(encoding="utf-8"))
        assert payload["canvas"] == expected.canvas
        lines = captured.out.splitlines()
        assert lines[1:] == [
            "  section 1, column 1: NewsWebPart (News, zoneEmphasis 2)",
            "  section 2, column 1: NewsWebPart (News)",
        ]

    def test_an_explicit_missing_registry_is_an_error(self, tmp_path, capsys):
        spec, discovery, out = self.write_inputs(tmp_path, SIMPLE_SPEC)
        rc = main(
            ["compile", spec, discovery, "--out", out, "--findings", str(tmp_path / "none.md")]
        )
        assert rc == 1
        captured = capsys.readouterr()
        assert captured.err.startswith("error: no findings registry at ")
        assert captured.err.count("\n") == 1

    def test_a_malformed_registry_is_one_error_line(self, tmp_path, capsys):
        spec, discovery, out = self.write_inputs(tmp_path, SIMPLE_SPEC)
        findings = tmp_path / "bad.md"
        findings.write_text(table(row(check_id="Bad.id.here")), encoding="utf-8")
        rc = main(["compile", spec, discovery, "--out", out, "--findings", str(findings)])
        assert rc == 1
        captured = capsys.readouterr()
        assert captured.err.startswith("error: ")
        assert "Bad.id.here" in captured.err
        assert captured.err.count("\n") == 1


def node_available() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


class TestFindprobe:
    """The re-probe lane. Its golden is pinned in test_generator.py under
    ``findprobe``; here the shape and the registry literal."""

    def test_the_embedded_registry_decodes_to_the_rows(self):
        registry = load_findings(FINDINGS)
        script = generate_findprobe_script(registry)
        literal = re.search(r"  const FINDINGS = (\[.*?\n  \]);\n", script, re.S)
        assert literal, "no FINDINGS literal"
        assert json.loads(literal.group(1)) == [
            {
                "checkId": f.check_id,
                "lane": f.lane,
                "measured": f.measured.isoformat(),
                "result": f.result,
            }
            for f in registry
        ]

    def test_it_reuses_the_discover_probe_s_setup_and_legs_verbatim(self):
        # The measurement legs are shared partials: discover includes them
        # between its catalogue spread and its download, findprobe between
        # its registry literal and its SavePage leg. Same bytes in both.
        setup = (TEMPLATES / "_probe_setup.js.j2").read_text(encoding="utf-8")
        legs = (TEMPLATES / "_probe_legs.js.j2").read_text(encoding="utf-8")
        discover = generate_discover_script()
        findprobe = generate_findprobe_script(load_findings(FINDINGS))
        for partial in (setup, legs):
            # One Jinja comment names the partial; everything after it is
            # plain JavaScript that both scripts carry byte for byte.
            header, body = partial.split("\n", 1)
            assert header.startswith("{#") and header.endswith("#}")
            assert "{%" not in body and "{{" not in body and "{#" not in body
            assert body in discover
            assert body in findprobe
        # findprobe does not spread the catalogue.
        assert "for (let i = 0; i < placeable.length; i++)" in discover
        assert "for (let i = 0; i < placeable.length; i++)" not in findprobe
        assert "formwork-discovery.json" not in findprobe

    def test_every_findprobe_row_has_a_verdict_and_every_verdict_a_row(self):
        registry = load_findings(FINDINGS)
        script = generate_findprobe_script(registry)
        literal = set(re.findall(r'verdicts\["([a-z0-9.-]+)"\]', script))
        assert literal < set(FINDPROBE_LANE)
        # The property verdicts are keyed by alias slug at run time; the
        # sampled aliases are the six PROPERTY_SAMPLES components.
        start = script.index("const PROPERTY_SAMPLES = [")
        samples = script[start : script.index("];", start)]
        aliases = re.findall(r'component: "(\w+)"', samples)
        computed = literal | {f"page.properties.{alias_slug(a)}" for a in aliases}
        assert computed == set(FINDPROBE_LANE)
        assert 'verdicts["page.properties." + slug(sample.component)]' in script

    def test_the_savepage_leg_sends_the_measured_body_shape_and_recycles(self):
        script = generate_findprobe_script(load_findings(FINDINGS))
        assert 'API("sitepages/pages(" + savePage.id + ")/SavePage")' in script
        assert '__metadata: { type: "SP.Publishing.SitePage" },' in script
        assert "CanvasContent1: JSON.stringify(established)," in script
        assert 'LayoutWebpartsContent: "[]",' in script
        assert 'BannerImageUrl: "/_layouts/15/images/sitepagethumbnail.png",' in script
        assert "isFromSectionTemplate: false, addedFromPersistedData: false," in script
        assert "zoneId: zoneId, sectionFactor: 12, layoutIndex: 1" in script
        assert "crypto.randomUUID()" in script
        # Established by SavePage, then a control item-merged into section 2.
        assert 'savePageControl(SAVEPAGE_IDS[2], 2, zoneIds[1], 2, 3)' in script
        assert '"X-HTTP-Method": "MERGE", "If-Match": etag' in script
        # Non-fatal, recorded, recycled before the download.
        assert "} catch (err) {\n    sectionEmphasis.reason = bounded(err);" in script
        savepage = script.index(")/SavePage\")")
        legs_recycle = script.index('")/recycle"')
        assert legs_recycle < savepage
        second_recycle = script.index('")/recycle"', savepage)
        assert savepage < second_recycle < script.index("URL.createObjectURL")
        assert 'schema: "formwork.findprobe/v1"' in script
        assert "formwork-findprobe.json" in script
        assert "console.table(report)" in script

    @pytest.mark.skipif(not node_available(), reason="node is not installed")
    def test_script_is_syntactically_valid_javascript(self, tmp_path):
        path = tmp_path / "findprobe.js"
        path.write_text(generate_findprobe_script(load_findings(FINDINGS)), encoding="utf-8")
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, check=False)
        assert result.returncode == 0, result.stderr.decode()

    def test_gen_findprobe_prints_the_script(self, capsys):
        assert main(["gen", "findprobe", "--findings", str(FINDINGS)]) == 0
        out = capsys.readouterr().out
        assert out == generate_findprobe_script(load_findings(FINDINGS)) + "\n"

    def test_gen_findprobe_without_a_registry_is_an_error(self, tmp_path, capsys):
        rc = main(["gen", "findprobe", "--findings", str(tmp_path / "none.md")])
        assert rc == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("error: no findings registry at ")
