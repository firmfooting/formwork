# Adversarial re-review: the P1 fixes (`293e791`)

Reviewed 2026-09-06, branch `feat/m3-dsl-and-release`, commit `293e791` ("fix(refs,dsl): fold architecture-review P1-1 and P1-2"), against `.hermes/review/2026-09-06_architecture-review.md` P1-1 and P1-2. Method: `git diff 2e03506..293e791` could not be run (Bash denied; the brief grants Read/Grep/Glob/Write), so the fix was reconstructed from the current tree, the architecture review's line citations, and the fix's own in-code citations ("architecture review P1-1/P1-2, 2026-09-06"). No code was executed; anything that needs a run is marked OPERATOR-RUN. Every claim carries a file:line.

## Verdict: REQUEST CHANGES

Narrow. P1-1 and P1-2 as specified are correctly and completely folded (sections 1 and 2). The request is for one P1 that the fix does not introduce but does make reachable on ordinary live pages: the dirty-render path both fixes now route through passes re-escaped JSON to `re.sub` as a *replacement template* (`src/formwork/canvas.py:73,78`), so any non-ASCII character crashes it and any newline, tab or backslash silently corrupts the stored JSON. The architecture review named the `json.dumps` / `ensure_ascii` behaviour as a coupled P1-2 sub-defect (architecture-review.md:41); it is worse than "unmeasured". Two lines and one test fix it. Everything else below is P2/P3.

## 1. P1-1 completeness

### Verified

- **One fold, all positions.** `stored_text_html` is `html.replace(":", "&#58;")` over the whole inner HTML (`src/formwork/dsl.py:337-354`), applied once when the text control's body is built (`dsl.py:390`). Style attributes, hrefs and running text are all inside that string, so all three fold. The three positions are all *measured*, not inferred: style and href in the seven style samples (`tests/fixtures/discovery.styling.json:2829,2848,2867,2886,2924`), running text in the second M1 probe, requested `Second text control: ` (`:2610`) and persisted `Second text control&#58; ` (`:2663`).
- **The measured delta is exactly the fold.** The nine text samples carry ten colons (probe 1: `https:` and `color:`; probe 2: one in running text; style samples: 1+1+1+3+0+1+0). Ten times four bytes is the 40-character growth `requestedCanvasChars 97907` vs `storedCanvasChars 97947` (`discovery.styling.json:2581-2582`). Nothing else on the 84-control scratch page moved.
- **Nothing else emits a literal `:` from compile.** Control and web-part attributes go through `escape_attribute`, which folds `:` (`src/formwork/canvas.py:37`, used at `dsl.py:396-397`, `dsl.py:313,319`). The web-part control body is `<div data-sp-webpartdata="…" data-sp-htmlproperties=""></div></div>` (`dsl.py:317-324`) and the page wrapper is `<div>` … `</div>` (`dsl.py:451-454`): no colon outside escaped JSON.
- **`parts[].html` is authored form.** `body_html = part_html(placement)` is stored in the part record unfolded (`dsl.py:431-434`); the fold happens inside `_text_control` only. Preview also renders `part_html(placement)` (`src/formwork/preview.py:80`). Pinned at `tests/test_dsl.py:565-596` and `tests/test_styling_evidence.py:117-118`.
- **No double fold.** Compile marks every control dirty (`dsl.py:333,392`), but the dirty render substitutes only the two JSON attributes and leaves `body` untouched (`canvas.py:69-79`, `count=1`), so the rte body is folded exactly once. On the copy path a text control is never a web-part control, so it is never dirtied and renders raw (`canvas.py:64-65`). The catalogue gate folds the other direction, on the comparison only (`src/formwork/catalogue.py:49-75`), never on emitted bytes. A text body cannot carry a `data-sp-controldata=` for the regex to hit because `_checked_html` refuses any `data-sp-` (`src/formwork/text.py:121-122`).
- **Apply names the page and never recycles.** `apply.js.j2:62-67` throws "The page EXISTS with what SharePoint stored: item <id> at <url>. Formwork does not recycle it; keep it or recycle it yourself." `created.id` and `created.url` exist: `createSitePage` returns `{ id: page.Id, url: page.Url, … }` (`src/formwork/templates/_prelude.js.j2:193-196`). `recycle` appears in no apply template (grep: only `discover.js.j2` and `README.md:108`). Goldens carry the message (`tests/fixtures/expected/apply.js:225-240`, `apply-payload.js:225-240`) and `tests/test_generator.py:450-464` pins message, id, URL and the absence of `recycle(` / `/recycle`.
- **The gate still needs its both-sides fold.** The probe sends literal colons in text inner HTML (`discover.js.j2:199-202`; requested `:2591` vs persisted `:2645`), so `persisted_matches` folding both sides (`catalogue.py:73-75`) is correct and unchanged.

