"""Payload provenance (M8): the stamp compile writes and apply checks.

The stamp binds a payload to the discovery document (and so the web) it was
compiled against, and to the formwork that compiled it; what the apply
paste-in does with it is pinned in tests/test_apply_guard.py. Here: the hash
is over the file's exact bytes, the web id and URL are carried, the version
is ``formwork.__version__``, every producer (compile, compile-pages, process)
writes a stamp, and compile prints it on the line after "payload written".
"""

import hashlib
import json
import pathlib
import re

import formwork
from formwork import multipage
from formwork.cli import main
from formwork.multipage import compile_pages, find_specs
from formwork.provenance import (
    PAYLOAD_KEY,
    PayloadStamp,
    Provenance,
    payload_stamp,
    process_stamp,
    provenance,
)
from test_dsl import DISCOVERY, DISCOVERY_WITH_TEXT
from test_multipage import HOME, write_discovery, write_specs

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
#: The stamp clock: ISO 8601, UTC, whole seconds, Z suffix.
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
#: One discovery document, two byte forms.
PRETTY = json.dumps(DISCOVERY, indent=2).encode("utf-8")
COMPACT = json.dumps(DISCOVERY).encode("utf-8")
DISCOVERED_AT = "2026-09-06T22:15:54.234Z"
DATED = {**DISCOVERY, "discoveredAt": DISCOVERED_AT}


class TestTheHeader:
    def test_the_hash_is_over_the_exact_bytes_and_is_stable(self):
        first = provenance(PRETTY, json.loads(PRETTY))
        assert first == provenance(PRETTY, json.loads(PRETTY))
        assert first.discovery_sha256 == hashlib.sha256(PRETTY).hexdigest()
        # The same document in other bytes (whitespace) is another stamp:
        # the hash names the file, not the parse.
        other = provenance(COMPACT, DISCOVERY)
        assert other.discovery_sha256 == hashlib.sha256(COMPACT).hexdigest()
        assert other.discovery_sha256 != first.discovery_sha256

    def test_a_str_is_hashed_as_its_utf8_bytes(self):
        # M7's signature took text; the same text gives the digest of its
        # bytes, so a caller still passing text agrees with read_bytes.
        as_text = provenance(PRETTY.decode("utf-8"), DISCOVERY)
        assert as_text.discovery_sha256 == provenance(PRETTY, DISCOVERY).discovery_sha256

    def test_it_carries_the_web_id_url_timestamp_and_the_formwork_version(self):
        header = provenance(PRETTY, DATED)
        assert header.discovery_web_id == DISCOVERY["web"]["id"]
        assert header.discovery_web_url == DISCOVERY["web"]["url"]
        assert header.discovered_at == DISCOVERED_AT
        assert header.formwork == formwork.__version__
        assert header.as_dict() == {
            "formwork": formwork.__version__,
            "discoverySha256": hashlib.sha256(PRETTY).hexdigest(),
            "discoveryWebId": DISCOVERY["web"]["id"],
            "discoveryWebUrl": DISCOVERY["web"]["url"],
            "discoveredAt": DISCOVERED_AT,
        }

    def test_a_document_without_a_web_block_stamps_empty_strings_not_nothing(self):
        # Apply then sees a compile stamp whose web cannot match anything and
        # refuses (fail closed) instead of skipping the site check.
        header = provenance(b"{}", {})
        assert header.discovery_web_id == ""
        assert header.discovery_web_url == ""
        assert header.discovered_at == ""
        assert "discoveryWebId" in header.as_dict()

    def test_multipage_still_exports_the_header_it_defined_in_m7(self):
        assert multipage.Provenance is Provenance
        assert multipage.provenance is provenance


class TestThePayloadStamp:
    def test_it_is_the_header_plus_the_spec_and_the_compile_time(self):
        header = provenance(PRETTY, DATED)
        stamp = payload_stamp(header, "home.yaml", "2026-09-07T01:02:03Z")
        assert isinstance(stamp, PayloadStamp)
        assert stamp.as_dict() == {
            **header.as_dict(),
            "spec": "home.yaml",
            "compiledAt": "2026-09-07T01:02:03Z",
        }
        assert list(stamp.as_dict()) == [
            "formwork",
            "discoverySha256",
            "discoveryWebId",
            "discoveryWebUrl",
            "discoveredAt",
            "spec",
            "compiledAt",
        ]

    def test_the_clock_is_iso_utc_to_the_second(self):
        header = provenance(PRETTY, DATED)
        assert ISO_UTC.match(payload_stamp(header, "x.yaml").compiled_at)
        assert ISO_UTC.match(process_stamp("b.json")["processedAt"])

    def test_the_one_liner_names_every_field_on_one_line(self):
        header = provenance(PRETTY, DATED)
        line = payload_stamp(header, "home.yaml", "2026-09-07T01:02:03Z").one_liner()
        assert "\n" not in line
        assert line == (
            f"provenance: formwork {formwork.__version__} compiled home.yaml at"
            f" 2026-09-07T01:02:03Z against discovery sha256 {header.discovery_sha256[:12]}"
            f" (web {DISCOVERY['web']['id']} at {DISCOVERY['web']['url']},"
            f" discovered {DISCOVERED_AT})"
        )

    def test_a_process_stamp_is_version_bound_not_web_bound(self):
        stamp = process_stamp("formwork-bundle.json", "2026-09-07T01:02:03Z")
        assert stamp == {
            "formwork": formwork.__version__,
            "bundle": "formwork-bundle.json",
            "processedAt": "2026-09-07T01:02:03Z",
        }


