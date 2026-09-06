"""Paste-in script generators.

Formwork's operator interface is console paste-ins rendered here from the
Jinja templates under ``formwork/templates``:

* the extract script runs on the SOURCE page's site, fetches the page item
  and the web's identity over same-origin REST, assembles a formwork bundle,
  and downloads it as formwork-bundle.json;
* the discover script runs on any page of a site, places one control per
  placeable component (and two known text controls) on a scratch page, reads
  back what SharePoint persisted, recycles the page, and downloads
  formwork-discovery.json;
* the apply script runs on any page of the TARGET site, reads the processed
  payload embedded in it, creates the new page, writes the canvas, and
  verifies by reading back what SharePoint actually stored.

All fetches use relative URLs so the same script body works on any tenant and
site; only the embedded payload differs per apply run. The shared prelude
(``_prelude.js.j2``) carries the measured transport facts; each script's own
template carries its phase logic. The emitted bytes are pinned by the goldens
under ``tests/fixtures/expected``.
"""

import json

from . import __version__
from .templating import render_template


def generate_extract_script() -> str:
    """Console script: extract the current page as a formwork bundle."""
    return render_template("extract.js.j2", version=__version__)


def generate_discover_script() -> str:
    """Console script: discover placeable components on the current site."""
    return render_template("discover.js.j2", version=__version__)


def generate_apply_script(
    page_name: str = "Formwork copy",
    canvas_payload: str = "{}",
    promoted_state: int = 0,
) -> str:
    """Console script: create the page on the target site and set its canvas.

    ``canvas_payload`` is the processed JSON document produced by
    ``formwork process``; it is embedded as a JSON string literal and parsed
    at runtime. The JSON embedding happens HERE, so the template receives
    ready JavaScript literals and never quotes anything itself.
    """
    return render_template(
        "apply.js.j2",
        version=__version__,
        name=json.dumps(page_name),
        payload_json=json.dumps(canvas_payload),
        state=str(int(promoted_state)),
    )
