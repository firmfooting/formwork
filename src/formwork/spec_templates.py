"""Spec template rendering (M10): page specs as Jinja templates over vars.

A spec file is rendered as a Jinja2 template BEFORE the YAML parser sees
it, so the DSL itself is unchanged (the golden scripts must never move
because of this module; the rendering environment is the shared one from
:mod:`formwork.templating` — one Jinja configuration per project).

Variables come from a vars file (YAML mapping, safe_load only) plus
``--set k=v`` overrides, which win. StrictUndefined is the point: a
missing variable is a compile error naming the variable and its template
line, never an empty string baked into a page. Error values are never
echoed — a vars file routinely carries site URLs or connection strings,
so messages name the variable, never its value (pinned by
``test_secret_values_never_reach_output``-style tests in
``tests/test_spec_templates.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from jinja2 import TemplateError

from .dsl import DslError
from .templating import environment


def load_vars(path: Path | str) -> dict[str, Any]:
    """Load a vars file: a YAML mapping, safe_load only, nothing else.

    A vars file is data, never code: ``yaml.safe_load`` cannot execute
    anything, and a non-mapping root is refused with a cited error (the
    file's own name, not its contents).
    """
    file = Path(path)
    try:
        with open(file, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except OSError as exc:
        # strerror carries the reason, never file content (P2-1: a missing
        # page vars file must fail its page, not abort the run with a
        # traceback).
        raise DslError(f"{file}: cannot read vars file ({exc.strerror})") from None
    except yaml.YAMLError as exc:
        # Report position, never the offending line: PyYAML's message
        # embeds the source line, and a vars file routinely carries
        # values that must not reach stderr or the manifest (P1-4).
        where = _yaml_mark(exc)
        raise DslError(f"{file}: invalid YAML in vars file{where}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise DslError(
            f"{file}: a vars file is a mapping of name to value, "
            f"not {type(data).__name__}"
        )
    return data


def parse_set_overrides(pairs: Sequence[str] | None) -> dict[str, Any]:
    """Turn ``--set k=v`` strings into variables. Later pairs win.

    A pair without ``=`` is refused with the pair named; the value is
    never part of the message (it may be a secret) but the key always is.
    """
    out: dict[str, Any] = {}
    for pair in pairs or ():
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise DslError(
                f"--set expects name=value (got a pair without '='; name: {key!r})"
            )
        if "\n" in value or "\r" in value:
            # A newline in a value can carry YAML structure (a following
            # "  - text:" line becomes a new part). Refused with the key
            # named, never the value (P2-4); use the vars file for
            # multi-line values.
            raise DslError(
                f"--set value for {key!r} contains a newline; put multi-line"
                " values in the vars file instead"
            )
        out[key] = value
    return out


def render_spec_text(source: str, variables: dict[str, Any], name: str) -> str:
    """Render one spec file's text with StrictUndefined. No DSL change:
    the caller YAML-parses the returned text exactly as it parsed the file
    before M10. Uses the project's one Jinja environment."""
    try:
        template = environment().from_string(source)
        return template.render(**variables)
    except TemplateError as exc:
        # Name the template, the line if Jinja gives us one, and the
        # variable if the error is an undefined name. Values are never
        # part of the message.
        line = getattr(exc, "lineno", None)
        where = f"{name}:{line}" if isinstance(line, int) else name
        undefined = _undefined_name(exc)
        if undefined is not None:
            raise DslError(
                f"{where}: template variable {undefined!r} is not defined "
                "(pass it with --set or in the vars file)"
            ) from exc
        raise DslError(f"{where}: template error: {_first_line(exc)}") from exc


def resolve_variables(
    vars_path: Path | str | None,
    set_pairs: Sequence[str] | None,
    *,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Precedence, documented in --help and pinned by tests:
    ``--set`` overrides the vars file, which overrides ``base``."""
    variables = dict(base) if base else {}
    variables.update(load_vars(vars_path) if vars_path is not None else {})
    variables.update(parse_set_overrides(set_pairs))
    return variables


def _yaml_mark(exc: yaml.YAMLError) -> str:
    """", line N, column M" from the problem mark, or "" when absent."""
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return ""
    return f" at line {mark.line + 1}, column {mark.column + 1}"


def _undefined_name(exc: Exception) -> str | None:
    message = str(exc)
    # StrictUndefined's message shape: "'name' is undefined"
    if "is undefined" in message:
        return message.split("'")[1] if "'" in message else None
    return None


def _first_line(exc: BaseException) -> str:
    return " ".join(str(exc).split())
