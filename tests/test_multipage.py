"""Multi-page compilation (M7): many specs, one discovery document.

``formwork compile-pages <dir-or-glob> <discovery>`` compiles every ``*.yaml``
spec against ONE discovery document and writes one payload per spec plus a
manifest carrying the shared provenance header. These tests pin the four
properties the README promises: per-page isolation (one bad spec fails
alone), the shared discovery, the provenance header, and the ``navigation``
refusal; the last tests compile the README's own sample so the
documentation cannot drift from the command.
"""

import datetime as dt
import hashlib
import json
import pathlib
import re

import pytest
import yaml

import formwork
from formwork.catalogue import parse_discovery
from formwork.cli import main
from formwork.dsl import UNENCODABLE_PAGE_KEYS, UNMEASURED_PAGE_KEYS, DslError, compile_page
from formwork.findings import Finding, Registry, render_findings
from formwork.multipage import (
    MANIFEST_NAME,
    MANIFEST_SCHEMA,
    PAYLOAD_SCHEMA,
    PageOptions,
    compile_pages,
    find_specs,
    provenance,
)
from test_dsl import DISCOVERY, DISCOVERY_WITH_TEXT
from test_findings import registry_dated

ROOT = pathlib.Path(__file__).parent.parent
README = ROOT / "README.md"

HOME = """\
page: Team home
sections:
  - type: two-thirds
    parts:
      - component: NewsWebPart
      - text: |
          ## Welcome

          See the [news](/sites/T/SitePages/Team-news.aspx).
        column: 2
"""

NEWS = """\
page: Team news
sections:
  - type: one
    parts:
      - component: NewsWebPart
        properties: {layoutId: "List"}
"""

BROKEN = """\
page: Broken
sections:
  - type: one
    parts:
      - component: NoSuchWebPart
"""

NAVIGATION = """\
page: Navigated
navigation: {quickLaunch: true}
sections:
  - type: one
    parts:
      - component: NewsWebPart
"""


def write_discovery(tmp_path: pathlib.Path) -> pathlib.Path:
    # DISCOVERY_WITH_TEXT: the HOME sample spec has a text part, and
    # compile_page rightly refuses text against a document without the
    # persisted text-control measurement (test_dsl pins that refusal).
    path = tmp_path / "formwork-discovery.json"
    path.write_text(json.dumps(DISCOVERY_WITH_TEXT), encoding="utf-8")
    return path


def write_specs(tmp_path: pathlib.Path, **specs: str) -> pathlib.Path:
    pages = tmp_path / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    for stem, text in specs.items():
        (pages / f"{stem}.yaml").write_text(text, encoding="utf-8")
    return pages


class TestFindSpecs:
    def test_a_directory_means_its_yaml_files_in_name_order(self, tmp_path):
        pages = write_specs(tmp_path, news=NEWS, home=HOME)
        (pages / "notes.txt").write_text("not a spec", encoding="utf-8")
        (pages / "nested").mkdir()
        (pages / "nested" / "deep.yaml").write_text(HOME, encoding="utf-8")
        assert [p.name for p in find_specs(str(pages))] == ["home.yaml", "news.yaml"]

    def test_a_glob_is_expanded_and_sorted(self, tmp_path):
        pages = write_specs(tmp_path, news=NEWS, home=HOME)
        found = find_specs(str(pages / "*.yaml"))
        assert [p.name for p in found] == ["home.yaml", "news.yaml"]

    def test_nothing_found_is_an_empty_list(self, tmp_path):
        assert find_specs(str(tmp_path / "none" / "*.yaml")) == []


class TestProvenance:
    def test_it_hashes_the_discovery_bytes_and_names_the_web(self):
        text = json.dumps(DISCOVERY)
        header = provenance(text, DISCOVERY)
        assert header.formwork == formwork.__version__
        assert header.discovery_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert header.discovery_web_id == DISCOVERY["web"]["id"]
        assert header.discovery_web_url == DISCOVERY["web"]["url"]
        assert header.discovered_at == ""  # the synthetic document has no discoveredAt
        assert header.as_dict() == {
            "formwork": formwork.__version__,
            "discoverySha256": header.discovery_sha256,
            "discoveryWebId": DISCOVERY["web"]["id"],
            "discoveryWebUrl": DISCOVERY["web"]["url"],
            "discoveredAt": "",
        }

    def test_a_document_without_a_web_block_still_has_a_header(self):
        document = {"schema": "formwork.discovery/v1", "components": []}
        header = provenance(json.dumps(document), document)
        assert header.discovery_web_id == ""
        assert header.discovery_web_url == ""
        assert len(header.discovery_sha256) == 64