### Findings

- **P3** `README.md:110-113` says the payload "carries what SharePoint will store". What is measured is that SharePoint's rewrite of text HTML is *at most* the colon fold for the nine samples. That `&#58;` *sent* comes back as `&#58;` in rte inner HTML has not been measured directly: the probe sent `:` (`discover.js.j2:199-202`), the pre-fix live apply sent `:`, and no post-fix live apply is recorded in the tree (README grep for byte-exact: `:262,280,294`, none about a compiled text part; no new fixture). The 73 web-part controls prove `&#58;` survives in *attributes* (`README.md:294`), which is a different sanitiser path from rte inner HTML. Almost certainly idempotent, but it is the single assumption P1-1 now rests on. See OPERATOR-RUN 1.
- **P3** The compile gate's samples do not contain what the markdown converter emits for `&`, `<`, `>` (entities, `text.py` escapes them), nor `<ol>`, `<h1>/<h3>/<h4>`, `<br>`. `<strong>`, `<em>`, `<ul><li>` are measured (probe 2, `discovery.styling.json:2610`). An entity in text HTML is the next most likely thing SharePoint's encoder touches, and it would fail apply in exactly the P1-1 way. Not a defect in this diff; noted for the evidence registry.

## 2. P1-2 completeness

### Verified

- **No type-id matching remains.** Controls are keyed by `web_part_data["instanceId"]`, falling back to the control's own `id` (`src/formwork/refs.py:89-102`); `_controls_by_instance` (`:105-121`) is the only lookup, used by `scan_canvas` (`:158-163`) and `apply_plan_to_canvas` (`:217-236`). The component id appears in `refs.py` only in the docstring. `tests/test_refs.py:299-335` proves it on a canvas with two Quick links sharing one component id and different instanceIds.
- **Dirty only on real change.** `_write` compares before setting and returns `False` on equality (`refs.py:248-251`); `apply_plan_to_canvas` marks dirty only on `True` (`:233-235`). `setdefault` cannot create a section without also writing (a missing section implies a missing key, which returns `True`). Pinned by `tests/test_refs.py:270-278`: a mapping restating the extracted values gives `rewritten == ()`, no control dirty, `render() == CANVAS`. The `not any(control.dirty …)` assertion is the load-bearing one; the byte-equality alone would hold even if the controls were dirtied, because collabhome round-trips byte-exact through the dirty path.
- **Duplicate instanceId: correct and reachable.** `ValueError("canvas carries two web-part controls with instanceId …")` at `refs.py:116-119` is raised through `scan` (inspect: `cli.py:33-34`; process: `cli.py:66`) and again through `apply_plan_to_canvas` (`:225`). `main` maps `ValueError` to `error: …`, exit 1 (`cli.py:284-295`). `tests/test_refs.py:198-203` builds the doubled canvas by duplicating a control block and pins the refusal.
- **Old bundles still parse.** `parse_bundle` ignores unknown keys; the legacy `webParts` key is retained only in `raw` (`src/formwork/bundle.py:76-78`), pinned at `tests/test_bundle.py:60-69`.
- **`process` reports honestly.** `cli.py:84-89` prints resolved, rewritten and unresolved as three separate numbers; a mapping that changes nothing prints `N refs resolved, 0 control(s) rewritten`. The `7 refs resolved, 3 control(s) rewritten, 9 unresolved` pin (`tests/test_cli.py:89`) is arithmetically right for collabhome: resolved = baseUrl×2 (restates source, no write) + siteId×2 + webId×2 + one text override = 7; rewritten = News, Quick links, Document library = 3; unresolved = 4 list + 3 text + 2 link = 9; Site activity untouched.
- **The named sub-defects are all folded**: title-as-mapping-key for lists kept (documented), `build_plan` treats `link`/`image` as report-only (`refs.py:49-55,191`), and the `if new_value:` truthiness bug is now `is None` (`refs.py:193`) with `test_an_empty_string_override_resolves`.

