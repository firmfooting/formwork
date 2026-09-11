"""Review 2026-09-11 P2-3: the rendered-YAML refusal must not pretend the
position is a line of the spec file.

The value-leak fix (#15) reports only the position of the YAML error in the
RENDERED text. A multi-line vars value shifts every line after it, so the
number can exceed the spec file's own line count. The refusal now says so
explicitly, keeping the no-values property intact.
"""

from pathlib import Path

import pytest

from formwork.dsl import DslError
from formwork.multipage import read_spec

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def test_refusal_names_the_rendered_text_not_the_spec_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    discovery = tmp_path / "discovery.json"
    discovery.write_text(
        (FIXTURES / "discovery.m5.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "v.yaml").write_text(
        'blurb: "line one\\nline two\\nline three"\n', encoding="utf-8"
    )
    # The unterminated string is on the spec's line 7; three substituted
    # newlines push the YAML error to rendered line 10.
    spec = tmp_path / "p.yaml"
    spec.write_text(
        "page:\n"
        "  name: P\n"
        "  title: T\n"
        "vars: v.yaml\n"
        "sections:\n"
        "  - type: text\n"
        "    text: {{ blurb }} broken\n",
        encoding="utf-8",
    )

    with pytest.raises(DslError) as excinfo:
        read_spec(spec, None)
    message = str(excinfo.value)
    assert "invalid YAML" in message
    assert "rendered" in message and "not the spec file" in message
    # The multi-line substitution really did shift the line past the file's
    # own line count (7 lines), which is the whole point of the caveat.
    assert "line 9" in message
