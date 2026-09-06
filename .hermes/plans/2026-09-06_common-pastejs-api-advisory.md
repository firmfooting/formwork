# Advisory: should formwork, dbml-sharepoint and dbml-sharepoint-test-agent share a common API?

Date: 2026-09-06. Read-only review of the three working trees. Every substantive
claim cites a file; claims I could not verify by reading are marked UNVERIFIED.

Preconditions not met: the Hindsight MCP tools (`mcp__hindsight__*`,
`mcp__hindsight-hermes__*`) were not registered in this session, so Hermes
memory and the repo knowledge pages were not consulted. If Shaun has a standing
rule about cross-repo packaging, it is not reflected here.

## 1. Verdict

Partial, and narrow. Do not create a shared package, a shared repo, or a shared
Python emission layer. Two things are worth sharing, in this order. First, the
probe and evidence contract that dbml-sharepoint already owns and the test-agent
already validates (IIFE shape, four guards, `RESULTS` declared before any
question, `expect`/`record`/`report`, `// finding:` header lines, the
`<surface>.<scope>.<question>` check-id grammar). formwork should conform to it
so its measured SharePoint behaviour becomes re-runnable evidence on the Camofox
lane. Second, the measured transport facts in dbml-sharepoint's HTTP partials
(throttle-page redirect, `error.message.value` shaping, contextinfo parse
hardening, OData literal quoting), ported into formwork's prelude as cited,
dated comments with pinned tests, not as a shared runtime. A vendored,
checksum-pinned transport prelude is a possible later step once a third
consumer or a fourth formwork script exists; it is not justified today.

## 2. Evidence

### 2.1 formwork (v0.2.0, four commits, days old)

- The whole transport is one Python string constant, `_JS_PRELUDE`
  (`src/formwork/generator.py:30-111`), prepended to three bodies. Bodies are
  plain strings; apply uses `str.format` with doubled braces
  (`generator.py:171-228`, `418-422`). No Jinja, no template loader.
- Its measured constraints are dated and cited to the sandbox
  (`generator.py:20-29`): bare `/_api/` from a sub-site page resolves against
  the tenant root; contextinfo is POST-only (GET gives 405); Site Pages is a
  document library so list-item POST and `Files/add` of `.aspx` are refused;
  pages are created through `/_api/sitepages/pages`.
- Site resolution derives the prefix from `location.pathname` matching
  `/SitePages/` and refuses to run elsewhere (`generator.py:36-41`). It does not
  use `_spPageContextInfo` at all. This is a modern-page anchor.
- Concurrency uses a real etag: MERGE with `If-Match: item.__metadata.etag`
  (`generator.py:88-104`, `188-205`), then a byte-exact readback
  (`generator.py:211-225`).
- `getJson`/`postJson` throw `"GET <url> -> <status>"` with no retry, no
  throttle detection and no server-message extraction (`generator.py:42-55`).
  `getDigest` POSTs per use with no cache and a blind `.d.GetContextWebInformation`
  dereference (`generator.py:57-59`).
- The test gate is `node --check` plus string-presence assertions; one of them
  pins the site-prefix finding by counting `"/_api` occurrences
  (`tests/test_generator.py:26-45`). There is no golden file.
- Document schemas are formwork's own: `formwork.bundle/v1` (`bundle.py:63-67`),
  `formwork.discovery/v1` (`catalogue.py:52-58`), `formwork.payload/v1`
  (`cli.py:63-72`, `118-120`). The discovery document is a component catalogue
  plus one stored canvas; it has no question/outcome rows.
- Packaging: setuptools, Python >=3.11, one runtime dependency (pyyaml)
  (`pyproject.toml:1-13`).
- `.hermes/` did not exist before this report was written.

### 2.2 dbml-sharepoint (v0.4.0 released 2026-09-03, Beta, 24 probes)

- The doctrine that answers this question is already written down. The
  partial-earning rule: "A template partial is shared only when every including
  script needs it identically: identity/provenance, site guard, digest, HTTP
  transport. Phase and domain logic stays with its phase"
  (`website/docs/development/philosophy.md:77-85`). Live findings are law and
  must land as a dated comment, a pinned test and a design-doc revision
  (`philosophy.md:33-47`). One source of truth per fact (`philosophy.md:94-99`).