class TestCompilePages:
    def test_one_payload_per_spec_and_a_manifest(self, tmp_path):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, home=HOME, news=NEWS)
        out = tmp_path / "build"
        manifest = compile_pages(find_specs(str(pages)), discovery, out)
        assert manifest.ok
        assert [r.stem for r in manifest.results] == ["home", "news"]
        assert sorted(p.name for p in out.iterdir()) == [
            MANIFEST_NAME,
            "home.payload.json",
            "news.payload.json",
        ]
        written = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert written["schema"] == MANIFEST_SCHEMA
        assert written["compiledWith"] == manifest.provenance.as_dict()
        assert [p["spec"] for p in written["pages"]] == ["home.yaml", "news.yaml"]
        assert all(p["ok"] and p["error"] is None for p in written["pages"])

    def test_each_payload_is_what_compile_would_have_written(self, tmp_path):
        # Same schema, same canvas: apply consumes the two interchangeably.
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, home=HOME)
        out = tmp_path / "build"
        compile_pages(find_specs(str(pages)), discovery, out)
        payload = json.loads((out / "home.payload.json").read_text(encoding="utf-8"))
        assert payload["schema"] == PAYLOAD_SCHEMA == "formwork.payload/v1"
        assert payload["sourcePage"] == "(compiled from spec home.yaml)"
        assert payload["unresolved"] == []
        expected = compile_page(yaml.safe_load(HOME), parse_discovery(DISCOVERY_WITH_TEXT))
        assert payload["title"] == expected.title == "Team home"
        assert payload["canvas"] == expected.canvas
        # No link resolution: the cross-page href is carried as written.
        assert "/sites/T/SitePages/Team-news.aspx" in payload["canvas"]

    def test_one_bad_spec_fails_alone(self, tmp_path):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, broken=BROKEN, home=HOME, news=NEWS)
        out = tmp_path / "build"
        manifest = compile_pages(find_specs(str(pages)), discovery, out)
        assert not manifest.ok
        by_stem = {r.stem: r for r in manifest.results}
        assert by_stem["home"].ok and by_stem["news"].ok
        assert not by_stem["broken"].ok
        assert "NoSuchWebPart" in (by_stem["broken"].error or "")
        assert by_stem["broken"].payload_path is None
        assert not (out / "broken.payload.json").exists()
        assert (out / "home.payload.json").exists()
        assert (out / "news.payload.json").exists()
        written = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
        failed = [p for p in written["pages"] if not p["ok"]]
        assert [p["spec"] for p in failed] == ["broken.yaml"]
        assert failed[0]["payload"] is None

    def test_unreadable_yaml_fails_alone_too(self, tmp_path):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, home=HOME)
        (pages / "bad.yaml").write_text("page: [unclosed\n", encoding="utf-8")
        (pages / "list.yaml").write_text("- not\n- a mapping\n", encoding="utf-8")
        manifest = compile_pages(find_specs(str(pages)), discovery, tmp_path / "build")
        by_stem = {r.stem: r for r in manifest.results}
        assert by_stem["home"].ok
        assert not by_stem["bad"].ok and by_stem["bad"].error
        assert not by_stem["list"].ok
        assert "mapping" in (by_stem["list"].error or "")

    def test_every_page_shares_the_one_discovery(self, tmp_path):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, home=HOME, news=NEWS)
        manifest = compile_pages(find_specs(str(pages)), discovery, tmp_path / "build")
        text = discovery.read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert manifest.provenance.discovery_sha256 == digest
        written = json.loads((tmp_path / "build" / MANIFEST_NAME).read_text(encoding="utf-8"))
        # One header for the run, not one per page.
        assert "compiledWith" in written
        assert all("compiledWith" not in p for p in written["pages"])
        assert written["compiledWith"]["discoveryWebId"] == DISCOVERY["web"]["id"]
        assert written["compiledWith"]["formwork"] == formwork.__version__

    def test_navigation_is_refused_per_page_with_the_cited_reason(self, tmp_path):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, home=HOME, nav=NAVIGATION)
        manifest = compile_pages(find_specs(str(pages)), discovery, tmp_path / "build")
        by_stem = {r.stem: r for r in manifest.results}
        assert by_stem["home"].ok
        assert not by_stem["nav"].ok
        error = by_stem["nav"].error or ""
        assert error.startswith("spec: navigation is unmeasured")
        assert "page.navigation." in error
        assert "formwork gen discover" in error

    def test_two_specs_with_one_stem_refuse_before_writing(self, tmp_path):
        discovery = write_discovery(tmp_path)
        a = write_specs(tmp_path / "a", home=HOME)
        b = write_specs(tmp_path / "b", home=NEWS)
        with pytest.raises(ValueError, match=r"share the payload name home\.payload\.json"):
            compile_pages([a / "home.yaml", b / "home.yaml"], discovery, tmp_path / "build")
        assert not (tmp_path / "build").exists()

    def test_case_variant_stems_refuse_before_writing(self, tmp_path):
        # Windows and default macOS filesystems are case-insensitive, so
        # Home.payload.json and home.payload.json are ONE file there: a
        # case-only difference is a collision too, and an exact-match guard
        # let the second spec silently replace the first spec's payload
        # while the manifest reported two ok rows (swarm review 2026-09-11).
        discovery = write_discovery(tmp_path)
        a = write_specs(tmp_path / "a", Home=HOME)
        b = write_specs(tmp_path / "b", home=NEWS)
        with pytest.raises(ValueError) as raised:
            compile_pages(
                [a / "pages" / "Home.yaml", b / "pages" / "home.yaml"],
                discovery,
                tmp_path / "build",
            )
        message = str(raised.value)
        assert "share the payload name home.payload.json" in message
        assert "case-only difference from Home.yaml" in message
        assert not (tmp_path / "build").exists()

    def test_case_variant_stems_in_one_glob_refuse_too(self, tmp_path):
        # The same hole through the command's own discovery path: a glob
        # spanning two directories whose stems differ only by case.
        discovery = write_discovery(tmp_path)
        write_specs(tmp_path / "a", Home=HOME)
        write_specs(tmp_path / "b", home=NEWS)
        specs = find_specs(str(tmp_path / "*" / "pages" / "*.yaml"))
        assert [s.name for s in specs] == ["Home.yaml", "home.yaml"]
        with pytest.raises(ValueError, match=r"share the payload name home\.payload\.json"):
            compile_pages(specs, discovery, tmp_path / "build")
        assert not (tmp_path / "build").exists()

    def test_the_manifest_records_stale_findings_per_page(self, tmp_path):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, home=HOME)
        old = dt.date.today() - dt.timedelta(days=400)
        registry = Registry(
            (
                Finding(
                    "page.components.merge-byte-exact",
                    "claim",
                    old,
                    "result",
                    "tests/fixtures/discovery.styling.json#textControls",
                    "formwork gen discover",
                ),
            )
        )
        manifest = compile_pages(
            find_specs(str(pages)),
            discovery,
            tmp_path / "build",
            PageOptions(registry=registry),
        )
        (result,) = manifest.results
        assert result.ok
        assert any(
            w.startswith("page.components.merge-byte-exact: measured") for w in result.warnings
        )
        assert any(w.startswith("page.text.colon-rewrite: no row") for w in result.warnings)
        written = json.loads((tmp_path / "build" / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert written["pages"][0]["warnings"] == list(result.warnings)


class TestNavigationRefusal:
    def test_navigation_is_an_unmeasured_key_not_an_unencodable_one(self):
        # UNENCODABLE keys carry a measured reason (a 2026-09-06 citation);
        # UNMEASURED keys name the lane that would measure them.
        assert "navigation" in UNMEASURED_PAGE_KEYS
        assert "navigation" not in UNENCODABLE_PAGE_KEYS
        reason = UNMEASURED_PAGE_KEYS["navigation"]
        assert "page.navigation." in reason
        assert "formwork gen discover" in reason
        assert "FINDINGS.md" in reason

    def test_compile_refuses_at_parse(self):
        spec = {"page": "T", "navigation": {"quickLaunch": True}, "sections": [{"parts": []}]}
        with pytest.raises(DslError, match=r"^spec: navigation is unmeasured"):
            compile_page(spec, parse_discovery(DISCOVERY))

    def test_the_readme_names_the_key_in_the_refusal_list(self):
        readme = README.read_text(encoding="utf-8")
        section = re.search(r"^### What compile refuses\n(.*?)(?=^## )", readme, re.S | re.M)
        assert section, "README has no '### What compile refuses' section"
        assert "`navigation`" in section.group(1)


class TestCompilePagesCommand:
    def test_the_command_writes_the_build_and_prints_one_line_per_page(
        self, tmp_path, capsys
    ):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, home=HOME, news=NEWS)
        out = tmp_path / "build"
        rc = main(["compile-pages", str(pages), str(discovery), "--out-dir", str(out)])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        lines = captured.out.splitlines()
        assert lines[0].startswith(f"compiled 2 of 2 pages against {discovery} (web ")
        assert lines[0].endswith(f"): manifest {out / MANIFEST_NAME}")
        assert lines[1:] == [
            "  ok    home.yaml -> home.payload.json (Team home, 2 parts)",
            "  ok    news.yaml -> news.payload.json (Team news, 1 part)",
        ]

    def test_a_failing_page_is_reported_and_the_rest_still_build(self, tmp_path, capsys):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, broken=BROKEN, home=HOME)
        out = tmp_path / "build"
        rc = main(["compile-pages", str(pages), str(discovery), "--out-dir", str(out)])
        assert rc == 1
        captured = capsys.readouterr()
        lines = captured.out.splitlines()
        assert lines[0].startswith(f"compiled 1 of 2 pages against {discovery} (web ")
        assert lines[1].startswith("  FAIL  broken.yaml: ")
        assert "NoSuchWebPart" in lines[1]
        assert lines[2] == "  ok    home.yaml -> home.payload.json (Team home, 2 parts)"
        assert (out / "home.payload.json").exists()
        assert captured.err == ""

    def test_a_glob_argument_works_the_same(self, tmp_path, capsys):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, home=HOME, news=NEWS)
        out = tmp_path / "build"
        rc = main(
            ["compile-pages", str(pages / "*.yaml"), str(discovery), "--out-dir", str(out)]
        )
        assert rc == 0
        assert (out / MANIFEST_NAME).exists()

    def test_no_specs_is_one_error_line(self, tmp_path, capsys):
        discovery = write_discovery(tmp_path)
        empty = tmp_path / "empty"
        empty.mkdir()
        build = tmp_path / "b"
        rc = main(["compile-pages", str(empty), str(discovery), "--out-dir", str(build)])
        assert rc == 1
        captured = capsys.readouterr()
        assert captured.err.startswith("error: no *.yaml specs under ")
        assert captured.err.count("\n") == 1
        assert not build.exists()

    def test_stale_findings_are_warned_per_page_on_stderr(self, tmp_path, capsys):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, home=HOME)
        findings = tmp_path / "FINDINGS.md"
        findings.write_text(
            render_findings(registry_dated(dt.date.today() - dt.timedelta(days=200))),
            encoding="utf-8",
        )
        rc = main(
            [
                "compile-pages",
                str(pages),
                str(discovery),
                "--out-dir",
                str(tmp_path / "b"),
                "--findings",
                str(findings),
            ]
        )
        assert rc == 0
        err = capsys.readouterr().err
        # walk order: section factors first, then the part rows.
        assert err.startswith("warning: home.yaml: page.layout.factors-8-4: measured ")


