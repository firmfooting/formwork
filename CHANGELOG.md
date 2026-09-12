# Changelog

Dates are the dates of the commits on `main`. Every SharePoint behaviour named
here was measured on the shauntestazure sandbox on the date given; the
evidence lives under `tests/fixtures/`. The version lives once, in
`src/formwork/__init__.py` (`pyproject.toml` reads it dynamically); the
release-please workflow maintains the release PR, and merging it tags
`v<version>`, builds the wheel + sdist, attaches them to a GitHub release,
and publishes to PyPI as `formwork-sp`.

## Unreleased

Distribution, gate breadth and CI security posture (M11) and the M10
spec-template layer, folded with the 2026-09-08 adversarial reviews (Opus),
plus the 2026-09-11 swarm review (15 findings, issues #12-#26) folded with
the 2026-09-11 integration review (Opus). No version bump yet; the next bump
(0.7.0) will be the first to enjoy the golden version sentinel.

- Distribution: the package publishes to PyPI as `formwork-sp` (`formwork`
  was taken; the import package and CLI command stay `formwork`), cut by
  release-please and published by OIDC trusted publishing in `release.yml`
  (the filename is load-bearing — the PyPI pending publisher is bound to
  it). The version literal moved to `src/formwork/__init__.py` alone —
  pyproject reads it via `tool.setuptools.dynamic` — because a static
  `[project].version` would stale `uv.lock` on every bump and fail the
  `uv sync --locked` gate on the release merge.

- CI tests against Python 3.11, 3.12 and 3.13 on both Ubuntu and Windows —
  each leg logs `python -VV` so the interpreter under test is evidence, not
  a job name (review P1-1: the matrix existed but never selected the
  interpreter).
- A `release.yml` workflow: a `v*` tag runs the suite, asserts the tag
  matches `pyproject.toml`'s version, builds the wheel + sdist on the locked
  toolchain with caches disabled, verifies the wheel ships every Jinja
  template, and attaches the artifacts to a GitHub release
  (`gh release create` with `GH_REPO` set — review P1-2/P2-1). Actions are
  SHA-pinned; `permissions: {}` at the top level.
- Workflow security gate: `zizmor` (pinned 1.29.0) runs on every push/PR and
  fails on any finding; all workflows pass with zero findings.
- Dependencies are locked (`uv.lock` committed); CI installs with
  `uv sync --locked` so a PR cannot pass on locally-upgraded deps.
- The golden version sentinel: committed goldens are version-free (they
  carry `__FORMWORK_VERSION__` where a version literal belongs), the
  comparison folds only the generated side, and delimited folds keep
  measurement prose ("apply before 0.5.0") un-rewritten (review P2-3). A
  bump test patches the version to 9.9.9 and re-checks the goldens —
  a real independence test, replacing the tautology the first cut shipped
  (review P2-2).
- README install section points at GitHub release wheels — formwork is not
  on PyPI and the section no longer implies it is (review P1-3) — and the
  development commands are the uv ones CI runs.
- Spec templates (M10): a spec file is rendered as a Jinja2 template before
  the YAML parser sees it when the command carries `--vars`/`--set`, or the
  spec carries a top-level `vars:` key; with no flags the bytes reach the
  parser unchanged, so literal `{{ ... }}` in a plain spec keeps compiling.
  Precedence `--set` > the page's `vars:` file > the shared `--vars`;
  `StrictUndefined` refuses a missing variable by name; values are
  substituted as text (`& < > " '` survive verbatim, `--set` refuses a
  newline); refusals name files, positions and variables but never values.
  The payload stamp grew `varsFile`/`varsSha256`/`ownVarsFile`/
  `ownVarsSha256`/`setKeys` (names only, never values), so two payloads from
  one spec with different `--set` values are no longer stamp-identical. The
  M10 review's P2-7 asked for a README section and a changelog entry; both
  land with this one.

- The release build job installs its build frontend (`--with build==1.2.0`)
  instead of calling a module that was never a dependency: every tag failed
  with `No module named build` and the release job never ran (swarm #12, P1).
- `findprobe`'s filename verdict no longer embeds the server-assigned slug,
  which the server re-assigns on every create, so the row reports KEPT or
  DIFFERS from run-independent fields only (swarm #16, P1).
- A rendered spec whose YAML breaks no longer leaks substituted `--set`/vars
  values into the refusal or the committed manifest (swarm #15, P1); the
  position it names is the rendered text's, and says so (integration P2-3).
- The apply guard keys the site check on the stamp's shape, so a compile
  stamp that lost `discoveryWebId` is refused instead of silently creating on
  another web (swarm #20, P1).
- A path that cannot be read or written is one error line, exit 1 — and
  inside `compile-pages` it fails that page alone instead of aborting the run
  (swarm #14, P1).
- Case-only payload-name collisions are refused: on Windows or default macOS
  both pages wrote the same payload file and the second silently replaced the
  first while the manifest reported two `ok` rows (swarm #13, P2).
- An HTML text part whose href/src a browser resolves to a `javascript:` URL
  (character reference, embedded tab or newline) is refused, closing the route
  past the raw-text scan into the preview (swarm #21, P2).
- The provenance stamp records a page's own `vars:` file
  (`ownVarsFile`/`ownVarsSha256`) instead of attributing the canvas to the
  shared `--vars` file or to nothing (swarm #17, P2).
- `Catalogue.by_title` resolves a component from any preconfigured entry's
  titles, not just the first, so `component: Document library` no longer
  refuses with a false "run discover" (swarm #24, P2).
- `process` refuses a web-part control carrying neither a web-part
  `instanceId` nor a control-data `id`, instead of silently leaving its
  site-bound values unrewritten and unreported (swarm #22, P2).
- A rewritten control's `data-sp-htmlproperties` mirror now follows the new
  value (swarm #26); a mirror whose new value needs HTML escaping the
  plain-text mirror cannot carry is reported in the payload's `staleMirrors`
  and on stderr rather than left stale in silence (integration P2-2).
- The compiler refuses non-finite floats (`.inf`, `-.inf`) and non-string
  `displayTitle` values, which reached the canvas as bare `Infinity` and made
  `JSON.parse` reject the control data (swarm #25, P2).
- Styled-text reliance detection accepts any attribute spelling (`STYLE=`,
  `style =`, `CLASS=`, `<MARK>`), so a staleness warning is no longer dropped
  because of casing (swarm #23, P3).
- `tests/test_dsl.py` anchors its M5 fixture to the test file, so the suite
  passes from any working directory (swarm #19, P2).
- README documents the M10 templating surface and corrects the provenance
  field list (swarm #18, P2).

## [0.7.0](https://github.com/firmfooting/formwork/compare/v0.6.0...v0.7.0) (2026-09-12)


### Features

* because the user-facing change is pip install formwork-sp — this ([5152ded](https://github.com/firmfooting/formwork/commit/5152ded2c75ebb3904668463a9d48e0489132b95))
* **distribution:** M11 — wheel releases, 3.12/3.13 matrix, golden version sentinel ([020de82](https://github.com/firmfooting/formwork/commit/020de827ce07539ddae114c15038c6d1501c34b0))
* **distribution:** PyPI publication as formwork-sp, cut by release-please ([#28](https://github.com/firmfooting/formwork/issues/28)) ([5152ded](https://github.com/firmfooting/formwork/commit/5152ded2c75ebb3904668463a9d48e0489132b95))
* M10 — page specs as Jinja templates over a vars file ([79828ef](https://github.com/firmfooting/formwork/commit/79828ef137f209d582afb43c12b767fcacc68f18))
* M11 — distribution, gate breadth, golden version sentinel ([ffeaa2c](https://github.com/firmfooting/formwork/commit/ffeaa2c7a929f95c7923042116e2c32b6d1013d1))
* **templates:** M10 — page specs as Jinja templates over a vars file ([a392224](https://github.com/firmfooting/formwork/commit/a3922247d440ebefab8a34350a11cd4caf32627f))


### Bug Fixes

* **canvas:** sync the htmlproperties mirror a dirty render rewrites ([88281e4](https://github.com/firmfooting/formwork/commit/88281e41b3308b253f07eb699d4a9e5e810da9e4))
* **catalogue:** resolve a title from any preconfigured entry, not just the first ([90c599a](https://github.com/firmfooting/formwork/commit/90c599a1624d007fd885786bc55788a1ab698b77))
* **ci,release:** build job never obtained the build frontend — no tag could publish ([07f97ff](https://github.com/firmfooting/formwork/commit/07f97ff327f662ef5570393d8f01793fe1db9386))
* **ci,release:** M11 review — real matrix, gated release, honest README, delimited sentinel fold ([6f2e410](https://github.com/firmfooting/formwork/commit/6f2e4103e4dc803783771c4df5a4aad7bfa4c6ca))
* **ci:** accept release-please's linked changelog heading form ([#30](https://github.com/firmfooting/formwork/issues/30)) ([25b3418](https://github.com/firmfooting/formwork/commit/25b341871c2b1c3c0e05b83f4efb55c42970bc3b))
* **ci:** argparse invalid-choice message quoting changed in 3.12+ — assert either form ([fcb4472](https://github.com/firmfooting/formwork/commit/fcb4472723625dda039d2aec48963c63118921ff))
* **cli:** a path that cannot be read or written is a refusal, not a traceback ([640af31](https://github.com/firmfooting/formwork/commit/640af319311da4c822a9879aa7c5aeb2b07e4050))
* **compiler:** refuse an href/src a browser resolves to a script url ([d78d462](https://github.com/firmfooting/formwork/commit/d78d46241729b7156856b6a7609dbf31d51b8ddb))
* **compiler:** refuse non-finite floats and non-string displayTitle reaching the canvas ([dc83c12](https://github.com/firmfooting/formwork/commit/dc83c12c7550775fcaa972ee53e561868b7de011))
* **findings:** detect styled text HTML in any attribute spelling ([09e29fa](https://github.com/firmfooting/formwork/commit/09e29fa58655ae1975c54abaeb90d464c392ac56))
* **multipage:** refuse case-only payload-name collisions ([61d2072](https://github.com/firmfooting/formwork/commit/61d20723a8fd8c2498ee1d4e01a5edf2996e51fb))
* **provenance:** stamp a page own vars file, not just shared --vars ([cbab495](https://github.com/firmfooting/formwork/commit/cbab495baa3256eac41b43503e5506fc1f469358))
* **refs:** refuse a web-part control with no address instead of skipping it ([6298ee9](https://github.com/firmfooting/formwork/commit/6298ee98ac68a0d9bfc15c7987c4c4d58faa5a84))
* swarm integration review — merge [#16](https://github.com/firmfooting/formwork/issues/16)'s fix, report stale mirrors, honest YAML position, changelog ([984ade7](https://github.com/firmfooting/formwork/commit/984ade79de5635c0066bf0920de631577b139f16))
* swarm review — 14 verified findings, one per area ([ed0afb9](https://github.com/firmfooting/formwork/commit/ed0afb9121a379990512c15f47842fdd083a86ee))
* **templates:** apply guard fails closed on a compile stamp missing a web value ([a5e13a8](https://github.com/firmfooting/formwork/commit/a5e13a8ab8b1442555ca697d7ac8e4a44aa32d97))
* **templates:** M10 review — intent-keyed rendering, one read path, no escaped values, audited stamps ([12d8361](https://github.com/firmfooting/formwork/commit/12d83617e7de60f8cbcbb32f49f2f09586e86c42))
* **templates:** make the filename-slug findprobe verdict run-independent ([7d9bfd7](https://github.com/firmfooting/formwork/commit/7d9bfd7b75bfa51ce58d0fdbcc0259df5d6e1241))
* **templating:** a rendered spec that breaks YAML echoed the value; report position only ([2e87196](https://github.com/firmfooting/formwork/commit/2e8719669f89c281afe0197a0cd71724fdc8e7c4))


### Documentation

* document the M10 spec-template layer (--vars/--set, page vars:, template provenance) ([6f67142](https://github.com/firmfooting/formwork/commit/6f6714233e9e80ba8a16804bc6c049b2ddc0fb7b))
* **plan:** ledger — M10 built and review-folded (PR [#10](https://github.com/firmfooting/formwork/issues/10)) ([560dc6d](https://github.com/firmfooting/formwork/commit/560dc6d7088d41a5df77a61986f8a360730f4973))

## 0.6.0 — 2026-09-07

Section model and single serialiser (M9-as-built), consolidation only:

- `sections.py` is the one home for the section factor tables and the
  Section/SectionColumn/Placement tree; `compile`, `preview` and
  `compile-pages` all consume the same tree. Fixes the M7-review P1-2
  preview bug class structurally (preview can no longer re-derive
  geometry from `type` and drop column-2 parts).
- `canvas.py` is the single decode/encode for canvas attributes;
  `catalogue.py` decodes persisted blocks through it.
- No emitted-byte change: the golden suite diffs empty, which is the
  milestone's acceptance proof. Two intentional non-golden changes:
  `preview` labels `columns:` sections by their real layout
  (`two-thirds`/`columns`) instead of always `one`, and the
  unmeasured-factor warning now prints once per section instead of twice.
- Honest divergence note (m9 review P2-1): the compiler numbers
  `control_index` per SECTION; the M5 probe numbers per COLUMN. The
  render-side effect is unmeasured; reconcile before the SavePage
  emphasis slice.

## 0.5.0 — 2026-09-07

Payload provenance and the apply guard (M8), on top of 0.4.0's page-state
lane (M7): a payload now says which web it was compiled for, the apply
paste-in refuses to put it anywhere else, and the promoted state travels
where it was measured to persist.

### Provenance and the apply guard (M8)

- **Every payload carries a `provenance` stamp.** `formwork compile` and
  `compile-pages` write the formwork version, the SHA-256 of the discovery
  file's exact bytes, the discovery's web id, web URL and `discoveredAt`, the
  spec file name and an ISO compile time (`src/formwork/provenance.py`;
  `multipage.Provenance` moved there unchanged, and the manifest header
  `compiledWith` is the same five fields). `compile` prints the stamp on the
  line after "payload written". `formwork process` writes a shorter stamp
  (version, bundle name, `processedAt`): a copied page is bound to its
  mapping, not to a discovery document.
- **The apply paste-in refuses before it creates anything** (architecture
  review 2026-09-06, P2-1) when the payload has no stamp, when the web it
  runs on differs from the stamp's web id or URL (read the way discover
  records them: `web.d.Id`, and `location.origin` plus the server-relative
  root), or when the payload's formwork is newer than the script's own
  version. Each refusal lists the stamp's value beside the observed one.
  `FORCE_SITE_MISMATCH`, a constant at the top of the script documented in
  its header, overrides the site check only; the version check has no
  override. A process stamp gets the version check and a printed line that
  the site check does not apply.
- **`PromotedState` rides in the create body.** `--promoted-state 1` used to
  be a post-create item MERGE, which the page-state lane measured returning
  204 and reading back 0 on the Home layout (`page.page-state.promoted-state`;
  review 2026-09-07 P1-3 named the confound: write path or layout). Sent at
  create it persisted (new row `page.promoted-state.create-is-effective`,
  measured 2026-09-06 beside the Article layout,
  `discovery.pagestate.json#pageState.samples.3`). Apply now sends it inside
  the create body, sends nothing for 0, reads the stored value back beside the
  byte-exact check and warns, without throwing, when it differs. The Home
  layout with `PromotedState` at create is not yet a sample of its own.
  `createSitePage` in the shared prelude takes the extra create fields;
  `gen apply --promoted-state` still accepts only 0 or 1 and the generator
  refuses any other value.
- `FINDINGS.md`: the new row, with a findprobe verdict that names the layout
  it was measured beside; the promoted-state row cites the review that named
  its confound. Goldens regenerated for the prelude change, the apply body and
  the version; version 0.5.0.

## 0.4.0 — 2026-09-07

The findings registry (M6, PR #5) and page state and identity (M7).

### Page state and identity (M7)

- **The `pageState` discover lane** (`_probe_pagestate.js.j2`, shared by
  `formwork gen discover` and `formwork gen findprobe`): six scratch pages
  of the lane's own, each created through `sitepages/pages` with one
  identity or state field under test, read back as the page entity, the
  list item and the item's `HasUniqueRoleAssignments`, and recycled before
  the download. The samples: an explicit `FileName` beside a `Title`; a
  `FileName` with spaces and capitals, as an editor would type it; the
  `Article` layout; `PromotedState` 1 at create; `PromotedState` 1 by the
  item MERGE apply makes; and a fresh draft's `OData__UIVersionString`,
  `CheckoutUserId` and moderation status before and after `checkoutpage`
  and `publish`. The first page also carries `Description` and
  `BannerImageUrl` (item MERGE as `SP.FieldUrlValue`, then the page model's
  `SavePageAsDraft` with no canvas). Every step records requested and
  persisted by page id; a refused create is a sample with the server's
  reason, never a failed run. `unmeasured` names `navigation`,
  `permission-break`, `banner-json` and `rendering`. Additive under
  `formwork.discovery/v1`; `catalogue.PageStateSample` reads it, tolerant
  of its absence.
- **`formwork compile-pages <dir-or-glob> <discovery> [--out-dir]`**: every
  `*.yaml` compiles against one discovery document, one payload per spec,
  plus `formwork-pages.json` with a shared provenance header (formwork
  version, discovery SHA-256, web id and URL, discovery timestamp) and a
  per-page result. One bad spec fails alone; exit 1 if any did. No link
  resolution, no transaction, no cross-page ordering (README, "Multi-page").
- **`navigation` refused at parse.** No `page.navigation.*` row exists, so
  the key is refused naming the row pattern and the discover lane that
  would measure it (`dsl.UNMEASURED_PAGE_KEYS`, kept apart from the
  measured `UNENCODABLE_PAGE_KEYS`).
- `FINDINGS.md` rows for the page-state claims are not written yet: a row
  cites a fixture, and the lane has not run live. The operator's
  `formwork gen discover` run supplies `tests/fixtures/<capture>#pageState`
  and the rows follow it, measured on that date.
- Version 0.4.0 in `pyproject.toml` and `formwork.__version__`; the goldens
  carry the string, and discover and findprobe carry the lane.

### Findings registry (M6)

- **`FINDINGS.md`**, the findings registry: one row per measured claim with
  a check-id (`page.<scope>.<question>`), the claim, the measured date, the
  compact result, an evidence pointer into a fixture and the re-probe
  command. Seeded with the 17 claims of the 2026-09-06 runs, the
  hand-measured section-emphasis mechanism and the M5 property, layout and
  list-binding rows included. `src/formwork/findings.py` parses and
  validates it on load.
- **Compile staleness warning.** `formwork compile` warns, per check-id,
  when the newest row a spec relies on is older than `--findings-max-age`
  (default 90 days), naming the parts that rely on it, its age and the
  re-probe command. Never a refusal. Silent when no `FINDINGS.md` is in the
  working directory; `--findings` names one explicitly.
- **`formwork gen findprobe`**, the re-probe lane: re-runs every recorded
  measurement (the discover legs, now the shared partials
  `_probe_setup.js.j2` and `_probe_legs.js.j2`, plus a SavePage
  section-emphasis leg on a second scratch page), prints "same" or
  "DIFFERS" per row and downloads `formwork-findprobe.json`. Golden
  `tests/fixtures/expected/findprobe.js`.
- Discover's comments cite the registry rows where they used to name the
  measurement as pending; the paste-in's bytes otherwise stay as before.

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