- The shared transport is a set of Jinja partials included in order by
  `deploy.js.j2:60-68`: `_site_guard.js.j2`, `_http.js.j2`, `_http_write.js.j2`,
  `_http_batch.js.j2`, `_digest_cached.js.j2`. Each carries measured facts:
  - `_http.js.j2:8-15`, `36-44`: a throttled browser session is redirected to
    `/_layouts/15/throttle.htm`, which arrives as 406 because the script asked
    for JSON; retry keys on the final URL, not the status. One throttle gate
    holds every lane (`_http.js.j2:45-63`).
  - `_http.js.j2:25-34`: `spError` extracts `error.message.value`; a bare
    status "left a blocked run undiagnosable (live finding 2026-07-24)".
  - `_digest_cached.js.j2:8-42`: the one place contextinfo is parsed; a second
    copy "is what reported #282 as a TypeError". Cache refreshes 60 s before
    `FormDigestTimeoutSeconds`.
  - `_site_guard.js.j2:10-23`: SITE_URL is baked in; the guard requires
    `_spPageContextInfo.webServerRelativeUrl` to match exactly, else abort.
  - `_cross_web.js.j2:8-18`: "the modern pages this is pasted on (CollabHome)
    do not define [`_spPageContextInfo`] (measured 2026-08-26)", and a form
    digest is per-web (live finding 2026-09-05, 403 on a foreign web's digest).
  - The operator manifest tells the operator to open a CLASSIC page for this
    reason (`manifest.md.j2:49-52`).
- Every write uses `IF-MATCH: '*'` (`columns.js.j2:182`, `_verify_body.js.j2:46`,
  `deploy/_helpers.js.j2:45`, `rollback.js.j2:147`, and more). Nothing in the
  templates reads an item etag. This is deliberate reconcile semantics, the
  opposite of formwork's byte-exact concurrency check.
- The probe harness is a second, separately maintained transport in the same
  repo. `test/manual/templates/_probe_harness.js.j2` (v1) has no SITE_URL
  constant on purpose because "a tenant URL committed to this repo has leaked
  twice" (`:19-22`), reads `_spPageContextInfo.webAbsoluteUrl` (`:23-28`),
  fetches the digest uncached (`:32-39`), and returns refusals as values rather
  than throwing because "a 400 here is the finding, not a crash" (`:99-105`).
  `isRefusal` is defined by exclusion, with the observation that every recorded
  SharePoint refusal came back 500 (`:58-84`). `_probe_core_v2.js.j2` adds the
  CONFIRMED/ALLOW_WRITES gates, `fetchWithRetry`, a cached digest and a
  `merge` helper with `IF-MATCH: '*'` (`:8-17`, `:37-69`, `:122-126`).
- The repo already solved drift between copies of the harness, inside one repo:
  "the harness they share ... was copied into four scripts and had already
  drifted between them" (`test/manual/render_probes.py:4-6`). The fix is Jinja
  includes, a revision hash over the transitive template sources printed at run
  time (`render_probes.py:52-81`, `_probe_core_v2.js.j2:20`), and a test that
  fails on a stale rendered probe (`test/test_probes.py:89-107`).
- The evidence vocabulary has one authority: `test/manual/SURFACES.md` "is the
  sole authority for the surface list, the scope registries and the check-id
  grammar. dbml-sharepoint validates its probes against it and
  dbml-sharepoint-test-agent validates its evidence against it" (`:8-10`).
  Adding a surface "should be rare ... worth discussing before it is worth
  encoding" (`:12-13`). Ids are `<surface>.<scope>.<question>`, compared
  byte-for-byte (`:20-45`). `probe-catalog.json` is schema 1.2 and names each
  probe's harness (`shared-v1`, `shared-v2`, `helper`) and authority (`:1-15`).
- dbml-sharepoint has its own read-only extract script that downloads site
  state as JSON for the CLI to consume (`templates/extract.js.j2:1-42`). It
  includes the same site guard and HTTP partials as deploy. This is the closest
  analogue to formwork's extract and discover flows.
- The word "finding" means two things here: build-time validator findings
  (`analysis/findings.py:79-160`, `FindingCode` with declared severity, 194
  rules per `AGENTS.md:165`) and probe findings (header lines and catalogue
  check ids). Only the second is relevant to this question.
- No page-surface code exists: `SitePages`, `CanvasContent1` and
  `GetClientSideWebParts` do not appear in `src/` except as a URL-cutting
  segment in `generators/reportgen.py:554-562`.
- Gates: pytest, ruff, mypy, j2lint, markdownlint (`AGENTS.md:40-50`); the
  deploy golden fails on any template change until deliberately regenerated
  (`AGENTS.md:131-134`). Python >=3.13; jinja2, typer, rich, pydbml
  (`pyproject.toml:6`, `29-39`). `templating.py:36-69` binds typemap facts
  into the Jinja environment as globals, so the environment is not generic.

### 2.3 dbml-sharepoint-test-agent (v0.1.0, private per its README)

- Ownership is stated: "The dbml-sharepoint repository remains the owner of
  probe questions, templates, generated JavaScript and harness semantics"
  (`AGENTS.md:3`).
- Coupling to upstream is by file contract, not by package. No Python file
  imports `dbml_sharepoint` (grep over the tree, zero matches); the runtime has
  no dependencies at all (`pyproject.toml:9-13`). The contract is regexes over
  probe source (`runner.py:14-16`: the four guards, the `RESULTS` declaration,
  the IIFE opener), the catalogue loader (`catalog.py`), and SHA-256 pins of
  reviewed read-only probe bytes with PR-numbered comments (`catalog.py:27-50`).
- `contract.py:86-141` prepares every probe in a directory under a policy and
  keeps an exact exception list; a probe that starts satisfying the contract
  fails the check until its exception is removed (`:130-133`). CI runs it
  against upstream main (`docs/architecture.md:46`;
  `scripts/check_upstream_contract.py:13` hardcodes `minimum_scripts=20`).
- Surfaces are mirrored from SURFACES.md; an unknown surface is refused
  (`catalog.py:56-63`).
- Site validation accepts only `https://*.sharepoint.com/sites/<name>` or
  `/teams/<name>` (`runner.py:148-193`). The owner lane runs from the classic
  settings page and checks `_spPageContextInfo.webAbsoluteUrl` by exact match;
  the reader lane runs from Site Contents with a prefix check (`AGENTS.md:11-12`).
  Neither lane anchors on a modern page.
- The deploy lane is a contract on build shape: one top-level IIFE, a baked
  `SITE_URL`, a `DEBUG` const, a `[DONE]` line, kind detected from the
  `[SP-DEPLOY]`/`[SP-ROLLBACK]`/`[SP-VERIFY]` log prefix (`deploy.py:83-170`).
- Evidence flows back to the owner of the question: "The durable public result
  belongs back in dbml-sharepoint as a dated code comment, test, probe-header
  run record or issue finding" (`docs/architecture.md:63`). Probe-header
  findings use `// finding: <slug> — <claim>` and are marked captured when a
  review with a matching check id exists (`probe_findings.py:1-15`, `54-86`).
  Human-validation issues may only be filed in the test-agent repo
  (`github_handoff.py:52-60`). The publish bridge that PRs evidence into
  dbml-sharepoint was not read: UNVERIFIED beyond the brief's description.

## 3. Recommended architecture

Evaluate the four candidate meanings separately.

**(a) Shared JS transport runtime: no shared runtime; share the facts.**
dbml-sharepoint's own partial-earning rule requires identical need, and the
needs are not identical. formwork anchors on a modern page and cannot use the
`_spPageContextInfo` guard that dbml-sharepoint requires and that
dbml-sharepoint itself measured absent on a modern page. formwork needs real
etags; dbml-sharepoint never reads one. formwork must not carry a SITE_URL;
deploy must. Even inside dbml-sharepoint the probe harness and the deploy
transport are kept apart because a refusal is a finding in one and a failure in
the other. A transport that satisfied all three would be a third thing that
fits none of them well. What transfers cleanly is knowledge: throttle-page
detection, `spError`, the hardened contextinfo parse, `odataName`. Port each
into `_JS_PRELUDE` with a comment naming the dbml-sharepoint file and the dated
finding, and pin each with a test in `tests/test_generator.py` the way the
site-prefix rule is pinned today.

**(b) Shared Python emission layer: no.** `script_env()` is coupled to
dbml-sharepoint's typemap globals and to Python 3.13; formwork has three
scripts, no Jinja, and a 3.11 floor. The value is nil and the coupling would
put dbml-sharepoint's golden fixture downstream of an external version. Adopt
the practices instead: a golden file per generated script in formwork, reviewed
like code, and `node --check` (already present).

**(c) Shared evidence/findings schema: yes for the probe contract, no for the
discovery document.** `formwork.discovery/v1` is a catalogue artefact, the
analogue of dbml-sharepoint's extract download, and should stay formwork's own.
formwork's measured constraints in `generator.py:22-29`, however, are probe
findings without a probe. Write them as a probe that conforms to the shared-v2
harness contract so the test-agent can run it unchanged: top-level
`(async () => {`, the four guards defaulting to false, `const RESULTS = [];`
before any question, `expect` for every question up front, `record` with
outcome and evidence separated, `report`, `// finding:` header lines, and check
ids under a new `page` surface. Owned by dbml-sharepoint's SURFACES.md (one
authority), mirrored in the test-agent in the same review, with the probe
files living in formwork.

