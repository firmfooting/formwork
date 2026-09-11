"""Review 2026-09-11 P2-2: an un-syncable mirror must be reported, never silent.

``_sync_mirrors`` skips a mirror whose new value contains ``&``, ``<`` or
``>`` because the plain-text mirror cannot carry it verbatim. Silence there
recreates the defect #26 was filed for: the JSON carries the new value, the
emitted page keeps the source site's text, and ``process`` reports the ref
applied. The control now records the skipped names and ``apply_plan``
surfaces them as ``staleMirrors`` in the payload and on stderr.
"""

import json
import pathlib
import subprocess
import sys

from formwork.bundle import parse_bundle
from formwork.canvas import Canvas
from formwork.refs import Plan, apply_plan, scan

REPO = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def _bundle():
    data = json.loads((FIXTURES / "collabhome.bundle.json").read_text(encoding="utf-8"))
    return parse_bundle(data)


def test_escaping_value_records_unsynced_mirror_name():
    canvas = Canvas.parse((FIXTURES / "collabhome.canvas.html").read_text(encoding="utf-8"))
    target = canvas.controls[2]  # Quick links
    sp = target.web_part_data["serverProcessedContent"]
    sp["searchablePlainTexts"]["items[0].title"] = "R&D primer"
    target.mark_dirty()

    canvas.render()

    assert target.unsynced_mirrors == ["items[0].title"]


def test_plain_value_leaves_unsynced_mirrors_empty():
    canvas = Canvas.parse((FIXTURES / "collabhome.canvas.html").read_text(encoding="utf-8"))
    target = canvas.controls[2]
    sp = target.web_part_data["serverProcessedContent"]
    sp["searchablePlainTexts"]["items[0].title"] = "Reports library"
    target.mark_dirty()

    canvas.render()

    assert target.unsynced_mirrors == []


def test_apply_plan_reports_stale_mirror_instead_of_staying_silent():
    bundle = _bundle()
    refs = [r for r in scan(bundle) if r.kind == "text"]
    title_ref = next(r for r in refs if r.location.endswith("title"))
    plan = Plan(applied=[(title_ref, "R&D & copy")])

    result = apply_plan(bundle, plan)

    assert result.rewritten, "the ref itself must still apply"
    assert any("mirror" in note for note in result.unresolved_extra)


def test_process_payload_and_stderr_carry_stale_mirrors(tmp_path):
    """End to end: the payload records staleMirrors; stderr names the field."""
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps({"textOverrides": {"Quick links": "R&D & copy"}}), encoding="utf-8"
    )
    out = tmp_path / "out.payload.json"
    proc = subprocess.run(
        [
            sys.executable, "-m", "formwork.cli", "process",
            str(FIXTURES / "collabhome.bundle.json"),
            "--mapping", str(mapping),
            "--out", str(out),
        ],
        capture_output=True, text=True, cwd=REPO, check=False,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(payload["staleMirrors"], list)
    assert any("mirror" in note for note in payload["staleMirrors"]), payload["staleMirrors"]
    assert "stale mirrors" in proc.stderr