class TestReadmeSample:
    """The README's Multi-page section shows two specs, the command and its
    output. Compile those very specs and compare, so the sample cannot drift."""

    @staticmethod
    def section() -> str:
        readme = README.read_text(encoding="utf-8")
        match = re.search(r"^## Multi-page\n(.*?)(?=^## )", readme, re.S | re.M)
        assert match, "README has no '## Multi-page' section"
        return match.group(1)

    def test_the_sample_specs_compile_to_the_printed_lines(self, tmp_path, capsys):
        body = self.section()
        specs = re.findall(r"```yaml\n# pages/([\w-]+\.yaml)\n(.*?)```", body, re.S)
        assert len(specs) == 2, "the README sample is two specs under pages/"
        pages = tmp_path / "pages"
        pages.mkdir()
        for name, text in specs:
            (pages / name).write_text(text, encoding="utf-8")
        discovery = write_discovery(tmp_path)
        out = tmp_path / "build"
        rc = main(["compile-pages", str(pages), str(discovery), "--out-dir", str(out)])
        assert rc == 0
        printed = capsys.readouterr().out.splitlines()
        shown = re.search(r"```text\n(.*?)```", body, re.S)
        assert shown, "the README sample shows the command's output"
        expected = shown.group(1).splitlines()
        # The first line carries the paths and the discovery hash of the
        # reader's own run; the per-page lines are exact.
        assert expected[0].startswith("compiled 2 of 2 pages against ")
        assert printed[1:] == expected[1:]

    def test_the_sample_documents_what_multi_page_does_not_do(self):
        body = self.section()
        for promise in (
            "one payload per spec",
            "no link resolution",
            "no transaction",
            "`navigation`",
        ):
            assert promise in body, promise
