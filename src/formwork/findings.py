"""The findings registry: FINDINGS.md parsed, validated and queried.

FINDINGS.md is data, not decoration. One row per measured claim, six cells:

* ``check-id``: ``<surface>.<scope>.<question>``, lowercase hyphenated
  segments, the surface one of :data:`SURFACES` (``page`` today; the same
  grammar dbml-sharepoint's SURFACES convention uses, so a second surface is
  one more tuple entry, not a new grammar);
* ``claim``: the sentence formwork relies on;
* ``measured``: the ISO date of the run that produced the evidence;
* ``result``: the compact outcome the re-probe reproduces verbatim, so a
  re-run's verdict is a string comparison;
* ``evidence``: ``tests/fixtures/<file>#<dotted.key>`` into a live capture;
* ``re-probe``: the generator command that re-derives the claim. Only two
  exist (:data:`REPROBE_COMMANDS`): the discover run re-derives what the
  catalogue spread itself measures; the findprobe lane re-runs the
  measurement legs and diffs against the ``result`` column.

Two consumers: ``formwork compile`` (:func:`stale_findings`) warns when the
newest row a spec relies on is older than ``--findings-max-age``; the
warning names the check-id and its re-probe command, and never refuses.
Evidence ages, it does not vanish. ``formwork gen findprobe`` renders the
rows into the re-probe paste-in (generator.py).

A re-measured claim is a new row with the same check-id and the new date;
:meth:`Registry.newest` is the row compile judges age by. The parser refuses
a malformed row on load (grammar, date, evidence root, re-probe command,
duplicates) so the file cannot drift into prose.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalogue import Catalogue
from .dsl import placements, resolve_component
from .sections import Placement

#: The surfaces a check-id may name. dbml-sharepoint's convention; extend
#: by appending, never by loosening the grammar.
SURFACES: tuple[str, ...] = ("page",)

#: ``<surface>.<scope>.<question>``: each segment lowercase, starting with a
#: letter, hyphen-separated words of letters and digits.
_SEGMENT = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
CHECK_ID_RE = re.compile(rf"^({_SEGMENT})\.({_SEGMENT})\.({_SEGMENT})$")

#: The table header, in order.
COLUMNS: tuple[str, ...] = ("check-id", "claim", "measured", "result", "evidence", "re-probe")

#: The only mechanisms that re-derive a claim. A row naming anything else is
#: a note, not a finding, and is refused on load.
REPROBE_COMMANDS: tuple[str, ...] = ("formwork gen discover", "formwork gen findprobe")

#: Evidence pointers name a live capture under the fixtures directory.
EVIDENCE_ROOT = "tests/fixtures/"

#: ``formwork compile`` warns when the newest relied-on row is older than
#: this many days (``--findings-max-age``). Strictly older: a row measured
#: exactly this many days ago is still current.
DEFAULT_MAX_AGE_DAYS = 90

#: Where compile and findprobe look when ``--findings`` is not given.
DEFAULT_PATH = "FINDINGS.md"

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RULE_CELL_RE = re.compile(r"^:?-+:?$")

#: The rows the compiler relies on, by what a spec declares.
COMPONENTS_CHECK_ID = "page.components.merge-byte-exact"
TEXT_CHECK_ID = "page.text.colon-rewrite"
STYLED_TEXT_CHECK_ID = "page.text.styled-html"
EMPHASIS_CHECK_ID = "page.emphasis.control-merge"
BIND_CHECK_ID = "page.bind.list-library-keys"
PROPERTIES_SCOPE = "properties"

#: The measured factor sets (sections.MEASURED_FACTOR_SETS) by the row that
#: pins each: the one/two/three defaults ride on every discover run; the
#: 8/4 and 4/8 splits are findprobe legs of their own.
FACTOR_CHECK_IDS: dict[tuple[int, ...], str] = {
    (12,): "page.layout.default-factors",
    (6, 6): "page.layout.default-factors",
    (4, 4, 4): "page.layout.default-factors",
    (8, 4): "page.layout.factors-8-4",
    (4, 8): "page.layout.factors-4-8",
}

#: Text whose HTML carries styling relies on the styled-text row as well as
#: the colon rewrite: an inline style, a class, or a <mark>. HTML tag and
#: attribute names are case-insensitive and '=' may carry spaces around it
#: (text.py:_HTML_REFUSED), and an HTML part is passed through as written, so
#: the match ignores case and whitespace — otherwise a part that spells its
#: styling ``STYLE=`` or ``style =`` would silently skip the styled-text row.
_STYLED_TEXT_RE = re.compile(r"\bstyle\s*=|\bclass\s*=|<mark\b", re.IGNORECASE)


class FindingsError(ValueError):
    """FINDINGS.md cannot be read as a registry."""


@dataclass(frozen=True)
class Finding:
    """One measured claim: a row of FINDINGS.md."""

    check_id: str
    claim: str
    measured: dt.date
    result: str
    evidence: str
    reprobe: str

    @property
    def lane(self) -> str:
        """``discover`` or ``findprobe``: the generator that re-derives it."""
        return self.reprobe.split()[-1]

    @property
    def scope(self) -> str:
        return self.check_id.split(".")[1]

    def age_days(self, today: dt.date) -> int:
        return (today - self.measured).days


@dataclass(frozen=True)
class Registry:
    """The rows of FINDINGS.md, in file order."""

    findings: tuple[Finding, ...] = ()

    def __iter__(self) -> Iterator[Finding]:
        return iter(self.findings)

    def __len__(self) -> int:
        return len(self.findings)

    @property
    def check_ids(self) -> tuple[str, ...]:
        """Every check-id, once each, in first-appearance order."""
        return tuple(dict.fromkeys(f.check_id for f in self.findings))

    def rows(self, check_id: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.check_id == check_id)

    def newest(self, check_id: str) -> Finding | None:
        """The most recently measured row for a check-id; the first of a
        same-day tie. This is the row compile judges age by."""
        newest: Finding | None = None
        for finding in self.rows(check_id):
            if newest is None or finding.measured > newest.measured:
                newest = finding
        return newest

    def newest_in(self, scope: str) -> Finding | None:
        """The newest row of a scope (the middle check-id segment)."""
        newest: Finding | None = None
        for finding in self.findings:
            if finding.scope == scope and (newest is None or finding.measured > newest.measured):
                newest = finding
        return newest

    def lane(self, lane: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.lane == lane)


def alias_slug(alias: str) -> str:
    """A component alias as a check-id segment: ``NewsWebPart`` is
    ``news-web-part``. Findprobe computes the same slug in JavaScript."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "-", alias)
    return re.sub(r"[^a-z0-9]+", "-", spaced.lower()).strip("-") or "unnamed"