### Findings

- **P1 (pre-existing, made reachable by this fix)** `canvas.py:73` and `:78` call `_CONTROLDATA.sub(f'data-sp-controldata="{controldata}"', full, count=1)` with a *string* replacement, so `re` parses backslash sequences in the re-escaped JSON. Consequences: `json.dumps` defaults to `ensure_ascii=True` (`canvas.py:71,76`), so any non-ASCII character in a dirty control becomes `\uXXXX` and `re` raises `re.error: bad escape \u` (unknown escapes of ASCII letters are errors since Python 3.7); a `\n`, `\t`, `\r`, `\b`, `\f` in any string value is converted to the raw control character inside the attribute JSON, which `json.loads` then rejects and SharePoint stores as sent; `\\` collapses to `\`. Only `\"` survives, because `\&` (after `escape_attribute`) is not an ASCII-letter escape, which is exactly why collabhome's `serializedFilterQuery` round-trips (`tests/test_refs.py:280-297`). `re.error` is not a `ValueError`, so `main` (`cli.py:284-295`) shows a raw traceback. Reachable: from `process` on any live page whose *rewritten* web part carries a curly apostrophe, an accented name or a multi-line searchable text (`refs.py:233-234` → `canvas.py:63-79`), which before this fix never happened because nothing was ever dirtied; and, independently, from `compile` through an author's `displayTitle` or `properties` (`dsl.py:304,308-309`), which flow into `web_part_data` and are re-serialised at `dsl.py:333`. Not covered by any test: every fixture is ASCII-only (grep for non-ASCII bytes under `tests/` hits only two test comments and the goldens' em-dashes); the six `\n` escapes in `discovery.styling.json` (`:220,328,472,508,535,571`) sit in manifest `pattern`/`description` schema strings, which `parse_discovery` does not copy into `default_properties` (`catalogue.py:115-125`). Fix: use a callable replacement (`lambda _m: f'data-sp-controldata="{controldata}"'`) or splice on the match span, at both sites; add a test that dirties a collabhome control with `"Team’s links"` and one with `"a\nb"` and re-parses the render. Whether SharePoint stores `’` or the raw character stays a separate measurement (the review's original point); with a callable replacement the bytes are at least valid JSON either way. See OPERATOR-RUN 2 and 3.
- **P2** The in-place write updates `data-sp-webpartdata` only (`refs.py:239-251`); the control's `data-sp-htmlproperties` child, which lives in `body` and is never touched by the dirty path (`canvas.py:69-79`), keeps the *source* values. On collabhome those mirrors are `href="/sites/TestSampleTeam"` for `baseUrl` (twice), `>Documents<` for `listTitle`, and the Quick links titles and item URLs (`tests/fixtures/collabhome.canvas.html:1`, nine `data-sp-prop-name` attributes). After `process` with the test mapping, the payload canvas carries `listTitle: "Reports library"` in JSON and `>Documents<` in htmlproperties. Which copy SharePoint's runtime reads is unmeasured; the fixture shows the two already differ in spelling (absolute vs server-relative `baseUrl`), so the server derives one from the other on *some* path, but the item MERGE apply uses stores as sent (`README.md:293-294`). `tests/test_cli.py:84` (`"Reports library" in payload["canvas"]`) cannot see this because the old value is not asserted absent, and it is not absent. Outside the review's P1-2 text; raised because the "in place" write is the fix's mechanism and it is half a write. See OPERATOR-RUN 4.
- **P3** A web-part control with neither `instanceId` nor control `id` is skipped silently (`refs.py:114-115`) while `inspect` still counts it in "(N web parts)" (`cli.py:51`), so the count and the ref list can disagree without a word. Unmeasured whether such a control exists; a one-line `warn` would do.
- **P3** `inspect` is read-only yet refuses a canvas with duplicate instanceIds outright (`cli.py:33-34` → `refs.py:116-119`), so the operator cannot inventory the page they are being told is unusable. Listing the duplicate in `inspect` and refusing only in `process` is friendlier.
- **P3** `lists` is still keyed by `web_part_title` (`refs.py:187`), so two list-bound parts with one title cannot be mapped separately even though refs are now instance-addressed. Documented behaviour; an optional instanceId key would close it.
- **P3** `Ref.location` still spells `webParts[<instanceId>].…` (`refs.py:70-72`) for a list that no longer exists; pinned at `tests/test_cli.py:109`. Cosmetic.