**(d) Shared repo or package: no.** Three cadences (release-please with a
breaking-change list on 2026-09-03; a private harness with checksum pins to
specific upstream commits; a days-old tool), two Python floors, and a name
collision waiting to happen (`bundle.py` means an extraction bundle in formwork
and a build-output bundle in dbml-sharepoint).

**The contract, stated:**

| Surface | Owner | Consumers | Proof of compatibility |
| --- | --- | --- | --- |
| Probe harness shape, guards, result table, `// finding:` lines | dbml-sharepoint (`test/manual/templates/`) | test-agent (runs), formwork (conforms) | `check_probe_directory` run against each consumer's probe directory in CI |
| Check-id grammar and surface list (`SURFACES.md`) | dbml-sharepoint | test-agent (mirror, refuses unknown), formwork (files under `page.*`) | test-agent mirror test; formwork catalogue validated by the same loader |
| Measured transport facts | dbml-sharepoint partials, dated | formwork prelude, by citation | A pinned test per fact in each consumer |
| Vendored harness bytes (if formwork vendors the partial) | dbml-sharepoint | formwork | SHA-256 of the vendored bytes at a named upstream commit, in the style of `catalog.py:27-50`; revision hash printed at run time |
| Document schemas (`formwork.*`), canvas semantics, page DSL | formwork | formwork only | formwork's own tests and fixtures |