# --- parsing ---------------------------------------------------------------


def _split_row(line: str) -> list[str]:
    """The cells of a ``| a | b |`` row; ``\\|`` and ``\\\\`` are literal."""
    inner = line.strip()[1:-1]
    cells: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner) and inner[i + 1] in "|\\":
            current.append(inner[i + 1])
            i += 2
            continue
        if ch == "|":
            cells.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    cells.append("".join(current).strip())
    return cells


def _escape_cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1


def _parse_row(cells: list[str], where: str) -> Finding:
    if len(cells) != len(COLUMNS):
        raise FindingsError(
            f"{where}: expected {len(COLUMNS)} cells ({', '.join(COLUMNS)}), got {len(cells)}"
        )
    for name, cell in zip(COLUMNS, cells, strict=True):
        if not cell:
            raise FindingsError(f"{where}: empty {name} cell")
    check_id, claim, measured, result, evidence, reprobe = cells
    match = CHECK_ID_RE.match(check_id)
    if match is None or match.group(1) not in SURFACES:
        raise FindingsError(
            f"{where}: check-id {check_id!r} does not follow <surface>.<scope>.<question>"
            f" (lowercase hyphenated segments; surface one of {', '.join(SURFACES)})"
        )
    if not _ISO_DATE_RE.match(measured):
        raise FindingsError(f"{where}: measured {measured!r} is not an ISO date (YYYY-MM-DD)")
    try:
        day = dt.date.fromisoformat(measured)
    except ValueError:
        raise FindingsError(f"{where}: measured {measured!r} is not a calendar date") from None
    path, _, key = evidence.partition("#")
    if not path.startswith(EVIDENCE_ROOT) or not key:
        raise FindingsError(
            f"{where}: evidence {evidence!r} must point into a fixture as"
            f" {EVIDENCE_ROOT}<file>#<dotted.key>"
        )
    if reprobe not in REPROBE_COMMANDS:
        raise FindingsError(
            f"{where}: re-probe {reprobe!r} is not a generator command; the only"
            f" mechanisms that re-derive a claim are {' and '.join(REPROBE_COMMANDS)}"
        )
    return Finding(check_id, claim, day, result, evidence, reprobe)


