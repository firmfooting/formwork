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
from dataclasses import dataclass
from datetime import UTC, datetime
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
class PayloadStamp:
    """One payload's provenance: the shared header plus which spec, and when."""

    header: Provenance
    spec: str
    compiled_at: str

    def as_dict(self) -> dict[str, str]:
        return {**self.header.as_dict(), "spec": self.spec, "compiledAt": self.compiled_at}

    def one_liner(self) -> str:
        """What ``compile`` prints after "payload written": the stamp, one line.

        The digest is shortened to twelve characters as on the
        ``compile-pages`` line; the payload holds the full value.
        """
        h = self.header
        return (
            f"provenance: formwork {h.formwork} compiled {self.spec} at {self.compiled_at}"
            f" against discovery sha256 {h.discovery_sha256[:12]}"
            f" (web {h.discovery_web_id or '?'} at {h.discovery_web_url or '?'},"
            f" discovered {h.discovered_at or '?'})"
        )


def now_iso() -> str:
    """The stamp clock: ISO 8601, UTC, whole seconds, ``Z`` suffix."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def payload_stamp(header: Provenance, spec: str, compiled_at: str | None = None) -> PayloadStamp:
    return PayloadStamp(header=header, spec=spec, compiled_at=compiled_at or now_iso())


def process_stamp(bundle: str, processed_at: str | None = None) -> dict[str, str]:
    """The stamp ``process`` writes: bound to a formwork version, not to a web."""
    return {"formwork": __version__, "bundle": bundle, "processedAt": processed_at or now_iso()}