## 3. Regression risk

- **Consumers of the removed contract: none left.** `webParts` / `web_parts` survives in `src/` only as the `bundle.py:76-78` comment and the `refs.py:72` address string. `cli.py:51` derives the count from the canvas. The extract template (`extract.js.j2:31-46`) and its golden (`tests/fixtures/expected/extract.js:206-221`) emit `sections: []` and no `webParts`; `tests/test_generator.py:467-473` pins it.
- **No test silently depends on the fixture's removed key.** `tests/fixtures/collabhome.bundle.json` now ends at `"sections": []` (`:44-45`); `tests/test_refs.py:126-130` asserts `"webParts" not in bundle.raw`; every refs/cli test reads the canvas.
- **Old and new readers.** New reader with old bundle: ignored key, `test_bundle.py:60-69`. Old 0.3.0 reader with new bundle: by construction fine if the old `parse_bundle` defaulted the key (the review says it did, architecture-review.md:33); I could not open `2e03506` to confirm. See OPERATOR-RUN 5. `BUNDLE_SCHEMA` stays `formwork.bundle/v1` (`src/formwork/__init__.py`); acceptable because the key was optional and always empty.
- **P1 above** is the real regression surface: the fix turns the copy path's rewrite from a no-op into a live re-serialisation, and that re-serialisation has a latent corruption bug.
- **P3** No changelog entry for the fix. `CHANGELOG.md` mentions `&#58;` only at `:32` (the 0.3.0 gate note) and never mentions the fold, the removed key or the apply message. `tests/test_version.py:24-28` requires the first heading to be the current version, so an "Unreleased" section cannot be added without a bump; since 0.3.0 is on an unmerged branch, amending the 0.3.0 entry is the honest route. The goldens embed `formworkVersion: "0.3.0"` (`expected/extract.js:218`) and would need regenerating on a bump.

## 4. The new tests

- `tests/test_dsl.py:544-562` flips the old pin (`"<p>a: b</p>" not in canvas`, `'<p>a&#58; b</p>'` in canvas): fails on old code on its own assertions, not just on the import. Not vacuous.
- `tests/test_dsl.py:565-596` asserts style, href and running-text folds against a hand-written expected string, the part record keeps authored HTML, and a colon-free part is untouched. Meaningful, but its running-text case is checked against the author's expectation, not live bytes (see next).
- `tests/test_styling_evidence.py:99-118` is the strong pin: for all seven style samples `stored_inner == stored_text_html(requested["html"])` on the live persisted bytes, and a compile against the live document emits them. **P3**: the loop covers `styleSamples` only; the two `textControls` probes, which carry the running-text colon and the `<strong>/<em>/<ul>` constructs (`discovery.styling.json:2591,2610`), are not in it. Adding them ties the running-text claim to measured bytes rather than to `test_dsl.py:565-596`. The `split("</div>", 1)` at `:109` truncates on a future sample containing `</div>`, but that fails loudly, so acceptable.
- `tests/test_refs.py`: `:147-157` (instance not component id), `:198-203` (duplicate refused, reachable path), `:252-268` (untouched controls byte-identical on the rendered output), `:270-278` (dirty-only, load-bearing as analysed in section 2), `:280-297` (exactly one re-serialisation, idempotent re-apply), `:299-335` (twins get their own values), `:351-362` (plan naming an absent control refused). None passes on old code; none is a substring pin on its own output. Not vacuous.
- `tests/test_cli.py:89`: arithmetic verified above. Note it exercises the identical-value `baseUrl` only on controls dirtied by `siteId`, so it does not by itself prove dirty-only; `test_refs.py:270-278` does.
- `tests/test_generator.py:450-464`: substring pins plus the goldens. It cannot tell whether `created.url` is well-formed at runtime (see P3 below); the item id is right regardless.
- `tests/test_bundle.py:60-69`, `tests/test_generator.py:467-473`: real behaviour, fail on old code.
- **P3** `location.origin + created.url` (`apply.js.j2:53,65`) assumes `SP.Publishing.SitePage.Url` is server-relative. The entity also exposes `AbsoluteUrl`, which needs no composition. If `Url` is site-relative (`SitePages/x.aspx`), both the success log and the new mismatch message print a malformed URL; the item id still identifies the page. Pre-existing on the success log; the fix copied it. See OPERATOR-RUN 6.
- **P3** The mismatch branch is the only post-creation exit that names the page. `setFields` (`apply.js.j2:13` → `_prelude.js.j2:202,221`), `read item` (`:20`), `canvas write` (`:41`) and `verify read` (`:48`) all run after `createSitePage` at `:12` and throw without the id. Outside the review's P1-1 text, adjacent to it.