def parse_findings(text: str, source: str = DEFAULT_PATH) -> Registry:
    """Parse the registry table out of FINDINGS.md's text, validating every row."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if _is_table_line(line)), None)
    if start is None:
        raise FindingsError(f"{source}: no registry table (a row starting with '| check-id |')")
    header = _split_row(lines[start])
    if header != list(COLUMNS):
        raise FindingsError(
            f"{source} line {start + 1}: expected the header | {' | '.join(COLUMNS)} |,"
            f" got | {' | '.join(header)} |"
        )
    rule = start + 1
    if rule >= len(lines) or not _is_table_line(lines[rule]) or not all(
        _RULE_CELL_RE.match(cell) for cell in _split_row(lines[rule])
    ):
        raise FindingsError(f"{source} line {rule + 1}: expected the table rule after the header")
    findings: list[Finding] = []
    seen: set[tuple[str, dt.date]] = set()
    for index in range(rule + 1, len(lines)):
        line = lines[index]
        where = f"{source} line {index + 1}"
        if not _is_table_line(line):
            if line.strip():
                raise FindingsError(f"{where}: content after the registry table: {line.strip()!r}")
            continue
        finding = _parse_row(_split_row(line), where)
        key = (finding.check_id, finding.measured)
        if key in seen:
            raise FindingsError(
                f"{where}: a row for {finding.check_id} measured {finding.measured} appears twice"
            )
        seen.add(key)
        findings.append(finding)
    return Registry(tuple(findings))


def load_findings(path: str | Path) -> Registry:
    """The registry at ``path``; FileNotFoundError when there is none."""
    path = Path(path)
    return parse_findings(path.read_text(encoding="utf-8"), source=str(path))


def load_findings_if_present(path: str | Path) -> Registry | None:
    """The registry at ``path``, or None when the file does not exist: the
    default lookup, under which compile stays silent and unchanged."""
    path = Path(path)
    if not path.is_file():
        return None
    return load_findings(path)


def render_findings(registry: Registry) -> str:
    """The registry as its canonical table: what FINDINGS.md ends with."""
    lines = [
        "| " + " | ".join(COLUMNS) + " |",
        "| " + " | ".join("---" for _ in COLUMNS) + " |",
    ]
    for f in registry:
        cells = (f.check_id, f.claim, f.measured.isoformat(), f.result, f.evidence, f.reprobe)
        lines.append("| " + " | ".join(_escape_cell(cell) for cell in cells) + " |")
    return "\n".join(lines) + "\n"


# --- what a spec relies on ---------------------------------------------------


@dataclass(frozen=True)
class Reliance:
    """A spec location that depends on a measured claim."""

    check_id: str
    where: str


def _part_reliances(placement: Placement, cat: Catalogue, registry: Registry) -> list[Reliance]:
    where = f"part {placement.ordinal}"
    part = placement.part
    if placement.kind == "text":
        found = [Reliance(TEXT_CHECK_ID, where)]
        if _STYLED_TEXT_RE.search(str(part.get("text", ""))):
            found.append(Reliance(STYLED_TEXT_CHECK_ID, where))
        return found
    found = [Reliance(COMPONENTS_CHECK_ID, where)]
    if part.get("properties"):
        component = resolve_component(str(part["component"]), cat)
        check_id = f"{SURFACES[0]}.{PROPERTIES_SCOPE}.{alias_slug(component.alias)}"
        fallback = registry.newest_in(PROPERTIES_SCOPE)
        # A part with no row of its own relies on the general claim: the
        # newest properties row. No row at all is reported as unrecorded.
        if registry.newest(check_id) is None and fallback is not None:
            check_id = fallback.check_id
        found.append(Reliance(check_id, where))
    if part.get("bind") is not None:
        found.append(Reliance(BIND_CHECK_ID, where))
    if placement.emphasis:
        found.append(Reliance(EMPHASIS_CHECK_ID, where))
    return found


def reliances(spec: dict[str, Any], cat: Catalogue, registry: Registry) -> list[Reliance]:
    """Every measured claim a spec relies on, in walk order: a section's
    factor row when the section is first seen, then each part's rows."""
    found: list[Reliance] = []
    seen_sections: set[int] = set()
    for placement in placements(spec):
        if placement.section not in seen_sections:
            seen_sections.add(placement.section)
            factor_id = FACTOR_CHECK_IDS.get(placement.factors)
            if factor_id is not None:
                found.append(Reliance(factor_id, f"section {placement.section}"))
        found.extend(_part_reliances(placement, cat, registry))
    return found


@dataclass(frozen=True)
class Staleness:
    """A relied-on claim whose newest row is too old, or missing."""

    check_id: str
    finding: Finding | None
    where: tuple[str, ...]
    age_days: int | None

    def message(self, max_age_days: int) -> str:
        relied = "relied on by " + ", ".join(self.where)
        if self.finding is None:
            return (
                f"{self.check_id}: no row in FINDINGS.md records this claim; {relied};"
                " re-probe: formwork gen discover, then formwork gen findprobe, and add the row"
            )
        return (
            f"{self.check_id}: measured {self.finding.measured.isoformat()},"
            f" {self.age_days} days ago (--findings-max-age {max_age_days}); {relied};"
            f" re-probe: {self.finding.reprobe}"
        )


def stale_findings(
    spec: dict[str, Any],
    cat: Catalogue,
    registry: Registry,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    today: dt.date | None = None,
) -> list[Staleness]:
    """The claims a spec relies on whose newest row is strictly older than
    ``max_age_days``, or has no row at all; one entry per check-id, in the
    order the spec first relies on them."""
    today = today or dt.date.today()
    grouped: dict[str, list[str]] = {}
    for reliance in reliances(spec, cat, registry):
        locations = grouped.setdefault(reliance.check_id, [])
        if reliance.where not in locations:
            locations.append(reliance.where)
    stale: list[Staleness] = []
    for check_id, where in grouped.items():
        finding = registry.newest(check_id)
        if finding is None:
            stale.append(Staleness(check_id, None, tuple(where), None))
            continue
        age = finding.age_days(today)
        if age > max_age_days:
            stale.append(Staleness(check_id, finding, tuple(where), age))
    return stale
