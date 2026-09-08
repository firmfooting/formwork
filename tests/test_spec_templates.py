"""M10 template rendering: the pins that make it safe.

The module docstring of :mod:`formwork.templating` states the contract;
these tests hold it. The load-bearing ones:

* **No vars, no change.** Without --vars/--set the spec bytes reach the
  YAML parser unchanged, and the golden apply/extract scripts do not move
  (test_generator.py still owns that proof; here it is the read_spec path).
* **StrictUndefined.** A missing variable is a DslError naming the
  variable, not an empty string baked into a page.
* **Values never echo.** Error messages name variables and files, never
  values: a vars file routinely carries site URLs or connection strings.
* **Precedence.** --set overrides --vars, which overrides a page's own
  vars file; and a page vars file may not silently shadow --vars.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from formwork.cli import main
from formwork.dsl import DslError
from formwork.multipage import read_spec
from formwork.spec_templates import (
    load_vars,
    parse_set_overrides,
    render_spec_text,
    resolve_variables,
)
from test_dsl import DISCOVERY

SECRET = "https://secret.example/sites/hidden"


def _write(tmp_path: pathlib.Path, name: str, text: str) -> pathlib.Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


class TestVarsFiles:
    def test_a_vars_file_is_a_mapping(self, tmp_path):
        p = _write(tmp_path, "vars.yaml", "env: prod\ncolumns: [4, 8]\n")
        assert load_vars(p) == {"env": "prod", "columns": [4, 8]}

    def test_a_non_mapping_vars_file_is_refused(self, tmp_path):
        p = _write(tmp_path, "vars.yaml", "- just\n- a\n- list\n")
        with pytest.raises(DslError, match="mapping of name to value"):
            load_vars(p)

    def test_invalid_yaml_in_vars_names_the_file_not_the_content(self, tmp_path):
        p = _write(tmp_path, "vars.yaml", "key: [unclosed\n")
        with pytest.raises(DslError, match=r"vars\.yaml"):
            load_vars(p)

    def test_set_pairs_parse_and_later_wins(self):
        assert parse_set_overrides(["a=1", "a=2", "b=x"]) == {"a": "2", "b": "x"}

    def test_a_set_pair_without_equals_is_refused_with_the_name(self):
        with pytest.raises(DslError, match="name: 'env'"):
            parse_set_overrides(["env"])


class TestPrecedence:
    def test_set_overrides_vars(self, tmp_path):
        v = _write(tmp_path, "vars.yaml", "env: prod\n")
        assert resolve_variables(v, ["env=dev"]) == {"env": "dev"}

    def test_base_is_the_lowest_layer(self, tmp_path):
        v = _write(tmp_path, "vars.yaml", "env: prod\n")
        assert resolve_variables(v, None, base={"env": "stale", "new": "1"}) == {
            "env": "prod",
            "new": "1",
        }


class TestRenderSpec:
    def test_a_missing_variable_names_the_variable_and_line(self):
        with pytest.raises(DslError, match=r"'env'.*--set"):
            render_spec_text("title: {{ env }} page", {}, "spec.yaml")

    def test_a_value_never_reaches_the_error_message(self):
        # The vars file's VALUE is the secret; the refusal must not carry it.
        with pytest.raises(DslError) as excinfo:
            render_spec_text("title: {{ missing }}", {"other": SECRET}, "spec.yaml")
        assert SECRET not in str(excinfo.value)

    def test_rendering_is_textual_and_yaml_safe_values_are_spelled(self):
        out = render_spec_text("columns: {{ cols }}", {"cols": "[4, 8]"}, "s")
        assert out == "columns: [4, 8]"


class TestReadSpec:
    def test_without_variables_the_bytes_are_unchanged(self, tmp_path):
        raw = "page:\n  title: Literal {{ not_a_var }}\nsections: []\n"
        p = _write(tmp_path, "spec.yaml", raw)
        # No variables: the parser sees the file's own bytes, braces and all.
        spec = read_spec(p, None)
        assert spec["page"]["title"] == "Literal {{ not_a_var }}"

    def test_with_variables_the_template_renders(self, tmp_path):
        p = _write(tmp_path, "spec.yaml", "page:\n  title: {{ env }} page\nsections: []\n")
        spec = read_spec(p, {"env": "Training"})
        assert spec["page"]["title"] == "Training page"

    def test_a_strictly_undefined_variable_fails_the_page(self, tmp_path):
        p = _write(tmp_path, "spec.yaml", "page:\n  title: {{ env }}\nsections: []\n")
        with pytest.raises(DslError, match="'env'"):
            read_spec(p, {})

    def test_a_page_vars_key_layers_over_shared_and_is_dropped(self, tmp_path):
        _write(tmp_path, "own.yaml", "env: page-local\n")
        p = _write(
            tmp_path,
            "spec.yaml",
            "vars: own.yaml\npage:\n  title: {{ env }}\nsections: []\n",
        )
        spec = read_spec(p, {"env": "shared", "extra": "kept"})
        assert spec["page"]["title"] == "page-local"
        assert "vars" not in spec

    def test_a_page_vars_file_may_not_shadow_an_explicit_set(self, tmp_path):
        _write(tmp_path, "own.yaml", "env: page-local\n")
        p = _write(
            tmp_path,
            "spec.yaml",
            "vars: own.yaml\npage:\n  title: {{ env }}\nsections: []\n",
        )
        # The operator's --set env=shared must hold; the page file naming
        # the same key is refused, not silently dropped.
        with pytest.raises(DslError, match="explicit --set"):
            read_spec(
                p,
                {"env": "shared"},
                frozenset({"env"}),
                {"env": "shared"},
            )

    def test_a_set_value_survives_a_page_vars_file(self, tmp_path):
        _write(tmp_path, "own.yaml", "env: page-local\n")
        p = _write(
            tmp_path,
            "spec.yaml",
            "vars: own.yaml\npage:\n  title: {{ env }}\nsections: []\n",
        )
        spec = read_spec(
            p,
            {"env": "shared"},
            frozenset(),
            {"env": "shared"},
        )
        assert spec["page"]["title"] == "shared"


class TestCompileCommandTemplatePath:
    def test_compile_renders_before_parsing(self, tmp_path, monkeypatch, capsys):
        # End to end through the CLI: a spec with a placeholder, a vars
        # file, and the golden discovery fixture from the DSL tests.
        discovery = _write(tmp_path, "discovery.json", json.dumps(DISCOVERY))
        spec = _write(
            tmp_path,
            "page.yaml",
            "title: {{ env }} brief\nsections:\n  - text: hi\n",
        )
        _write(tmp_path, "vars.yaml", "env: Training\n")
        out = tmp_path / "payload.json"
        rc = main(
            [
                "compile",
                str(spec),
                str(discovery),
                "--out",
                str(out),
                "--vars",
                str(tmp_path / "vars.yaml"),
            ]
        )
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["title"] == "Training brief"
