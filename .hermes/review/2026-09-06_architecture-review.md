# Architecture review: firmfooting/formwork

Reviewed 2026-09-06 at HEAD `2e03506` (`feat/m3-dsl-and-release` = `main` `f0e0a44` + the 0.3.0 commit). Read in full: `src/formwork/` (10 modules, 5 templates), every test and golden, README, CHANGELOG, pyproject, CI, both `.hermes/plans/` documents, both prior `.hermes/review/` documents, and the structure of the three fixtures. Not done: the test suite was not run (Python execution is not granted to this session) and the Hindsight banks were not readable (tools not registered). Every finding below rests on reading, with file:line citations.

## Verdict: sound-with-conditions

The shape is right for what it claims: one canvas model, one escaping function, generated paste-ins as the only transport, refusals that carry their measurement. Two defects break the pillars in practice today, both cheap to fix:

1. The compiler emits bytes that apply's byte-exact verify cannot accept for any text part containing a colon. The page is created, then the script throws.
2. The extract paste-in ships an empty `webParts` list, so the copy path's reference rewrite does nothing on a live bundle.

Conditions for "sound": fix P1-1 and P1-2, bind payloads to a site and a time (P2-1), and turn the scattered measurement findings into one registry (P2-3).

## P1 — blocking

### P1-1 Compile and apply disagree on the one measured normalisation

- `src/formwork/dsl.py:337-347`: `_text_control` records that SharePoint rewrites `:` to `&#58;` inside text-control HTML, "so nothing is folded here". Compile emits a literal `:`.
- `tests/test_dsl.py:556-557` pins it: `"<p>a: b</p>" in compile_page(...).canvas`.
- `src/formwork/catalogue.py:49-75`: the compile gate folds `&#58;` to `:` on both sides, so the gate passes.
- `src/formwork/templates/apply.js.j2:51,56-58`: verify is `stored.CanvasContent1 === PAYLOAD.canvas`; on mismatch it throws after the page was created and merged. No fold, no recycle.
- Live evidence the bytes differ: `tests/fixtures/discovery.styling.json:2581-2582`, `requestedCanvasChars 97907` vs `storedCanvasChars 97947`. The 40-char delta is the colon rewrite on the text samples.
- The README recommends colon-bearing HTML for five of its seven styled samples (`README.md:117-123`). Any `style="…"`, any absolute `href`, any "Note: …" carries a colon.
- The refusal at `dsl.py:392-398` warns that an *unmeasured* text shape "can abort after page creation on the byte-exact check". A measured shape with a colon aborts the same way.

Effect: every compiled page with a styled text part or an absolute link fails apply after creation and leaves a half-written page behind. The copy path is unaffected only because an extracted canvas has already been normalised by SharePoint. The two paths converge on transport but not on normalisation state (axis 5).

Recommendation: the compiler is the one place to fold. Emit `&#58;` for `:` inside the `data-sp-rte` body at `dsl.py:365` (what SharePoint stores). The both-sides fold in `catalogue.py` then only needs the requested side, and the gate keeps working. Keep apply's `===` strict; it is the contract's value. Add a live-verified apply of a compiled text part with a colon to the evidence (a `page.text.colon-roundtrip` finding, see P2-3). On mismatch, apply should recycle the page or at minimum print the item id and say the page still exists.

### P1-2 The extract paste-in ships an empty `webParts`, so the copy path rewrites nothing

- `src/formwork/templates/extract.js.j2:45-46`: `sections: [], webParts: []` unconditionally; `tests/fixtures/expected/extract.js` pins it.
- `src/formwork/refs.py:51,58-90,142`: `scan` and `apply_plan` read only `bundle.web_parts`; `src/formwork/bundle.py` defaults it to `[]`.
- The only bundle with a populated `webParts` is hand-authored: `tests/fixtures/collabhome.bundle.json:45ff`, which `tests/test_refs.py` and `tests/test_cli.py` run against.

