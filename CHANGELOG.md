# Changelog

Dates are the dates of the commits on `main`. Every SharePoint behaviour named
here was measured on the shauntestazure sandbox on the date given; the
evidence lives under `tests/fixtures/`. No tags have been cut; releases are
the version literal in `pyproject.toml` and `src/formwork/__init__.py`.

## 0.3.0 — 2026-09-06

Everything merged since 0.2.1: full-page authoring (PR #2, milestones M1–M3)
and the M3-DSL and M4 release work.

### Added

- **Text parts.** A part may be `text:` instead of `component:`; it compiles
  to a text control (`controlType` 4, `editorType` CKEditor). Text is HTML when
  it starts with `<` or carries `format: html`, otherwise a markdown subset
  (`#`–`####` headings, paragraphs, `-`/`*` and `1.` lists, bold, italic,
  links). Anything else refuses with the line number. On both paths
  `<script>`, `<style>`, `<iframe>`, `<textarea>`, `<svg>`, comments, inline
  `on*=` handlers, `javascript:`/`data:`/`vbscript:` URLs, `data-sp-`
  attributes and control characters refuse.
- **`formwork preview`** renders a spec to a standalone HTML page with no
  SharePoint calls; `--discovery` resolves titles and descriptions from the
  catalogue.
- **Discover probe for text and styling.** The discover paste-in places two
  text controls with known HTML (`textControls`), seven styled-text samples,
  five one-control section variants and one page-model save attempt
  (`styling`), recording each sample as requested and as persisted.
- **Compile gate on the text measurement.** Text parts compile only against a
  discovery document whose text samples persisted with at most the `:` to
  `&#58;` rewrite (measured 2026-09-06); a document without the measurement,
  or with any other difference, refuses and says why.
- **`emphasis:` on component parts.** `emphasis: {zoneEmphasis: N}` or
  `emphasis: N`, N in 1–4, compiled into the control's `emphasis` block.
  Measured 2026-09-06 (`styling.sectionSamples`): 2 and 3 persisted
  byte-for-byte through the item MERGE. `formwork compile` prints the value.
- **Refusals for what compile cannot encode**, each naming its measurement:
  `emphasis` on a section (takes effect only through the page model's SavePage
  with zoneIds, measured 2026-09-06), `background` and `spacing` on a section
  and `theme` on the page (`styling.unmeasured`), `emphasis` on a text part
  (every measured text control carried `{}`).
- **Evidence fixtures.** `tests/fixtures/discovery.styling.json` is a live
  discover run carrying the styling probe; `tests/fixtures/savepage-section-emphasis.json`
  is the editor's own SavePage body for an emphasised page.
  `tests/test_styling_evidence.py` ties the DSL and the README to them.
- The paste-ins and the preview are Jinja templates; the three scripts share
  one prelude partial, `_prelude.js.j2`, and stay byte-exact against the
  goldens.
- A second apply golden, `apply-payload.js`, embedding a payload with braces,
  quotes, a backslash, an apostrophe, `</script>` and a non-ASCII letter
  (review P3-4).
- Tests pinning the four transport-fact citations and their dates in the
  prelude template (review P3-8), `__version__` against `pyproject.toml` and
  this file, and one-line CLI errors for `compile` and `preview` (review
  P3-6).
- This changelog.

### Changed

- README rewritten around the authoring workflow (discover, declare, compile,
  preview, apply); copying a page is the second workflow; every measured
  behaviour is collected under one dated section.
- `persisted_matches()` folds the `:` rewrite on both sides of the comparison.
- Version 0.3.0 in `pyproject.toml` and `formwork.__version__`; the goldens
  carry the new string.

### Removed

- The unused `postJson` helper from the paste-in prelude (review P3-1). The
  goldens differ from 0.2.1 by that removal and the version string only.

## 0.2.1 — 2026-09-06

Transport hardening, PR #1. The version literal stayed at 0.2.0 through this
release; it is recorded here by its content.

### Added

- Four transport facts ported from dbml-sharepoint v0.4.0 partials into the
  paste-in prelude, each cited in the template and pinned by a test on every
  generated script: throttled browser sessions are redirected to the
  throttling page rather than answered 429, detected on the final URL, with
  one gate holding every request and a Retry-After-aware retry
  (`_http.js.j2:36-44` and `45-63`); the server's reason is read from
  `error.message.value` on every non-OK response (`_http.js.j2:25-34`, live
  finding 2026-07-24); the `contextinfo` response is parsed step by step
  instead of dereferenced blind (`_digest_cached.js.j2:9-42`); apostrophes in
  OData literals are doubled and URI-encoded (`_site_guard.js.j2:24-27`).
- Goldens for the three generated scripts under `tests/fixtures/expected/`,
  compared byte for byte; regenerate with `python tests/test_generator.py`.
- A paste-in API advisory under `.hermes/`.

### Fixed

- Extract decodes the percent-encoded page path before OData-quoting it, so a
  page named like `Bob's page.aspx` is found instead of matching zero rows
  (review P2-1).
- The throttle pins match the call sites and the detection expression rather
  than the bare definitions (review P2-2).

## 0.2.0 — 2026-09-06

### Added

- `formwork gen discover`: a paste-in that enumerates `GetClientSideWebParts`,
  places one control per component on a scratch page across one-, two- and
  three-column sections, reads back the persisted canvas, recycles the page
  and downloads the catalogue. Live: 73 placed, 73 stored.
- `formwork components`: list a discovery document's components (alias,
  title, hidden, defaults).
- `formwork compile`: page-spec YAML to an apply payload, resolved against the
  live catalogue; unknown or hidden components refuse to compile.
- Measured corrections in every template: an unprefixed `/_api` from a
  sub-site page resolves to the tenant root, so the prefix is derived from
  `location`; `contextinfo` is POST-only; a list-item POST into Site Pages is
  refused; `Files/add` of an `.aspx` is 403, so pages are created through
  `/_api/sitepages/pages`.

### Fixed

- `types-PyYAML` added to the dev extras so mypy sees the YAML stubs.

## 0.1.0 — 2026-09-06

### Added

- Canvas parser and renderer with a byte-exact round-trip against a
  live-captured modern page (`tests/fixtures/collabhome.*`, extracted
  2026-09-05).
- Site-bound reference scan and rewrite plan; `formwork inspect` and
  `formwork process`.
- `formwork gen extract` and `formwork gen apply` paste-in generators, gated
  with `node --check`.
