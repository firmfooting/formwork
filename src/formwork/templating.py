"""The one Jinja environment every rendered artifact comes from.

Templates live in ``formwork/templates``. Two kinds render here:

* the paste-in scripts (``*.js.j2``) render with autoescape OFF: they emit
  JavaScript, and every interpolation is a ready literal built in Python
  (``json.dumps``) or a package constant, never operator text;
* the page preview (``*.html.j2``) renders with autoescape ON, and a text
  part's HTML is marked safe at the one place it is inlined.

StrictUndefined so a missing variable fails the render instead of writing
``undefined`` into a script. ``trim_blocks`` and ``lstrip_blocks`` so a
template's Jinja comments and includes leave no whitespace behind, and
``keep_trailing_newline`` so a script ends with the newline its template
ends with: the goldens under ``tests/fixtures/expected`` pin all of it.
"""

import functools
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "templates"


@functools.cache
def environment() -> Environment:
    """The shared environment (built once; templates are cached by Jinja)."""
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_template(template: str, **context: Any) -> str:
    """Render ``templates/<template>`` with the given context.

    The first parameter is named ``template`` (not ``name``) because the
    apply context legitimately carries a ``name`` key.
    """
    return environment().get_template(template).render(**context)