Effect: on a live 0.3.0 bundle `formwork inspect` reports zero site-bound values and `formwork process` writes the source canvas unchanged with "0 refs rewritten, 0 unresolved", which reads as success. `README.md:181` documents inspect as listing every site-bound value. A page copied cross-site keeps the source `baseUrl`, `siteId`, `webId` and list ids.

Two more defects in `refs.py` that surface the moment `webParts` is populated:

- `refs.py:167-171` matches canvas controls to web parts on `id`, which is the web-part *type* GUID (`collabhome.bundle.json:47-48`: `id` `8c88f208…`, `instanceId` `…0001`). Two Quick Links on one page both receive the first entry's data.
- `refs.py:169-170` marks every matched control dirty whether or not the plan changed it, so all web-part controls are re-serialised through `json.dumps` (`canvas.py:70-78`). That defeats the "re-escapes only the controls it changed" promise at `README.md:238-239` for the process path. `json.dumps` defaults to `ensure_ascii=True`, so any non-ASCII title or property is re-emitted as `\uXXXX`; whether SharePoint stores that unchanged is unmeasured.

Recommendation: drop `webParts` from the bundle contract. `refs.scan` walks `Canvas.parse(bundle.canvas_html).web_part_controls()` and addresses refs by `instanceId` plus JSON path; `apply_plan` mutates `control.web_part_data` in place and marks dirty only when a value changed. That makes `refs.py` the second consumer of the canvas model instead of a parallel rewriter over a shadow list, and fixes both defects above. `build_plan` (`refs.py:93-134`) has no branch for kinds `link` or `image`; add mapping keys or state in the README that they are report-only.

## P2 — should fix

### P2-1 Nothing binds a discovery document, a payload, or an apply run to a site or a time

- `src/formwork/catalogue.py:105-132`: `parse_discovery` reads `schema`, `components`, `textControls`. `web`, `discoveredAt`, `placements`, `styling` are ignored, so the styling measurement is never consulted at runtime.
- `src/formwork/cli.py:64-73,135-141`: the payload carries `schema`, `sourcePage`, `title`, `canvas`, `unresolved`. No web url or id, no discovery timestamp, no formwork version, no hash of the discovery it was compiled against. The dict is assembled inline twice.
- `src/formwork/cli.py:163-171`: `gen apply` embeds any JSON without checking `schema`; there is no `parse_payload`.
- `src/formwork/templates/apply.js.j2:7-13`: apply never compares the running site to anything in the payload.

Attack: compile against site A's discovery, or a discovery from six months ago, and paste the apply script into site B. Components resolved by alias on A; on B they may be hidden or absent. The MERGE has no reason to refuse (the probe shows the item stores web-part controls as opaque bytes), verify passes byte-exact, and the operator reads "verify OK" for a page whose web parts do not render. The pillar "DSL refuses what discovery doesn't declare" holds only when discovery and apply are the same site, and nothing checks that.

Recommendation: a `Payload` dataclass with `parse_payload` carrying `compiledWith: {formwork, discoveryWebId, discoveryWebUrl, discoveredAt, discoverySha256}`; `gen apply` refuses anything else; `apply.js.j2` GETs `web?$select=Id` first and stops on mismatch unless `--allow-cross-site`. Compile warns when `discoveredAt` is older than a stated window (30 days) unless `--stale-ok`. Both payload dicts in `cli.py` become one constructor.

### P2-2 `gen apply --name` is dead, and page fields the README says are copied are not

- `src/formwork/cli.py:203`: `--name` is required.
- `src/formwork/templates/apply.js.j2:7,12`: `PAGE_NAME` goes to `createSitePage`, which posts `{__metadata, PageLayoutType: "Home"}` (`_prelude.js.j2:181-196`) and never sends the name. The MERGE at `apply.js.j2:37` writes `PAYLOAD.title`.
- Only `CanvasContent1`, `Title` and `PromotedState` are written. `PageLayoutType` is hard-coded `"Home"`. `Description`, `BannerImageUrl` and `LayoutWebpartsContent` (the title area) are extracted (`extract.js.j2:18-19`) and dropped.
- `README.md:223-224` claims "Copied: page title, description, layout type, promoted state".
- The created page's check-in and publish state is not stated anywhere and no probe records it.