## 4. Sequencing

Each step is independently valuable and none destabilises a working system.

1. **formwork only, small.** Port four transport facts into `_JS_PRELUDE` with
   dated citations: throttle-page redirect detection on the final URL
   (`_http.js.j2:36-44`), `spError` on every non-OK response (`_http.js.j2:25-34`),
   the guarded contextinfo parse (`_digest_cached.js.j2:9-42`), and `odataName`
   for any title interpolated into `getbytitle` (`_site_guard.js.j2:24-27`).
   Keep the `location.pathname` prefix, the real-etag MERGE and the absence of
   SITE_URL. Add a test per fact. Add a golden file for each of the three
   generated scripts. This makes the discover script, which issues the most
   requests, diagnosable under throttling.
2. **formwork only.** Write `test/manual/sitepages-transport-probe.js` (rendered
   from a template with a vendored copy of `_probe_core_v2.js.j2`, pinned by
   upstream commit and SHA-256, revision hash printed) that re-measures the
   constraints in `generator.py:22-29` as recorded rows: contextinfo GET, bare
   `/_api` from a sub-site page, list-item POST into Site Pages, `Files/add` of
   an `.aspx`, `sitepages/pages` create, recycle. Include a `probe-catalog.json`
   in the 1.2 shape. This turns "measured 2026-09-06" into evidence anyone can
   re-run, and it is useful even if no other step happens.
3. **dbml-sharepoint and test-agent, one review each, same week.** Add a `page`
   surface to SURFACES.md with a small scope registry (for example `sitepages`,
   `canvas`, `components`) and a note that its probes live in formwork; update
   the test-agent's surface mirror. This is the deliberate act SURFACES.md asks
   for and it is one line plus a mirror.