## Residual risk

The fix rests on one unmeasured step and inherits one unmeasured design gap. The step: SharePoint was only ever sent `:` in text inner HTML and answered `&#58;`; it has not yet been sent `&#58;` there, so "sent equals stored" for a compiled text part is inferred from the attribute path (73 web-part controls, byte-exact) and from the encoder's evident idempotence, not observed. One live apply of a compiled styled part closes it and should be recorded as evidence. The gap: the copy path now rewrites a web part's JSON while its `data-sp-htmlproperties` mirror keeps the source values, and nothing measures which copy SharePoint renders from. Beyond those, text-HTML entities, non-ASCII text, and the `re.sub` template hazard are the three places a real page differs from every fixture in the tree, and all three fixtures are ASCII-only and entity-free, so the suite cannot go red on them. The P1 is the only one of these that can silently corrupt a stored page; the rest fail loudly or not at all.

## OPERATOR-RUN

1. Post-fix live evidence for P1-1 (needs the target site's discovery document `discovery.json` and a spec `page.yaml` with one styled text part, e.g. `<p><span style="color:#a4262c;">Note: 10:30</span></p>`):
   ```
   .venv/bin/formwork compile page.yaml discovery.json --out payload.json
   .venv/bin/formwork gen apply payload.json --name "P1-1 colon roundtrip" > apply.js
   ```
   Paste `apply.js` into the console of a modern page on the target site; expect `byte-exact: true`. Record the console line and the item id.
2. Confirm the crash (expect `re.error: bad escape \u`):
   ```
   .venv/bin/python -c "
   from formwork.canvas import Canvas
   c = Canvas.parse(open('tests/fixtures/collabhome.canvas.html', encoding='utf-8').read())
   q = next(x for x in c.web_part_controls() if x.web_part_title == 'Quick links')
   q.web_part_data['serverProcessedContent']['searchablePlainTexts']['title'] = 'Team’s links'
   q.mark_dirty(); c.render()
   "
   ```
3. Confirm the silent corruption (expect `json.decoder.JSONDecodeError: Invalid control character`):
   ```
   .venv/bin/python -c "
   from formwork.canvas import Canvas
   c = Canvas.parse(open('tests/fixtures/collabhome.canvas.html', encoding='utf-8').read())
   q = next(x for x in c.web_part_controls() if x.web_part_title == 'Quick links')
   q.web_part_data['serverProcessedContent']['searchablePlainTexts']['title'] = 'Quick\nlinks'
   q.mark_dirty(); Canvas.parse(c.render())
   "
   ```
4. htmlproperties mirror: run `formwork process tests/fixtures/collabhome.bundle.json --mapping <the test_cli mapping> --out payload.json`, `gen apply`, apply on the sandbox, open the page and note whether the Document library part shows "Documents" or "Reports library"; then extract it and diff `listTitle` in JSON against the `data-sp-prop-name="listTitle"` text.
5. Old reader with the new bundle (read-only git):
   ```
   git show 2e03506:src/formwork/bundle.py | grep -n webParts
   ```
   Expect a `.get("webParts", [])` or equivalent default.
6. URL shape, in the console of any modern page on the site:
   ```
   fetch(location.pathname.replace(/\/SitePages\/.*/i, "") + "/_api/sitepages/pages?$select=Id,Url,AbsoluteUrl&$top=1", {headers:{Accept:"application/json;odata=verbose"}}).then(r=>r.json()).then(j=>console.log(j.d.results[0]))
   ```
   If `Url` has no leading slash, switch `apply.js.j2:53,65` to `AbsoluteUrl`.
7. The suite itself, which this review could not run:
   ```
   .venv/bin/pytest -q
   ```
