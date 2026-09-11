"""Spec template rendering (M10): the pins that make it safe.

Contract, under test here and in the module docstring of
:mod:`formwork.spec_templates`:

* **No flags, no change.** Rendering is keyed on operator intent
  (``--vars``/``--set`` given), never on the resolved map. Without flags
  the spec bytes reach the YAML parser unchanged — a spec containing
  literal Jinja-ish text keeps compiling.
* **StrictUndefined.** A missing variable is a refusal naming the
  variable, never an empty string baked into a page.
* **Values never echo.** Error messages name variables and files and
  positions, never values; this file's fixtures put SECRET on the lines
  that break and assert it stays out of the messages and the manifest.
* **No HTML escaping in spec values.** ``& < > " '`` survive verbatim
  (spec rendering is not HTML rendering).
* **Precedence.** ``--set`` > the page's own ``vars:`` file > shared
  ``--vars``; a page file naming a key an explicit ``--set`` also names
  is refused, not silently dropped.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from formwork.cli import main
from formwork.dsl import DslError
from formwork.multipage import PageOptions, TemplateVars, compile_pages, find_specs, read_spec
from formwork.spec_templates import (
    load_vars,
    parse_set_overrides,
    render_spec_text,
    resolve_variables,
)
from test_dsl import DISCOVERY_WITH_TEXT

SECRET = "s3cr3t-token-value"
URL = "https://contoso.sharepoint.com/sites/x?a=1&b=2"


def _write(tmp_path: pathlib.Path, name: str, text: str) -> pathlib.Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


_DISCOVERY = {
    "schema": "formwork.discovery/v1",
    "web": {"id": "w", "url": "https://x/sites/T"},
    "discoveredAt": "2026-01-01T00:00:00Z",
    "components": {},
}


class TestVarsFiles:
    def test_a_vars_file_is_a_mapping(self, tmp_path):
        p = _write(tmp_path, "vars.yaml", "env: prod\ncolumns: [4, 8]\n")
        assert load_vars(p) == {"env": "prod", "columns": [4, 8]}

    def test_a_non_mapping_vars_file_is_refused(self, tmp_path):
        p = _write(tmp_path, "vars.yaml", "- just\n- a\n- list\n")
        with pytest.raises(DslError, match="mapping of name to value"):
            load_vars(p)

    def test_invalid_yaml_names_the_file_and_position_never_the_content(self, tmp_path):
        # The broken line carries a secret; the refusal must carry neither
        # the line nor the value (review 2026-09-08 P1-4).
        p = _write(tmp_path, "vars.yaml", f'token: "{SECRET}\nenv: prod\n')
        with pytest.raises(DslError) as excinfo:
            load_vars(p)
        message = str(excinfo.value)
        assert "vars.yaml" in message
        assert "line" in message
        assert SECRET not in message

    def test_a_missing_vars_file_is_a_one_line_refusal_not_a_traceback(self, tmp_path):
        with pytest.raises(DslError, match="cannot read vars file"):
            load_vars(tmp_path / "renamed-away.yaml")

    def test_set_pairs_parse_and_later_wins(self):
        assert parse_set_overrides(["a=1", "a=2", "b=x"]) == {"a": "2", "b": "x"}

    def test_a_set_pair_without_equals_is_refused_with_the_name(self):
        with pytest.raises(DslError, match="name: 'env'"):
            parse_set_overrides(["env"])

    def test_a_set_value_with_a_newline_is_refused_with_the_key_only(self):
        with pytest.raises(DslError, match="'title'"):
            parse_set_overrides(["title=Ops\n  - text: injected"])


class TestPrecedence:
    def test_set_overrides_vars(self, tmp_path):
        v = _write(tmp_path, "vars.yaml", "env: prod\n")
        assert resolve_variables(v, ["env=dev"]) == {"env": "dev"}


class TestRenderSpec:
    def test_a_missing_variable_names_the_variable_and_line(self):
        with pytest.raises(DslError, match=r"'env'.*--set"):
            render_spec_text("title: {{ env }} page", {}, "spec.yaml")

    def test_values_with_html_metacharacters_survive_verbatim(self):
        # P1-3: from_string must not autoescape; a site URL with a query
        # string and an apostrophe in a title are ordinary values.
        out = render_spec_text("url: {{ u }}", {"u": URL}, "s")
        assert out == f"url: {URL}"
        out = render_spec_text("title: {{ t }}", {"t": "Team's Home"}, "s")
        assert out == "title: Team's Home"

    def test_a_value_referenced_then_broken_never_reaches_the_error(self):
        # The template DOES reference the secret-shaped value on the line
        # that breaks the render; the refusal must still not carry it.
        with pytest.raises(DslError) as excinfo:
            render_spec_text("title: {{ missing }}\nurl: {{ SECRET }}", {}, "s")
        assert SECRET not in str(excinfo.value)


class TestReadSpec:
    def test_no_flags_and_literal_jinja_text_the_bytes_are_unchanged(self, tmp_path):
        # P1-2: with no template flags the file is data. A doc example with
        # {{ handlebars }} must compile exactly as it did before M10.
        raw = "title: Literal {{ not_a_var }}\nsections: []\n"
        p = _write(tmp_path, "spec.yaml", raw)
        spec = read_spec(p, None)
        assert spec["title"] == "Literal {{ not_a_var }}"

    def test_with_vars_the_template_renders(self, tmp_path):
        p = _write(tmp_path, "spec.yaml", "title: {{ env }} page\nsections: []\n")
        vars_file = _write(tmp_path, "v.yaml", "env: Training\n")
        spec = read_spec(p, TemplateVars(vars_path=str(vars_file)))
        assert spec["title"] == "Training page"

    def test_with_set_alone_the_template_renders(self, tmp_path):
        # P1-1 on the read_spec layer: --set alone must render.
        p = _write(tmp_path, "spec.yaml", "title: {{ env }} page\nsections: []\n")
        spec = read_spec(p, TemplateVars(set_pairs=["env=Ward"]))
        assert spec["title"] == "Ward page"

    def test_a_strictly_undefined_variable_fails_the_page(self, tmp_path):
        # Flags given but the name missing: named refusal, not {{ env }}.
        p = _write(
            tmp_path, "spec.yaml", "title: {{ env }}\nsections:\n  - parts:\n      - text: hi\n"
        )
        with pytest.raises(DslError, match="'env'"):
            read_spec(p, TemplateVars(vars_path=str(_write(tmp_path, "empty.yaml", ""))))

    def test_a_page_vars_key_anywhere_at_column_zero_is_found(self, tmp_path):
        # P1-5: a document marker or comment above the key must not
        # silently disable it.
        _write(tmp_path, "own.yaml", "env: page-local\n")
        p = _write(
            tmp_path,
            "spec.yaml",
            "---\nvars: own.yaml\ntitle: {{ env }}\nsections: []\n",
        )
        spec = read_spec(p, TemplateVars())
        assert spec["title"] == "page-local"
        assert "vars" not in spec

    def test_a_page_vars_key_overrides_shared_vars(self, tmp_path):
        _write(tmp_path, "own.yaml", "env: page-local\n")
        shared = _write(tmp_path, "shared.yaml", "env: shared\n")
        p = _write(
            tmp_path,
            "spec.yaml",
            "vars: own.yaml\ntitle: {{ env }}\nsections: []\n",
        )
        spec = read_spec(p, TemplateVars(vars_path=str(shared)))
        assert spec["title"] == "page-local"

    def test_a_page_vars_file_naming_a_set_key_is_refused(self, tmp_path):
        _write(tmp_path, "own.yaml", "env: page-local\n")
        p = _write(
            tmp_path,
            "spec.yaml",
            "vars: own.yaml\ntitle: {{ env }}\nsections: []\n",
        )
        with pytest.raises(DslError, match="explicit --set"):
            read_spec(p, TemplateVars(set_pairs=["env=shared"]))

    def test_a_missing_page_vars_file_fails_its_page_as_a_refusal(self, tmp_path):
        p = _write(tmp_path, "spec.yaml", "vars: gone.yaml\ntitle: x\nsections: []\n")
        with pytest.raises(DslError, match="cannot read vars file"):
            read_spec(p, TemplateVars())

    def test_a_rendered_spec_that_breaks_yaml_never_echoes_the_value(self, tmp_path):
        # P1-4's sibling: here the line PyYAML reports is RENDERED text, so
        # its snippet carries the substituted value. The refusal must name
        # the file and the position and nothing else.
        p = _write(
            tmp_path,
            "spec.yaml",
            "title: t\nsections:\n  - parts:\n      - text: {{ msg }}\n",
        )
        with pytest.raises(DslError) as excinfo:
            read_spec(p, TemplateVars(set_pairs=[f"msg={SECRET}: breaks"]))
        message = str(excinfo.value)
        assert "invalid YAML" in message
        assert "line" in message
        assert SECRET not in message


class TestCompilePagesCli:
    """The end-to-end layer P1-1/P1-2 shipped without."""

    def _discovery(self, tmp_path, with_text=False):
        doc = DISCOVERY_WITH_TEXT if with_text else _DISCOVERY
        return _write(tmp_path, "discovery.json", json.dumps(doc))

    def test_set_alone_renders_pages_without_a_vars_key(self, tmp_path):
        pages = _write(
            tmp_path,
            "brief.yaml",
            "title: {{ env }} brief\nsections:\n  - parts:\n      - text: hi\n",
        )
        out = tmp_path / "build"
        manifest = compile_pages(
            find_specs(str(pages)),
            self._discovery(tmp_path, with_text=True),
            out,
            PageOptions(template_vars=TemplateVars(set_pairs=["env=Training"])),
        )
        (result,) = manifest.results
        assert result.ok, result.error
        payload = json.loads((out / "brief.payload.json").read_text(encoding="utf-8"))
        assert payload["title"] == "Training brief"

    def test_no_flags_leaves_literal_jinja_text_alone(self, tmp_path):
        # P1-2 end to end: a doc-y spec with {{ x }} and no flags compiles
        # exactly as on the parent commit.
        pages = _write(tmp_path, "doc.yaml", "title: Example {{ x }}\nsections:\n  - text: hi\n")
        out = tmp_path / "build"
        manifest = compile_pages(find_specs(str(pages)), self._discovery(tmp_path), out)
        (result,) = manifest.results
        assert result.ok, result.error
        payload = json.loads((out / "doc.payload.json").read_text(encoding="utf-8"))
        assert payload["title"] == "Example {{ x }}"

    def test_values_with_metacharacters_reach_the_payload_verbatim(self, tmp_path):
        pages = _write(
            tmp_path,
            "s.yaml",
            "title: {{ t }}\nsections:\n  - parts:\n      - text: {{ u }}\n",
        )
        out = tmp_path / "build"
        manifest = compile_pages(
            find_specs(str(pages)),
            self._discovery(tmp_path, with_text=True),
            out,
            PageOptions(template_vars=TemplateVars(set_pairs=["t=Team's&Co", f"u={URL}"])),
        )
        (result,) = manifest.results
        assert result.ok, result.error
        payload = json.loads((out / "s.payload.json").read_text(encoding="utf-8"))
        assert payload["title"] == "Team's&Co"
        # The URL is a VALUE rendered into the text part's html inside the
        # canvas. The canvas carries the STORED entity spelling (&#58; for
        # :, &amp; for &). The P1-3 pin: undo exactly those two folds and
        # the authored URL must come back — an autoescaped render would
        # have double-escaped (&amp;#58;) and broken this round-trip.
        body = payload["canvas"].replace("&#58;", ":").replace("&amp;", "&")
        assert URL in body
        # And no apostrophe mangling anywhere in the payload (title kept
        # "Team's" verbatim — asserted above; this catches &#39; leaks).
        assert "&#39;" not in json.dumps(payload)

    def test_a_broken_vars_file_puts_no_value_in_the_manifest(self, tmp_path):
        _write(tmp_path, "vars.yaml", f'token: "{SECRET}\nenv: prod\n')
        pages = _write(
            tmp_path,
            "a.yaml",
            "title: {{ env }}\nsections:\n  - parts:\n      - text: hi\n",
        )
        out = tmp_path / "build"
        manifest = compile_pages(
            find_specs(str(pages)),
            self._discovery(tmp_path),
            out,
            PageOptions(template_vars=TemplateVars(vars_path=str(tmp_path / "vars.yaml"))),
        )
        (result,) = manifest.results
        assert not result.ok
        on_disk = (out / "formwork-pages.json").read_text(encoding="utf-8")
        assert SECRET not in on_disk
        assert SECRET not in (result.error or "")

    def test_a_rendered_spec_that_breaks_yaml_puts_no_value_in_the_manifest(self, tmp_path):
        # The sibling of the vars-file pin above, on the render path: the
        # failing line is rendered text, so its snippet carries a value.
        pages = _write(
            tmp_path,
            "a.yaml",
            "title: t\nsections:\n  - parts:\n      - text: {{ msg }}\n",
        )
        out = tmp_path / "build"
        manifest = compile_pages(
            find_specs(str(pages)),
            self._discovery(tmp_path, with_text=True),
            out,
            PageOptions(template_vars=TemplateVars(set_pairs=[f"msg={SECRET}: breaks"])),
        )
        (result,) = manifest.results
        assert not result.ok
        assert SECRET not in (result.error or "")
        on_disk = (out / "formwork-pages.json").read_text(encoding="utf-8")
        assert SECRET not in on_disk

    def test_the_stamp_records_the_template_layer_without_values(self, tmp_path):
        vars_file = _write(tmp_path, "vars.yaml", "env: prod\n")
        pages = _write(
            tmp_path, "a.yaml", "title: {{ env }}\nsections:\n  - parts:\n      - text: hi\n"
        )
        out = tmp_path / "build"
        manifest = compile_pages(
            find_specs(str(pages)),
            self._discovery(tmp_path, with_text=True),
            out,
            PageOptions(
                template_vars=TemplateVars(
                    vars_path=str(vars_file), set_pairs=["flag=1"]
                )
            ),
        )
        (result,) = manifest.results
        assert result.ok, result.error
        stamp = json.loads((out / "a.payload.json").read_text(encoding="utf-8"))["provenance"]
        assert stamp["varsFile"] == "vars.yaml"
        assert len(stamp["varsSha256"]) == 64
        assert stamp["setKeys"] == "flag"
        assert "prod" not in json.dumps(stamp)

    def test_the_stamp_records_a_page_own_vars_file_with_no_flags(self, tmp_path):
        # M10 P2-5: a page rendered from its own ``vars:`` file must be
        # stamped with that file, not left looking untemplated.
        _write(tmp_path, "own.yaml", "env: page-local\n")
        pages = _write(
            tmp_path,
            "a.yaml",
            "vars: own.yaml\ntitle: {{ env }}\nsections:\n  - parts:\n      - text: hi\n",
        )
        out = tmp_path / "build"
        manifest = compile_pages(
            find_specs(str(pages)), self._discovery(tmp_path, with_text=True), out
        )
        (result,) = manifest.results
        assert result.ok, result.error
        payload = json.loads((out / "a.payload.json").read_text(encoding="utf-8"))
        assert payload["title"] == "page-local"
        stamp = payload["provenance"]
        assert stamp["ownVarsFile"] == "own.yaml"
        assert len(stamp["ownVarsSha256"]) == 64
        assert stamp["varsFile"] == ""
        assert "page-local" not in json.dumps(stamp)

    def test_the_stamp_names_the_page_vars_file_beside_shared_vars(self, tmp_path):
        # P2-5 misattribution: with --vars AND a page ``vars:`` file the
        # page file wins at render time, so a stamp naming only the shared
        # file would describe a file that did not produce the content.
        shared = _write(tmp_path, "vars.yaml", "env: shared\n")
        _write(tmp_path, "own.yaml", "env: page-local\n")
        pages = _write(
            tmp_path,
            "a.yaml",
            "vars: own.yaml\ntitle: {{ env }}\nsections:\n  - parts:\n      - text: hi\n",
        )
        out = tmp_path / "build"
        manifest = compile_pages(
            find_specs(str(pages)),
            self._discovery(tmp_path, with_text=True),
            out,
            PageOptions(template_vars=TemplateVars(vars_path=str(shared))),
        )
        (result,) = manifest.results
        assert result.ok, result.error
        payload = json.loads((out / "a.payload.json").read_text(encoding="utf-8"))
        assert payload["title"] == "page-local"  # the page file won
        stamp = payload["provenance"]
        assert stamp["varsFile"] == "vars.yaml"
        assert stamp["ownVarsFile"] == "own.yaml"
        assert stamp["varsSha256"] != stamp["ownVarsSha256"]


class TestCompileCli:
    def test_compile_renders_before_parsing(self, tmp_path):
        discovery = _write(tmp_path, "discovery.json", json.dumps(_DISCOVERY))
        spec = _write(
            tmp_path,
            "page.yaml",
            "title: {{ env }} brief\nsections:\n  - parts:\n      - text: hi\n",
        )
        _write(tmp_path, "vars.yaml", "env: Training\n")
        out = tmp_path / "payload.json"
        discovery = _write(tmp_path, "d2.json", json.dumps(DISCOVERY_WITH_TEXT))
        rc = main(
            [
                "compile", str(spec), str(discovery), "--out", str(out),
                "--vars", str(tmp_path / "vars.yaml"),
            ]
        )
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["title"] == "Training brief"

    def test_compile_with_an_empty_vars_file_still_renders_and_refuses(self, tmp_path):
        # P2-2: a stub vars file must not bake literal {{ env }} into a page.
        discovery = _write(tmp_path, "discovery.json", json.dumps(_DISCOVERY))
        spec = _write(
            tmp_path,
            "page.yaml",
            "title: {{ env }} brief\nsections:\n  - parts:\n      - text: hi\n",
        )
        _write(tmp_path, "vars.yaml", "# env: prod (fill me in)\n")
        out = tmp_path / "payload.json"
        rc = main(
            [
                "compile", str(spec), str(discovery), "--out", str(out),
                "--vars", str(tmp_path / "vars.yaml"),
            ]
        )
        assert rc == 1
        assert not out.exists()
