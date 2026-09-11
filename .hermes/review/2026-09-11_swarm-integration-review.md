# Adversarial review — swarm integration PR #27 (`main...swarm-integration`)

Reviewer: Claude Opus 5, 2026-09-11. Read-only review of the integration tip
`845d876` (20 files, +1101/-76). Gates re-run locally, not trusted from CI.

## Verdict

**All 14 merged fixes hold.** Each one does what its issue claims, each one's
test fails against `origin/main`, and nothing in the diff invalidates the M8
live evidence. The code is mergeable.

**One P1 blocks the PR as written**, and it is a linkage defect, not a code
defect: the P1 fix for #16 is on a branch that was never merged, while the PR
body lists #16 as fixed and says "Merge closes #12-#26". Merging as-is closes
an unfixed P1 issue silently.

Merge after either merging `origin/swarm/probe-scripts` (it applies cleanly) or
correcting the PR body so #16 stays open.

## P1 — blocks merge

### 1. Issue #16's fix is not in this branch, but the PR claims it is

`origin/swarm/probe-scripts` (`7d9bfd7`, "make the filename-slug findprobe
verdict run-independent") is the fix issue #16 names, and it is not an ancestor
of the integration tip. The diff touches no findprobe file:
`src/formwork/templates/findprobe.js.j2`, `tests/fixtures/expected/findprobe.js`
and `FINDINGS.md` are all untouched, so the volatile verdict string
(`"ignored (stored " + got + ")"`) is still what a tag would ship.

```console
$ for b in apply-guard canvas catalogue ci-packaging cli compiler docs findings \
         multipage preview provenance refs templating test-quality probe-scripts; do
    printf "%-14s " "$b"
    git merge-base --is-ancestor origin/swarm/$b HEAD && echo MERGED || echo "NOT MERGED"
  done
...
test-quality   MERGED
probe-scripts  NOT MERGED

$ git diff --stat main...HEAD -- src/formwork/templates/findprobe.js.j2 FINDINGS.md
(empty)
```

The PR body is wrong in two places, not one. Its "findings" list has 14 entries:
it **includes #16** (not merged) and **omits #23** (merged as `09e29fa`). So the
one issue with no fix is advertised as fixed, and one issue with a fix is
missing from the list that justifies closing it.

The branch applies cleanly on top, so this is cheap to correct:

```console
$ git merge-tree --write-tree --no-messages HEAD origin/swarm/probe-scripts; echo "exit=$?"
72df6a5d33421184cbfb93a89474edb429b20c91
exit=0
```

If `probe-scripts` is merged, regenerate the goldens again — it changes
`findprobe.js.j2`, and its own commit carries the matching
`tests/fixtures/expected/findprobe.js`.

Issue-to-branch linkage for the other 14 was checked one by one against each
issue body: every claimed branch and commit sha matches what was merged
(`07f97ff`, `61d2072`, `640af31`, `2e87196`, `cbab495`, `6f67142`, `264d390`,
`a5e13a8`, `d78d462`, `6298ee9`, `09e29fa`, `90c599a`, `dc83c12`, `88281e4`).
All of #12-#26 are still open, so nothing was closed early.

## P2 — fix before or immediately after merge

### 2. `canvas.py:207` — the mirror stays stale for any value containing `&`, `<` or `>`

`_sync_mirrors` refuses to touch a mirror whose new value needs HTML escaping
and says nothing about it. That is the exact outcome #26 was filed for: the
emitted page keeps the source site's text, `process` reports the ref as
applied, and no warning or unresolved row is produced. Ampersands in titles are
ordinary ("R&D", "Sales & Marketing"), so this is not an exotic input.

Measured on the live capture (`tests/fixtures/collabhome.canvas.html`), a
rewrite of the Quick links part titles:

```
changed controls: ('...-000000000003', '...-000000000004')
mirror: title           -> 'Fast links'                 <- synced
mirror: items[0].title  -> 'Learn about a team site'    <- STALE
mirror: items[1].title  -> 'Learn how to add a page'
json  : {'title': 'Fast links', 'items[0].title': 'R&D primer', ...}
```

`items[0].title` was rewritten to `R&D primer` in the web-part JSON; the mirror
still carries the source site's string. The docstring acknowledges the carve-out
("the new value needs no HTML escaping") but no test pins it, and the runtime is
silent. The repo's own standard is refuse-or-report; leaving a known-stale
mirror unreported is the defect class the issue raised. Either escape the value
or add it to `unresolved` / warn.

### 3. `multipage.py:258` — the YAML refusal names a position the operator cannot see

The value no longer leaks (that part of #15 is properly fixed), but the position
now reported is the mark in the **rendered** text. A multi-line value from a
vars file shifts every line after it, so the refusal can name a line beyond the
end of the spec file:

```console
$ cat -n pages/p.yaml          # 7 lines; the unterminated string is line 7
     1  vars: ../v.yaml
     ...
     7        - text: "unterminated
$ formwork compile-pages pages/ disc.json --out-dir build/
  FAIL  p.yaml: p.yaml: template rendered to invalid YAML at line 10, column 1
```

`v.yaml` holds `blurb: "line one\nline two\nline three"`. Saying "at rendered
line 10" (or mapping back through the template) keeps the refusal honest at no
cost to the secret-safety property.

### 4. `CHANGELOG.md` — thirteen behaviour changes ship unannounced

The only changelog addition is the M10 documentation entry from `swarm/docs`.
The other fixes add operator-visible refusals with nothing in Unreleased:
case-only payload-name collisions, address-less web-part controls, non-finite
floats, non-string `displayTitle`, obfuscated `javascript:`/`data:` URLs, a
stamp that names neither discovery nor bundle, plus the new catalogue entry-title
resolution and the two new stamp fields. The Unreleased section documents changes
at finer grain than these, so the omission is a convention break, and
`displayTitle: 2026` in an existing spec now refuses where it used to compile.

## P3 — notes

5. **`text.py:143` refuses escaped text content**, contradicting its own
   docstring ("text content are never decoded ... must stay legal").
   `html.unescape` is applied to the whole body, so a page that *describes* a
   script URL is refused:

   ```
   REFUSED '<p>Never write &lt;a href=&quot;javascript:alert(1)&quot;&gt; in a page.</p>'
   ```

   The companion test `test_escaped_markup_and_text_are_still_legal` only covers
   `&lt;script&gt;`, which carries no `href=`, so it cannot catch this. It fails
   in the safe direction. Legitimate URLs are unaffected: `https:`, `mailto:`,
   relative, `../`, `#anchor`, `src="/sites/..."` and a `data:` mention inside a
   query string all stay legal (verified against `text_to_html`).

6. **`text.py:166` reports the wrong line.** `_line_of` walks the original body
   counting characters against an index taken from the *unescaped* string, so
   every multi-character entity before the match shifts the count. A body whose
   bad URL sits on line 3, preceded by ten `&amp;` on line 1, is reported as
   "line 1".

7. **`refs.py:120` refusal cannot be acted on, and `inspect` no longer helps.**
   The message names no control (no index, instanceId, title or position), and
   `_cmd_inspect` (`cli.py:59`) calls the same `scan_canvas`, so the one command
   that could locate the broken control now refuses the same bundle. Not
   triggered by any real shape: across `collabhome.canvas.html`, the bundle and
   the three discovery captures, including two ~100-control stored canvases, zero
   web-part controls lack an address. So the refusal is defensive, not dead
   paranoia over a live shape, but a hand-edited bundle is now harder to debug.

8. **Named in issue #25, deliberately unfixed, still live on the tip.**
   `dsl.py:454` does `int(part.get("column", 1))`: `column: [1]` escapes as a raw
   `TypeError` traceback past the CLI handler, and `column: 1.9` silently
   compiles to column 1. #14 hardened `main()` for `OSError` and left `TypeError`
   escaping, so the traceback class the swarm set out to close is only partly
   closed. Pre-existing on `main`; out of scope for this PR, worth its own issue.

## Per-fix verdict

| Fix (branch) | Issue | Holds | Regression risk |
|---|---|---|---|
| ci-packaging | #12 P1 | Yes — proven outside CI | None. Release workflow only; verified by running the command in a clean export |
| templating | #15 P1 | Yes — no value in stderr or manifest | Low. Message position can mislead (P2-3) |
| probe-scripts | #16 P1 | **Not merged** | n/a — fix absent (P1-1) |
| multipage | #13 | Yes — case-folded guard refuses before writing | None. Refusal names both specs and the case-only reason |
| preview | #21 | Yes — all 7 obfuscations refuse | Low. False positive on escaped text content (P3-5), wrong line number (P3-6) |
| provenance | #17 | Yes — page vars stamped in both CLI paths | None. Stamp gains two fields; README and CHANGELOG already name them |
| compiler | #25 | Yes — inf/-inf/nan and non-string displayTitle refuse | Low. `displayTitle: 2026` now refuses; unannounced (P2-4) |
| canvas | #26 | Partly — silent for `&`/`<`/`>` values | Medium (P2-2). Byte-exactness of unchanged controls verified intact |
| catalogue | #24 | Yes — entry titles resolve with measured defaults | None. Own titles still outrank entry titles; ambiguity still refused; indices provably aligned |
| refs | #22 | Yes — refuses instead of dropping | Low. No live shape triggers it; message locates nothing (P3-7) |
| apply-guard | #20 | Yes — fails closed, M8 paths untouched | None. Verified under node with real payloads |
| cli | #14 | Yes — all three evidence cases are one error line | Low. `TypeError` still escapes (P3-8) |
| findings | #23 | Yes — case and spacing tolerant | None. Over-matching only adds a reliance row |
| test-quality | #19 | Yes — whole suite is cwd-independent now | None |

### The four sticky areas, specifically

**`apply.js.j2` does not invalidate the M8 live evidence.** The discriminator
moved from one field's type to the presence of any compile marker, and a real
compile stamp always carries `spec` and `compiledAt`. A real process stamp is
exactly `{formwork, bundle, processedAt}` (`provenance.py:215`), so it has no
compile marker and takes the process branch as before. Run under the repo's own
node harness against payloads produced by the current compiler:

```
== real compile payload (page vars, full stamp)
   creates: 1
   log: [formwork] provenance OK: ... web 20c3b672-... matches the stamp
== real process payload (process_stamp)
   creates: 1
   log: [formwork] provenance: ... no discovery binding (process payload): site check not applicable
== compile stamp with NO template fields
   creates: 1
   log: [formwork] provenance OK: ...
```

All three still create the page. The change only adds refusals for stamps that
compile never writes. Both goldens were regenerated consistently with the
template (`apply.js` and `apply-payload.js`, +42/-3 each, matching the template).

**`templating` × `provenance` on `multipage.py` merged correctly.** Both cases
stamp right, verified end to end:

| Case | `varsFile` | `ownVarsFile` |
|---|---|---|
| `--vars` only | `shared.yaml` | `""` |
| page `vars:` only, no flags | `""` | `secret.yaml` (+ sha256) |
| both | `shared.yaml` | `own-vars.yaml` (+ sha256) |

Single `compile` stamps it too (`cli.py:225`). No vars-file value appears in
`formwork-pages.json` (`grep -c SUPERSECRET` → 0). The extracted
`page_vars_name` helper is the same regex `read_spec` used, and `read_spec` still
calls it, so there is one discovery, not two that can disagree.

**`text.py` does not refuse legitimate URLs.** Checked `https:`, `mailto:`,
relative, `../`, `#anchor`, `img src="/sites/..."` and a `data:` substring in a
query string — all legal. The two false-positive classes are P3-5 and P3-6.

**`refs.py` is not guarding a shape any capture contains** — 0 address-less
web-part controls across every fixture, including two ~100-control stored
canvases. It matches the duplicate-instanceId refusal directly below it, and
issue #22's evidence (a hand-edited bundle) is a real operator input, so the
refusal is justified. P3-7 is about it being unactionable, not wrong.

## Gates run

| Gate | Result |
|---|---|
| `.venv/bin/python tests/test_generator.py` then `git status --short` | Clean, no drift. `findprobe.js` unchanged, consistent with probe-scripts absent |
| `.venv/bin/ruff check src tests` | All checks passed |
| `.venv/bin/mypy --strict src` | No issues, 16 files |
| Full suite from `/tmp` (not the repo root) | 529 passed — also proves #19's fix is complete, not just local to `test_dsl.py` |
| Branch's 13 changed test files against `main`'s `src/` via `PYTHONPATH` | 45 failed, 381 passed. Every fix has at least one test that cannot pass on `main` |
| The 6 added tests that pass on `main` | All explicitly named as regression guards ("still refuses", "still legal", "still renders byte exact"). Correct that they pass |
| Release build in a clean `git archive` export of each side | `main`: exit 1, "No module named build", no `dist/`. Branch: `formwork-0.6.0.tar.gz` + wheel, all 11 templates shipped |
| Apply guard under node, real compile / process / template-less payloads | All three apply; guard messages unchanged from M8 |
| `gh issue list --state open` | #12-#26 all open, none closed early |

Method note: main's source was compared by `git archive main` into `/tmp` and
importing it over `PYTHONPATH`, so the worktree was never modified. All scratch
artifacts are under `/tmp`.
