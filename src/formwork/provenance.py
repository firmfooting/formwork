"""Payload provenance (M8): what compiled this payload, and for which web.

``formwork compile`` and ``compile-pages`` stamp every payload with a
``provenance`` block, and the apply paste-in reads it before it creates
anything (architecture review 2026-09-06, P2-1: nothing bound a payload to
the site it was compiled against). The fields, and the role each plays:

* ``formwork``: the compiling version. Apply refuses a payload compiled by a
  NEWER formwork than the script's own version constant, because a newer
  compile may rely on a measurement the older script does not carry. That
  refusal has no override.
* ``discoverySha256``: SHA-256 over the exact bytes of the discovery file
  named on the command line. Nothing on the target web can be compared with
  it; it is the pointer back to the catalogue the canvas was compiled from,
  and a refusal quotes it.
* ``discoveryWebId`` and ``discoveryWebUrl``: the web the discovery document
  records (``web.id`` is ``web.d.Id``; ``web.url`` is ``location.origin``
  plus the web's server-relative root, discover.js.j2). Apply reads the same
  two values on the web it runs from and refuses when either differs;
  ``FORCE_SITE_MISMATCH`` in the script overrides this check and only this
  check.
* ``discoveredAt``: the document's own timestamp, so a refusal can say which
  discovery run the payload came from.
* ``spec``: the spec file's name; ``compiledAt``: when, ISO 8601 UTC.

The first five fields are the header ``compile-pages`` writes once into its
manifest as ``compiledWith`` (M7); a payload carries the header plus the two
per-payload fields. ``formwork process`` writes a shorter stamp
(``formwork``, ``bundle``, ``processedAt``): a copied page is bound to its
mapping, not to a discovery document, so apply runs the version check on it
and prints that the site check does not apply.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__

#: The payload key the stamp lives under; the apply script reads
#: ``PAYLOAD.provenance``.
PAYLOAD_KEY = "provenance"


@dataclass(frozen=True)
class Provenance:
    """The shared header: which formwork compiled against which discovery."""

    formwork: str
    discovery_sha256: str
    discovery_web_id: str
    discovery_web_url: str
    discovered_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "formwork": self.formwork,
            "discoverySha256": self.discovery_sha256,
            "discoveryWebId": self.discovery_web_id,
            "discoveryWebUrl": self.discovery_web_url,
            "discoveredAt": self.discovered_at,
        }


def provenance(discovery_bytes: bytes | str, discovery: dict[str, Any]) -> Provenance:
    """The header for a discovery document, hashed over its exact bytes.

    Pass the bytes as read from disk. A ``str`` is hashed as UTF-8, which is
    the same digest only where reading translated nothing (review 2026-09-07
    P2-7: ``read_text`` folds CRLF on Windows; ``read_bytes`` does not).
    """
    raw = discovery_bytes.encode("utf-8") if isinstance(discovery_bytes, str) else discovery_bytes
    web = discovery.get("web")
    web = web if isinstance(web, dict) else {}
    return Provenance(
        formwork=__version__,
        discovery_sha256=hashlib.sha256(raw).hexdigest(),
        discovery_web_id=str(web.get("id") or ""),
        discovery_web_url=str(web.get("url") or ""),
        discovered_at=str(discovery.get("discoveredAt") or ""),
    )


@dataclass(frozen=True)
class TemplateProvenance:
    """The template layer of a compile (M10, review 2026-09-08 P2-5).

    Two payloads compiled from the same spec and discovery with different
    ``--set`` values must not carry identical stamps. Values never go in
    (they are the secret-shaped part); the vars file is hashed over its
    exact bytes like the discovery document, and ``--set`` contributes its
    sorted KEY NAMES as the audit trail.
    """

    vars_name: str = ""
    vars_sha256: str = ""
    set_keys: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, str]:
        return {
            "varsFile": self.vars_name,
            "varsSha256": self.vars_sha256,
            "setKeys": ",".join(self.set_keys),
        }

    @property
    def empty(self) -> bool:
        return not (self.vars_name or self.vars_sha256 or self.set_keys)


def template_provenance(
    vars_path: Path | str | None,
    set_pairs: Sequence[str] | None,
) -> TemplateProvenance:
    """The template-layer stamp: file name + sha256 of exact bytes, and the
    sorted --set key names. Never values."""
    keys = tuple(sorted({pair.partition("=")[0] for pair in (set_pairs or ())}))
    if not vars_path:
        return TemplateProvenance(set_keys=keys)
    raw = Path(vars_path).read_bytes()
    return TemplateProvenance(
        vars_name=Path(vars_path).name,
        vars_sha256=hashlib.sha256(raw).hexdigest(),
        set_keys=keys,
    )


@dataclass(frozen=True)
class PayloadStamp:
    """One payload's provenance: the shared header plus which spec, when,
    and (M10) which template variables produced it."""

    header: Provenance
    spec: str
    compiled_at: str
    template: TemplateProvenance | None = None

    def as_dict(self) -> dict[str, str]:
        out = {**self.header.as_dict(), "spec": self.spec, "compiledAt": self.compiled_at}
        if self.template is not None and not self.template.empty:
            out.update(self.template.as_dict())
        return out

    def one_liner(self) -> str:
        """What ``compile`` prints after "payload written": the stamp, one line.

        The digest is shortened to twelve characters as on the
        ``compile-pages`` line; the payload holds the full value.
        """
        h = self.header
        line = (
            f"provenance: formwork {h.formwork} compiled {self.spec} at {self.compiled_at}"
            f" against discovery sha256 {h.discovery_sha256[:12]}"
            f" (web {h.discovery_web_id or '?'} at {h.discovery_web_url or '?'},"
            f" discovered {h.discovered_at or '?'})"
        )
        if self.template is not None and not self.template.empty:
            t = self.template
            bits = [f" vars {t.vars_name or '-'} sha256 {t.vars_sha256[:12] or '-'}"]
            if t.set_keys:
                bits.append(f" set[{','.join(t.set_keys)}]")
            line += ";" + "".join(bits)
        return line


def now_iso() -> str:
    """The stamp clock: ISO 8601, UTC, whole seconds, ``Z`` suffix."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def payload_stamp(
    header: Provenance,
    spec: str,
    compiled_at: str | None = None,
    template: TemplateProvenance | None = None,
) -> PayloadStamp:
    return PayloadStamp(
        header=header, spec=spec, compiled_at=compiled_at or now_iso(), template=template
    )


def process_stamp(bundle: str, processed_at: str | None = None) -> dict[str, str]:
    """The stamp ``process`` writes: bound to a formwork version, not to a web."""
    return {"formwork": __version__, "bundle": bundle, "processedAt": processed_at or now_iso()}
