"""Component catalogue parsed from a discovery bundle.

``GetClientSideWebParts`` (measured 2026-09-06, shauntestazure sandbox) returns
every placeable client-side component with an embedded ``Manifest`` JSON
string: alias, title, component type, hidden flag, and preconfigured entries
whose first entry supplies default properties. The catalogue is the authority
the page DSL compiles against — nothing is placed that the live site did not
declare placeable.

The discover script also places two text controls (``controlType`` 4, not
web parts) with known HTML and reads back what SharePoint persisted. They
arrive under the additive ``textControls`` key and are carried here as
:class:`TextControlSample` pairs so the shape the compiler emits can be
checked against a measurement rather than a guess. A discovery document from
before that probe has no such key and parses exactly as it did.
"""

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Component:
    component_id: str
    alias: str
    title: str
    hidden: bool
    component_type: int  # 1 = web part, 2 = extension (per wire field ComponentType)
    default_properties: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class TextControlSample:
    """One text control the discover script placed, as sent and as kept.

    ``requested`` is the canvas block the script wrote; ``persisted`` is the
    block SharePoint stored for the same control id, verbatim, or None when
    the readback did not contain it. The persisted bytes are the measurement
    of the text-control shape; nothing here interprets them.
    """

    control_id: str
    html: str
    requested: str
    persisted: str | None

    def persisted_matches(self) -> bool | None:
        """Whether SharePoint kept this sample byte-for-byte after normalising.

        Measured live (shauntestazure, 2026-09-06): SharePoint rewrites ``:``
        as ``&#58;`` inside a text control's inner HTML — the same entity
        style the canvas attributes use — and leaves everything else
        byte-identical. So equality is judged after folding that one
        normalisation back, and only that one: any other difference is a
        real shape change and returns False.

        None when the sample was never persisted (or the stored bytes could
        not be read), in which case no claim is made.
        """
        if self.persisted is None:
            return None
        if self.persisted == self.requested:
            return True
        return self.persisted.replace("&#58;", ":") == self.requested


@dataclass(frozen=True)
class Catalogue:
    components: tuple[Component, ...]
    text_controls: tuple[TextControlSample, ...] = ()

    @property
    def count(self) -> int:
        return len(self.components)

    def by_alias(self, alias: str) -> Component:
        for c in self.components:
            if c.alias == alias:
                return c
        raise KeyError(f"component alias not in catalogue: {alias!r}")

    def by_title(self, title: str) -> Component:
        matches = [c for c in self.components if c.title == title]
        if not matches:
            raise KeyError(f"component title not in catalogue: {title!r}")
        if len(matches) > 1:
            raise KeyError(
                f"component title {title!r} is ambiguous across "
                f"{len(matches)} components; use the alias instead"
            )
        return matches[0]


def parse_discovery(discovery: dict[str, Any]) -> Catalogue:
    """Build a catalogue from a formwork discovery document."""
    if discovery.get("schema") != "formwork.discovery/v1":
        raise ValueError(
            f"unsupported discovery schema: {discovery.get('schema')!r} "
            "(expected 'formwork.discovery/v1')"
        )

    components: list[Component] = []
    for raw in discovery.get("components", []):
        manifest = json.loads(raw.get("Manifest") or "{}")
        entries = manifest.get("preconfiguredEntries") or []
        first = entries[0] if entries else {}
        components.append(
            Component(
                component_id=raw.get("Id") or manifest.get("id", ""),
                alias=manifest.get("alias", ""),
                title=(first.get("title") or {}).get("default", ""),
                hidden=bool(manifest.get("isHidden", False)),
                component_type=int(raw.get("ComponentType", 0)),
                default_properties=dict(first.get("properties") or {}),
                description=(first.get("description") or {}).get("default", ""),
            )
        )
    return Catalogue(
        components=tuple(components),
        text_controls=_text_controls(discovery.get("textControls")),
    )


def _text_controls(raw: Any) -> tuple[TextControlSample, ...]:
    """Pair each requested text control with its persisted block by id.

    Tolerant by design: the key is additive, and a document that predates
    the probe (or a run whose readback lost the controls) yields an empty
    tuple or samples with ``persisted`` None, never an error.
    """
    if not isinstance(raw, dict):
        return ()
    persisted_by_id: dict[str, str] = {}
    persisted_raw = raw.get("persisted")
    if not isinstance(persisted_raw, list):
        persisted_raw = []
    for kept in persisted_raw:
        if isinstance(kept, dict) and isinstance(kept.get("canvas"), str):
            persisted_by_id[str(kept.get("id", ""))] = kept["canvas"]
    samples: list[TextControlSample] = []
    requested_raw = raw.get("requested")
    if not isinstance(requested_raw, list):
        requested_raw = []
    for sent in requested_raw:
        if not isinstance(sent, dict):
            continue
        control_id = str(sent.get("id", ""))
        samples.append(
            TextControlSample(
                control_id=control_id,
                html=str(sent.get("html", "")),
                requested=str(sent.get("canvas", "")),
                persisted=persisted_by_id.get(control_id),
            )
        )
    return tuple(samples)