4. **test-agent.** Parameterise `check_upstream_contract.py` so
   `minimum_scripts` is an argument and run it against formwork's probe
   directory as a second upstream in CI. Then design a modern-page anchor lane:
   the owner lane's exact match on `_spPageContextInfo.webAbsoluteUrl` cannot be
   used on a page where that global is absent, and `AGENTS.md:11` forbids
   weakening it to a prefix. The candidate replacement is a same-origin read of
   `/_api/web?$select=ServerRelativeUrl` from the anchored page, compared
   exactly against the canonical site. That needs a measurement of its own
   before it is trusted, and it is the test-agent owner's call. Evidence for a
   formwork probe must flow back to formwork, so the publish bridge needs a
   per-upstream target (UNVERIFIED how it selects its target today).
5. **Only if a third consumer appears or formwork grows past a handful of
   scripts.** Extract a vendored, checksum-pinned transport prelude generated
   from dbml-sharepoint's partials. Not a package; a rendered file with a
   pinned revision and a consumer-side test that fails when the bytes differ
   from the pinned upstream commit.

## 5. Governance and test-and-record

- **Who records SharePoint behaviour.** Whoever measured it, in the repo that
  owns the code path it corrects, as a dated comment plus a pinned test
  (`philosophy.md:33-47`). formwork adopts this rule verbatim; it already
  practises it in `generator.py:22-29` and `tests/test_generator.py:43-45`.
- **How a transport fact propagates.** It lands in dbml-sharepoint's partial
  first with its finding date. A formwork PR then cites that file and date in
  `_JS_PRELUDE` and adds its own pinned test. Nothing propagates automatically,
  and that is the point: each consumer proves it still holds for its own anchor
  page and call pattern. A fact formwork measures that is about transport rather
  than pages (for example, throttle behaviour from a modern page) is offered
  upstream as a `// finding:` line on the formwork probe and a dbml-sharepoint
  issue, and dbml-sharepoint decides whether it earns a partial change.
- **How the shared contract stays honest.** The test-agent's contract check is
  the executable definition. Running it against both probe directories in CI
  means a harness change in dbml-sharepoint that breaks formwork's probes is
  visible the day it lands, not when someone pastes. Checksum pins on vendored
  harness bytes make a silent divergence a failing test, and the printed
  revision hash makes a stale paste a one-line diagnosis
  (`render_probes.py:52-60`).
- **How evidence returns.** Machine results and captures go to the repo that
  owns the question (`docs/architecture.md:63`). For `page.*` check ids that is
  formwork. Raw transcripts never enter any repo (`AGENTS.md:15`).
- **Who may change the vocabulary.** Only dbml-sharepoint, in SURFACES.md, with
  the test-agent mirror updated in the same review. formwork never invents a
  surface or a scope locally.

## 6. Risks and anti-goals

- **Do not build a shared runtime to satisfy three call patterns.** The
  in-repo precedent is decisive: dbml-sharepoint keeps the probe harness (which
  returns refusals as values) apart from the deploy transport (which throws)
  because merging them would make a measured refusal look like a crash.
- **Do not bake SITE_URL into formwork scripts.** The probe harness dropped it
  after two tenant-URL leaks (`_probe_harness.js.j2:19-22`). formwork's scripts
  are meant to be pasted from the page they act on and derive the web from it.
- **Do not impose the `_spPageContextInfo` guard on formwork.** dbml-sharepoint
  measured that global absent on a modern page (`_cross_web.js.j2:8-10`);
  formwork runs only from modern pages. Whether it is absent on every modern
  page is UNVERIFIED and should be one of the first rows in step 2's probe.
- **Do not loosen the test-agent's exact-site check to admit modern pages.**
  Find a measured exact alternative or keep formwork's probes on the manual
  lane until one exists.
- **Do not make dbml-sharepoint's golden depend on an external version.** A
  dependency bump would then regenerate the deploy fixture from outside the
  repo, defeating "review the fixture diff like code" (`AGENTS.md:131-134`).
- **Do not merge the discovery document with the findings schema.** One is a
  catalogue of what a site declares placeable; the other is a table of
  questions with outcomes and evidence. Keeping them apart is what lets the
  DSL compile against the catalogue without a probe run.
- **Do not create a package with one consumer.** A `sharepoint-pastejs`
  package would carry two Python floors, two release cadences and the
  `bundle.py` name collision, for three scripts that currently fit in one
  string constant.
- **Watch for formwork drifting from its own rule.** The discover script
  already issues dozens of sequential requests with no throttle handling
  (`generator.py:239-353`). Step 1 exists because the next live finding in
  formwork is likely to be a throttle page reported as a bare 406.