class TestEveryProducerStampsItsPayload:
    def test_compile_stamps_the_payload_and_prints_the_stamp_after_payload_written(
        self, tmp_path, capsys
    ):
        discovery = write_discovery(tmp_path)
        raw = discovery.read_bytes()
        spec = tmp_path / "home.yaml"
        spec.write_text(HOME, encoding="utf-8")
        out = tmp_path / "payload.json"
        assert main(["compile", str(spec), str(discovery), "--out", str(out)]) == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        stamp = payload[PAYLOAD_KEY]
        assert stamp["formwork"] == formwork.__version__
        assert stamp["discoverySha256"] == hashlib.sha256(raw).hexdigest()
        assert stamp["discoveryWebId"] == DISCOVERY_WITH_TEXT["web"]["id"]
        assert stamp["discoveryWebUrl"] == DISCOVERY_WITH_TEXT["web"]["url"]
        assert stamp["spec"] == "home.yaml"
        assert ISO_UTC.match(stamp["compiledAt"])
        # The rest of the payload is what it was before the stamp.
        assert set(payload) == {
            "schema",
            "sourcePage",
            "title",
            "canvas",
            "unresolved",
            PAYLOAD_KEY,
        }
        lines = capsys.readouterr().out.splitlines()
        assert lines[0].startswith(f"payload written: {out} (")
        header = provenance(raw, DISCOVERY_WITH_TEXT)
        assert lines[1] == payload_stamp(header, "home.yaml", stamp["compiledAt"]).one_liner()
        assert lines[2].startswith("  section 1, column 1: ")

    def test_the_hash_follows_the_file_bytes_not_the_parse(self, tmp_path):
        # Two files, one document, different whitespace: the same canvas, two
        # discoverySha256 values, because the stamp names the file on the CLI.
        spec = tmp_path / "home.yaml"
        spec.write_text(HOME, encoding="utf-8")
        forms = {
            "compact.json": json.dumps(DISCOVERY_WITH_TEXT),
            "pretty.json": json.dumps(DISCOVERY_WITH_TEXT, indent=2) + "\n",
        }
        payloads = {}
        for name, text in forms.items():
            path = tmp_path / name
            path.write_text(text, encoding="utf-8")
            out = tmp_path / f"{name}.payload.json"
            assert main(["compile", str(spec), str(path), "--out", str(out)]) == 0
            payloads[name] = json.loads(out.read_text(encoding="utf-8"))
            digest = payloads[name][PAYLOAD_KEY]["discoverySha256"]
            assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
        compact, pretty = payloads["compact.json"], payloads["pretty.json"]
        assert compact["canvas"] == pretty["canvas"]
        assert compact[PAYLOAD_KEY]["discoverySha256"] != pretty[PAYLOAD_KEY]["discoverySha256"]

    def test_compile_pages_stamps_each_payload_with_the_manifest_header(self, tmp_path):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, home=HOME)
        out = tmp_path / "build"
        manifest = compile_pages(find_specs(str(pages)), discovery, out)
        payload = json.loads((out / "home.payload.json").read_text(encoding="utf-8"))
        stamp = payload[PAYLOAD_KEY]
        header = manifest.provenance.as_dict()
        assert {key: stamp[key] for key in header} == header
        assert header["discoverySha256"] == hashlib.sha256(discovery.read_bytes()).hexdigest()
        assert stamp["spec"] == "home.yaml"
        assert ISO_UTC.match(stamp["compiledAt"])
        assert set(stamp) == set(header) | {"spec", "compiledAt"}

    def test_compile_pages_gives_every_page_of_a_run_the_same_compile_time(self, tmp_path):
        discovery = write_discovery(tmp_path)
        pages = write_specs(tmp_path, home=HOME, again=HOME)
        out = tmp_path / "build"
        compile_pages(find_specs(str(pages)), discovery, out)
        stamps = [
            json.loads((out / f"{stem}.payload.json").read_text(encoding="utf-8"))[PAYLOAD_KEY]
            for stem in ("again", "home")
        ]
        assert stamps[0]["compiledAt"] == stamps[1]["compiledAt"]
        assert [stamp["spec"] for stamp in stamps] == ["again.yaml", "home.yaml"]

    def test_process_stamps_the_version_and_the_bundle_name(self, tmp_path):
        bundle = FIXTURES / "collabhome.bundle.json"
        out = tmp_path / "payload.json"
        assert main(["process", str(bundle), "--out", str(out)]) == 0
        stamp = json.loads(out.read_text(encoding="utf-8"))[PAYLOAD_KEY]
        assert stamp["formwork"] == formwork.__version__
        assert stamp["bundle"] == "collabhome.bundle.json"
        assert ISO_UTC.match(stamp["processedAt"])
        # A copy is bound by its mapping, not by a web: no site fields.
        assert "discoveryWebId" not in stamp
