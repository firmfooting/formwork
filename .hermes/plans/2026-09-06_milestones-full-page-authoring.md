# Formwork milestone plan: full page authoring (text, styling, formatting)

Created 2026-09-06 after the transport-hardening review. Direction from Shaun:
formwork should build an entire page and its contents — text, styling and
formatting — with **Jinja as the consumption/display layer**. Milestones run
after the current branch (`feat/transport-hardening`) merges.

## Where we are

- v0.2.0 on `main`: extract / discover / apply paste-ins, component catalogue,
  page DSL (sections + parts + property overrides), byte-exact canvas
  round-trip, live-verified end to end.
- `feat/transport-hardening` (3 commits, review-clean): the measured transport
  facts (throttle gate, spError, guarded digest, OData quoting) ported from
  dbml-sharepoint, pinned per script, with goldens.

## M0 — ship the branch (in flight)

Fold review findings (done: P2-1 decode-before-quote, P2-2 real throttle
pins), all gates green, push, PR (no reviewer, no labels), CI green, squash
to `main` after Shaun's review. Tag v0.2.1.

## M1 — text parts and rich content in the DSL

Text is a web part (`ClientWebPart`/text control, controlType 4) with HTML in
its properties — the same `serverProcessedContent.htmlStrings` surface the
canvas already carries. Add to the DSL:

- `text:` part type taking markdown or HTML, compiled to the text control
  with correct control data (`controlType: 4`, `htmlProperties`).
- Section headings and vertical-section support (currently only column
  factors).
- Property overrides verified against a real placed control (discover already
  reads back what SharePoint persists — extend it to capture text controls
  and headings as ground truth, folded into `formwork.discovery/v1`).

Deliverable: a spec that compiles a page with real text content, applied
byte-exact on the sandbox. Gates as today plus `node --check` and goldens.

## M2 — Jinja consumption layer

Introduce `formwork/templates/` (Jinja2) as the display layer for generated
artifacts, replacing the three Python string bodies:

- `extract.js.j2`, `discover.js.j2`, `apply.js.j2` — same emitted bytes
  (goldens prove the migration byte-for-byte; this is why goldens landed
  first, in M0).
- Shared partials mirroring dbml-sharepoint's partial-earning rule: `_prelude`
  stays one partial; the four transport facts become cited, dated Jinja
  comments at point of use.
- New: a **page HTML preview** template rendering the compiled page (sections,
  columns, text, part titles) for human review before apply — the consumption
  layer Shaun asked for. `formwork preview page.yaml` emits standalone HTML;
  no SharePoint call involved.

Deliverable: generators render through Jinja with zero golden churn
(`pytest` byte-exact), plus the preview command.

## M3 — styling and formatting

Measured, not guessed, per house rules:

- Theme/accent and section emphasis (the `emphasis` block already in
  control data), background images per section, vertical section spacing —
  one discovery pass each, findings dated in the prelude/canvas modules.
- DSL surface: `theme:`, `emphasis:`, per-section styling keys compiled into
  control data and validated against the live read-back.
- Text formatting via the text part's HTML (bold/colour/size/link) — styled
  content is authored in the DSL as HTML/markdown and lands in
  `htmlStrings`; a discovery row proves what SharePoint sanitises vs keeps.

Deliverable: a spec that compiles a styled, formatted page — headings, styled
text, accent sections — verified byte-exact on the sandbox.

## M4 — prose and polish

README rewrite around the authoring workflow (declare → preview → apply),
CHANGELOG, v0.3.0 tag, and the advisory's step 2 (sitepages transport probe
in dbml-sharepoint form) if Shaun wants the evidence loop closed.

## Standing constraints carried through every milestone

- No baked SITE_URL; prefix from `location.pathname`; refuse off-page.
- Byte-exact goldens are the migration and regression contract; review golden
  diffs like code.
- Every SharePoint behaviour claim is measured (sandbox live run) before the
  DSL encodes it; findings carry dates and citations.
- Gates per commit: pytest, ruff, mypy strict, ruff, `node --check` per
  generated script, goldens byte-exact.
- Reviews: read-only adversarial review per slice, findings folded or
  rebutted, PR only on Shaun's word, never a reviewer request, never labels.
