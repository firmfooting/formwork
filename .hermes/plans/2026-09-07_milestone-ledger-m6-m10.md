# Formwork milestone ledger — M6–M10 (next phase)

Created 2026-09-07. M0–M4 (the original full-page-authoring plan,
`.hermes/plans/2026-09-06_milestones-full-page-authoring.md`) are COMPLETE:
hardening, text parts, Jinja + preview, styling (measured), release 0.3.0 —
PR #4, all gates green. The architecture review
(`.hermes/review/2026-09-06_architecture-review.md`) is the research base for
this phase; its quarter list, reordered against what we have learned since,
is the plan below. Standing constraints from the prior plan carry forward
(measured-not-guessed, byte-exact goldens, cited refusals, gates per commit,
adversarial review per slice, PR only with stacks ≤ 5 deep, merge as needed).

## M5 — properties, nesting/alignment, list bindings (DONE — PR #4 merged 2026-09-07)

Dispatched 2026-09-06 (`proc_4f3c02949ade`). Discover gains three additive
measurement blocks:

- `webpartProperties`: 6 representative parts × 2 instances (defaults vs one
  modified flat property) → which property paths survive item-MERGE.
- `layoutVariants`: one-third-left (8/4) and one-third-right (4/8) sections,
  controlIndex ordering within split columns.
- `listBindings`: two probe fixture containers (custom list + document
  library, created and recycled by the probe), list-bound and library-bound
  web parts bound to real runtime-read ids, plus a cross-binding pair —
  the evidence base for "bind part X to target list Y" as a DSL operation.

Then: operator gates, live run through the sandbox tab, measurements folded
into typed catalogue accessors, DSL consumption (list binding mapping,
factor variants) as the next code slice.

## M6 — measurement infrastructure (DONE — PR #5 merged 2026-09-07; 17-row registry, staleness warnings, findprobe lane)

The architecture review's P2-3, promoted because "keep strong records" is
the point of the tool:

- `FINDINGS.md` in-repo: every measured claim as a row — check-id
  (`<surface>.<scope>.<question>` grammar, aligned with dbml-sharepoint's
  SURFACES convention), claim, date, fixture pointer, re-probe command.
- Discover emits a `findings` block; compile warns when the oldest relevant
  measurement exceeds a configurable age (default 90 days).
- A re-probe lane: `formwork gen findprobe` renders a paste-in that re-runs
  every recorded measurement and diffs against the registry (the advisory's
  step 2, folded in).
- Hand-authored fixture rows (section-emphasis) get promoted to
  re-runnable rows so the pin survives a re-run of discover.

## M7 — page state and identity (IN FLIGHT — dispatched 2026-09-07, proc_cd85503ba6ad, branch feat/page-state)

Create is only birth. Measure and add to the DSL/apply: file name (slug vs
editor-assigned), Description, BannerImageUrl, layout type beyond Home,
PromotedState as news, check-in/publish state, and a measured answer on
permission inheritance for a created page. Then multi-page: a spec that is
a list of pages sharing one discovery document, with `navigation` an
explicit refused-until-measured key.

## M8 — payload provenance and the apply guard (P2-1) — BUILT (PR #7) + LIVE-VALIDATED 2026-09-07

Live guard validation (sandbox, TestSampleTeam, all four cases):
1. tampered stamp URL -> REFUSED pre-create, both values listed, 0 pages created
2. honest stamp -> guard OK, page created, canvas byte-exact (1566 chars), PromotedState 0
3. stamp formwork 9.9.9 (newer) -> REFUSED with no override path, nothing created
4. tampered + FORCE_SITE_MISMATCH=true -> warning printed, applied, byte-exact
Both test pages recycled (200/200), zero residue. Guard verdict: pass on all four.

Compile stamps the payload with discovery-document hash, source web id/url,
spec hash, formwork version. Apply reads the stamp and refuses a
site/version mismatch without `--force`. Closes "compile against site A,
apply on site B verifies OK".

## M9 — templates and variables; authoring ergonomics (P2-6)

`page.yaml` becomes a Jinja template over a `vars` file (StrictUndefined,
rendered before YAML parse — no DSL change). Multi-page specs may share a
vars file. Preview grows a `--vars` passthrough.

## M10 — distribution and gate breadth (P2-5)

Tag v0.3.x, build a wheel in CI, document `pipx install`. Add Python 3.12
and 3.13 to the matrix; add the discover script to the CI node gate.
Golden version sentinel (rewrite goldens with a placeholder so version
bumps stop churning them) and `.gitattributes` eol pin land here.

## Explicitly deferred (do not pre-build)

- Section model / section emphasis via SavePage (P2-7): the item-merge
  measurement is done; the SavePage write path needs its own slice AFTER an
  editor-authored capture page gives us the section background shape.
- Theme and accent: web-level, not page-level; out of scope until someone
  needs it.
- Navigation: refused until measured.

## Process notes

- PR stacks stay ≤ 5 deep; merge bottom-up as slices land.
- Every slice: implement → operator gates → adversarial read-only review →
  fold → live measure where SharePoint behaviour is claimed → PR.
- Review chain lives in `.hermes/review/`; plans in `.hermes/plans/`.