Recommendation: drop `--name`, or send it as the page file name (unmeasured, so probe it first). Either copy `PageLayoutType`, `Description`, `BannerImageUrl`, `LayoutWebpartsContent` through the MERGE and verify them, or correct the README to "title, promoted state, canvas". Have apply's verify read back `File/CheckOutType,MajorVersion,MinorVersion` and log them so the created page's state is a measured fact, then decide whether apply calls check-in or publish.

### P2-3 Measurement findings are scattered and partly hand-authored; formwork needs the dbml-sharepoint treatment

Where findings live today: constant docstrings (`dsl.py:40-88`), probe comments (`discover.js.j2:105-141`), the 6.86 MB fixture, `tests/test_styling_evidence.py`, the README "Styled text" and "Emphasis" sections, CHANGELOG, `canvas.py:10-14`, and `_prelude.js.j2:24-47`. Seven surfaces, no ids, no single authority.

Specific defects:

- `styling.sectionEmphasisMechanism` (`discovery.styling.json:3202-3234`) is the evidence behind the section-emphasis refusal (`dsl.py:61-68`) and is pinned by `test_styling_evidence.py:82,165-171`, but `discover.js.j2` never emits that key. It was hand-added after a manual SavePage experiment. Re-running discover yields a document that fails `test_styling_evidence.py` and a catalogue that no longer carries the evidence the refusal cites. The block's own `unmeasured` list (`:3229`) admits "zoneId GUID generation rules (mine were invented)".
- `discover.js.j2:105-106` ships `TODO(measure, 2026-09-06): live run pending` inside the operator paste-in, pinned by `test_generator.py:167,204`, although the measurement exists.
- `ZONE_EMPHASIS_VALUES = (1, 2, 3, 4)` (`dsl.py:40-48`) accepts 1 and 4 explicitly without a read-back. The set lives in code, not in the discovery document, so a tenant that drops 4 cannot be told apart from this one.
- Every measurement is a Python constant keyed by a date string; the only staleness signal is a grep for "2026-09-06".

What breaks on a second tenant or SharePoint version: everything that is a constant rather than catalogue data. `SECTION_FACTORS`, `ZONE_EMPHASIS_VALUES`, the escaping table (`canvas.py:28-38`), `dataVersion "1.0"` (`dsl.py:307`), and `"Site Pages"` (`_prelude.js.j2:68`) are all asserted from one team site on one tenant on one day. The discovery document exists to carry per-site facts, yet the compiler consults only components and text samples.

Recommendation, in order:

