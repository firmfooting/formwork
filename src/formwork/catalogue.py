"""Component catalogue parsed from a discovery bundle.

``GetClientSideWebParts`` (measured 2026-09-06, shauntestazure sandbox) returns
every placeable client-side component with an embedded ``Manifest`` JSON
string: alias, title, component type, hidden flag, and preconfigured entries
whose first entry supplies default properties. The catalogue is the authority
the page DSL compiles against — nothing is placed that the live site did not
declare placeable.
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


@dataclass(frozen=True)
class Catalogue:
    components: tuple[Component, ...]

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
            )
        )
    return Catalogue(components=tuple(components))