1. `FINDINGS.md` as the sole authority (SURFACES-style): one row per finding with a check-id (`page.text.colon-rewrite`, `page.emphasis.control-merge`, `page.emphasis.section-savepage`, `page.transport.throttle-redirect`, …), date, tenant, fixture path plus JSON pointer, and the code that cites it. `test_styling_evidence.py` becomes "every check-id cited in code exists in FINDINGS.md and points at bytes in a fixture".
2. Make `discover.js.j2` emit a `findings` block with check-ids and `measuredAt`, including a re-runnable SavePage probe for the section-emphasis mechanism (the advisory's undone step 2). If SavePage cannot be probed safely, mark that finding `manual` in FINDINGS.md and stop pinning it as if discover produced it.
3. Move tenant-variable facts into the discovery document and have `parse_discovery` read them: the emphasis values actually read back, the section factors observed, and the Site Pages list identity (id and server-relative URL) rather than its title.
4. Remove the shipped TODO and cite the check-id instead.

### P2-4 Preview's trust boundary is weaker than its own header claims

- `src/formwork/templates/preview.html.j2:1` says "No SharePoint, no network, no script"; line 38 inlines `{{ part.html | safe }}`; there is no CSP.
- `src/formwork/text.py:74-82` is a blocklist and says so ("a stated trust boundary, not sanitisation"). Bypasses include: `href="javascript&#58;alert(1)"` (entity-encoded scheme; the regex wants the literal), `href="java&#9;script:…"` or a literal tab (tabs are allowed at `text.py:96-99` and browsers strip them from schemes), `<img/src/onerror=alert(1)>` (the handler regex at `:78` requires whitespace before `on`), `<meta http-equiv=refresh>`, `<base href>`, and `<form>` with `formaction`.
- `tests/test_preview.py:155-161` asserts `"<script" not in html`, which no bypass trips.
- A payload JSON handed to `gen apply` never passes through `text.py`; a discovery document's `preconfiguredEntries[].properties` flow into `default_properties` (`dsl.py:308`) unchecked.

Threat model per the brief: shared spec, multi-author site, hostile or stale discovery. The preview is the one place a spec's bytes execute in an operator's browser without SharePoint's own sanitiser in front. The canvas side is lower risk because the text web part sanitises on render.

Recommendation: keep the refusal list as the *canvas* contract (it protects the wrapper) but stop trusting it in the preview. Either escape text parts and show them as source, or run an allowlist parser (`p h1-h4 ul ol li strong em br mark`, `a[href]` restricted to http(s) and relative, `span[style]`) that drops and reports everything else, and add a `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">`. Reword line 1 to what is true. Validate payload shape in `gen apply` (P2-1).

### P2-5 Golden version churn, and what the goldens actually protect

- All four goldens embed `0.3.0` on line 1, `extract.js` again at line 218; `tests/test_version.py` pins `__version__` to pyproject and CHANGELOG. Every release touches four goldens with a version-only diff, which is the noise that hides a real transport change in the same diff.
- No `.gitattributes`. The goldens are LF here (`git ls-files --eol`), CI runs on Windows, and a contributor with `core.autocrlf=true` who regenerates via `python tests/test_generator.py` writes CRLF goldens.
- The node gate is `node --check` on extract, apply and apply-payload (`ci.yml:61`); discover, the script with the most logic, is excluded.
- Nothing executes any generated script. The throttle loop (`_prelude.js.j2:117-133`), digest parsing and `spError` have only substring pins.

Recommendation: render goldens with a sentinel version (`0.0.0-golden`; give the generators a `version` parameter) and keep one test that the real generator stamps `__version__`. Add `.gitattributes` with `*.js text eol=lf` and `*.json text eol=lf`. Add discover to the node gate. Add one node test that loads the prelude with a stubbed `fetch` and exercises a 429 with numeric Retry-After, the throttle-page redirect, a contextinfo response without `GetContextWebInformation`, and a 406 that is not throttle. Packaging is not the answer; the goldens are the contract and should stay. They just should not encode the version.

### P2-6 Two serialisers for one canvas shape, pinned by substrings only

- JS: `discover.js.j2:175-179` `esc()` and `:180ff` `webPartBlock`/`textBlock`. Python: `canvas.py:28-38` `escape_attribute` and `dsl.py:279-334,337-368`.
- Divergences between what discover measured and what compile emits: position values are ints in the probe and floats in compile (`dsl.py:266-268`); `controlIndex` counts per section in compile and per column in the probe (m12 review, still true); ids are `0000…-{ordinal:012d}` (`dsl.py:276`) while the probe used `…-0001-…` (`discovery.styling.json:2590`); `dataVersion` is hard-coded `"1.0"` (`dsl.py:307`) whereas the probe forwards `entry.dataVersion` and the editor stores `"1.6"`/`"2.1"` (`tests/fixtures/savepage-section-emphasis.json`); compile never emits a `pageSettingsSlice` control (`controlType 0`), which the editor-saved page carries.
- `test_styling_evidence.py:141-152` compares key order and the emphasis block, not values, so none of this fails.

Each divergence is a guess the measured MERGE tolerates because the item stores opaque text. The render-time question (does the editor accept the page, renumber, or drop `dataVersion 1.0` properties on first save) is unmeasured.

Recommendation: one cross-language byte test: take `styling.styleSamples.requested[*].canvas` and `sectionSamples.requested[*].canvas` (bytes the JS built) and assert `_control_for`/`_text_control` reproduce them from the same inputs. Then make compile match the probe (ints, per-column index, forwarded `dataVersion`). Add "open the created page in the editor, save, re-read, diff" as a finding (`page.editor.roundtrip`). That is the measurement that says whether a compiled page is a page or merely stored bytes.

### P2-7 There is no section model, and `dsl.py` is where one will be forced

- `canvas.py` models controls and a preamble only; sections exist as numbers inside each control's `position`.
- `dsl.py` (431 lines) holds the spec vocabulary, validation, the measured-refusal policy, geometry, and the byte emitter. Section emphasis via SavePage, backgrounds, collapsible and vertical sections, and page templates each add to all five.
- `refs.py` and `dsl.py` are the two half-rewriters the brief asks about: both build `web_part_data` dicts and both reach into `Control`, from different models (a flat list vs placements). `preview.py` derives columns from `placements()` a third time.

Recommendation: split `dsl.py` into `spec.py` (vocabulary, validation, refusal policy; returns `Placement`s), `emit.py` (placement plus component to `Control`), with `compile_page` as glue. Add `Section`/`Column` to the canvas model when section emphasis lands so refs, preview and compile walk one structure. Do this after P1-2, which decides what `refs.py` walks.

## P3 — notes

- **Unknown spec keys are silently ignored.** `dsl.py:128-159` refuses only the enumerated unencodable keys; `emphasise`, `colum`, `part` (singular) are dropped without a word. `README.md:169-170` says "Nothing in a spec is silently dropped". Refuse unknown keys and list the known ones, as the section-type check already does.
- **`Site Pages` by display title.** `_prelude.js.j2:68` is localised on non-English site collections. Extract already captures `listId` (`extract.js.j2:9,39`); apply and discover can use `web/GetList('<webPath>/SitePages')`. A second-tenant blocker in practice.
- **Extract on sub-folder pages.** `extract.js.j2:5` throws a bare TypeError on `/SitePages/folder/page.aspx`, and the `FileLeafRef` filter (`:16-17`) matches every same-named page across folders. Use `FileRef eq '<server-relative path>'`.
- **`build_plan` truthiness.** `refs.py:129` `if new_value:` treats an empty-string override as unresolved. Use `is not None`.
- **Preview resolves hidden and extension components as placeable.** `preview.py:84-85` calls `resolve_component` but never `_check_placeable` (m12 P3-5, still unfolded). Compile refuses what preview showed as fine.
- **Discover has a side effect and a residue.** It creates a scratch page and recycles it (`discover.js.j2:382ff`); the page existed briefly and sits in the recycle bin. State this in the README and give the scratch page a recognisable name prefix.
- **`getDigest` per write.** `_prelude.js.j2:144` is uncached; apply calls it three times, discover many more. Cache with `FormDigestTimeoutSeconds`.
- **Retry-After.** `_prelude.js.j2:122` `Number(header) || backoff` handles an HTTP-date by falling to backoff (fine) but honours an absurd numeric value uncapped. Cap at 300 s and say "throttled" in the exhausted-attempts error.
- **Emphasis 1 and 4, and non-ASCII content, are unmeasured but accepted** (`dsl.py:45-48`; `ensure_ascii` in P1-2). Probe both in the next discover run or refuse them.
- **Repository hygiene.** `tests/fixtures/discovery.styling.json` is 6.86 MB, committed in `a244d58`, and pins a real tenant URL (`test_styling_evidence.py:81`). Two more probe runs at that size make clone time a contributor cost; strip `components[].Manifest` bodies that no test asserts on, or use Git LFS. No tags exist, no wheel is built, `pip install git+…` is the only distribution.
- **CI depth.** One Python version (3.11) though pyproject says `>=3.11`; add 3.12 and 3.13. `tests/test_cli_compile.py:29` uses `__import__("json")` in a module that already imports json.
- **Parser description** at `cli.py:183` still reads "SharePoint page copier: extract, process, apply."

## What is genuinely good, where it protects a decision

- **Byte-exact, dirty-only canvas round trip** (`canvas.py:60-79`, `tests/test_canvas.py`). This is what makes the copy path safe to extend and the compile path checkable. It holds once P1-2 stops marking every control dirty.
- **Goldens plus `node --check` plus substring pins that survive regeneration** (`tests/test_generator.py:404-470`). The pins stop a regeneration from quietly rewriting a transport fact. Keep that split when the version sentinel lands.
- **`persisted_matches` folding both sides** (`catalogue.py:49-75`, `test_dsl.py:543-557`). Learned from a real failure, and the test names the failure. The gate is right; P1-1 is about the emitter.
- **Refusals that carry their measurement** (`dsl.py:61-88`, `test_styling_evidence.py:184-195`). A refusal with a date and a fixture pointer is the cheapest form of a findings registry. P2-3 asks for ids and an authority file, not a different idea.
- **The single-source `Site Pages` test** (`test_generator.py:404`). The right shape for every other tenant-variable string.
- **The review loop works.** Both prior reviews' P2s are folded with citations in the code, and the unfolded P3s are still visible. That property is what makes "sound-with-conditions" a safe verdict.

## Axis summary

| Axis | Verdict | Findings |
| --- | --- | --- |
| 1 Module boundaries | Coherent on the compile side; `refs.py` is a second rewriter over a shadow list that extract never fills | P1-2, P2-7 |
| 2 Golden strategy | Right idea, wrong content: version in goldens, no EOL pin, nothing executed | P2-5 |
| 3 Measurement contract | Seven surfaces, no ids; one finding hand-authored and not re-runnable; tenant facts are constants | P2-3, P2-6 |
| 4 Trust boundaries | Canvas side adequate; preview inlines blocklist-filtered HTML and claims "no script"; no site binding | P2-4, P2-1 |
| 5 Two apply paths | Converge on the payload dict and transport, not on normalisation state | P1-1, P2-2 |
| 6 Next six months | Nothing yet for templates, variables, multi-page, navigation, permissions, publish state, re-probing, distribution | below |

## What I would do next quarter

In order. Each item is a week or less except the last two.

1. **Fix both P1s and re-measure.** Colon fold in the compiler; `refs.py` over the canvas model; one live apply of a compiled page with a styled text part, recorded as a finding.
2. **Payload provenance and the apply guard** (P2-1). After this, "DSL refuses what discovery doesn't declare" is true end to end rather than only inside one process.
3. **FINDINGS.md and check-ids** (P2-3), with discover emitting a `findings` block. Port the advisory's undone step 2: a manual probe script that re-runs every finding and diffs against the registry. Put a monthly re-probe lane in the README and a `discoveredAt` age warning in compile. Measurement rot is the failure mode this design cannot detect by itself.
4. **Measure the editor round trip** (P2-6): create via apply, open in the editor, save, re-extract, diff. This settles whether floats, ids, `dataVersion` and the missing `pageSettingsSlice` matter, and it is the precondition for section emphasis via SavePage.
5. **Page state and identity** (P2-2): file name, layout type, description, banner, check-in and publish, and a measured answer on permission inheritance for a created page. Then multi-page: a spec that is a list of pages sharing one discovery, with `navigation` an explicit refused-until-measured key.
6. **Templates and variables.** Jinja is already the display layer. Let `page.yaml` be a Jinja template over a `vars` file, rendered with `StrictUndefined` before YAML parsing. No DSL change is needed.
7. **Distribution and gates.** Tag 0.3.x, build a wheel in CI, `pipx install`. Add Python 3.12 and 3.13 and the discover script to the gates. Golden version sentinel and `.gitattributes` in the same change (P2-5).
8. **Section model** (P2-7) only once section emphasis via SavePage is measured. Do not pre-build it.
