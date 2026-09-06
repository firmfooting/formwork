# Adversarial review: formwork transport hardening (a74bee4..cededeb)

Date: 2026-09-06. Branch `feat/transport-hardening`, two commits: `4b7f8b4`
(advisory document) and `cededeb` (prelude, tests, goldens, README). Read-only
review; nothing was run except read-only git and a denied attempt to execute
the generator (headless python is refused on this host, so byte-identity of
the goldens rests on the dispatcher's pytest run plus a line-by-line read,
stated below).

Reference material read: `dbml-sharepoint/src/dbml_sharepoint/templates/`
`_http.js.j2`, `_site_guard.js.j2`, `_digest_cached.js.j2`; the advisory
`.hermes/plans/2026-09-06_common-pastejs-api-advisory.md` section 4 step 1;
`main`'s `generator.py` at `a74bee4`.

## Verdict

**APPROVE WITH FINDINGS.** No P1. Two P2 (one pre-existing bug that the new
test comment claims is handled; one set of pins that stay green under the
regression they exist to catch). Four P3.

Counts: P1 0, P2 2, P3 4.

## What was checked and held up

Stated briefly so the findings below are read against it.

- **Gate logic** (`tests/fixtures/expected/apply.js:57-66`). `throttleGate`
  holds the promise returned by `.then(() => { throttleGate = null; })`, so
  by the time any `await throttleGate` in `passThrottleGate` resumes, the
  callback has already nulled it and the `while` exits. No deadlock. No
  request is admitted while the gate is set, because every fetch is preceded
  by `await passThrottleGate()` (`:74`). The only admission window is between
  a throttled response arriving and `holdEveryLane` being called (`:75-83`);
  with one sequential caller that window has no second requester. Equivalent
  to `_http.js.j2:54-63`.
- **Attempt counting** (`apply.js:72-88`). `i < attempts` with `attempts = 8`
  gives at most 8 retries and 9 fetches; the warning prints `retry 1/8` to
  `8/8`. Backoff with no `Retry-After` is 1,2,4,8,16,32,60,60 s. Equivalent to
  `_http.js.j2:75-93` minus the timing diagnostics.
- **`spError`** (`apply.js:30-36`). `JSON.parse` of HTML throws into the
  empty `catch`; JSON `null`/number/array short-circuit through `?.` to
  `undefined || text`. `failed()` reads the body once, only on the non-OK
  path, so no double-consume. Identical to `_http.js.j2:28-34`.
- **`odataName`** (`apply.js:20-22`) composes exactly what
  `_site_guard.js.j2:27` does in one expression. `encodeURIComponent` leaves
  `'`, `(`, `)` alone, so `getbytitle('Site%20Pages')` is the emitted path.
  On `main` the literal `getbytitle('Site Pages')` was percent-encoded by the
  browser's URL parser before it left the page (space is in the path
  percent-encode set), so the bytes on the wire are unchanged. Not a
  behaviour change.
- **Doubled braces.** `_APPLY_BODY` is the only `.format()` template; the
  golden shows `{ headers: { Accept: VERBOSE } }` at `apply.js:201`, `:230`
  and the MERGE block at `:208-222` rendered correctly. The prelude is
  concatenated, not formatted, so its single braces are safe.
- **Escaping in the Python source.** `\\/` and `\\.` in the non-raw
  `_JS_PRELUDE` render to `/\/_layouts\/15\/throttle\.htm(\?|$)/i`
  (`apply.js:49`). Correct.
- **Headers, methods, Accepts.** Every call site was diffed against `main`:
  no header lost, no Accept changed, no method changed. `getDigest` still
  POSTs `{}` with verbose Accept and Content-Type, as `main`'s `postJson`
  did. `GetClientSideWebParts` keeps `odata=nometadata`.
- **Apply verify step.** On `main`, a non-OK verify already aborted: an
  error body has no `.d`, so `stored.CanvasContent1` threw a TypeError, and
  an HTML body threw from `.json()`. The new `.ok` check changes the message,
  not the outcome. Same argument for discover's new `scratch read` and
  `scratch read back` checks. `getDigest` now aborts on an empty
  `FormDigestValue` where `main` would have proceeded to a 403 on the next
  POST: the abort moved earlier, no new failure.
- **Goldens.** `git status` is clean, so the on-disk goldens are the
  committed ones. `extract.js` (241 lines) and `apply.js` (243 lines) were
  read in full against `generator.py`; `discover.js` (342 lines) likewise.
  Header lines, `__FWV__` substitution, and apply's default arguments
  (`"Formwork copy"`, `"{}"`, `0`) all match. `git ls-files --eol` reports
  `i/lf w/lf` for all three. Mechanical equality was established by the
  dispatcher's 67-test run, which includes the three golden tests.
- **Scope.** `git diff --name-only a74bee4..cededeb` lists exactly the
  advisory, README, `generator.py`, the three goldens, and
  `test_generator.py`. `pyproject.toml` and `__init__.py` untouched
  (`0.2.0`). The branch has no upstream configured; `git ls-remote` was
  denied so absence on the remote is not independently confirmed. No
  `test/manual/`, no probe, no catalogue: steps 2 to 5 not touched.
- **Citations.** Every line range cited in the prelude comments matches the
  partial as read today: `_http.js.j2:25-34`, `:36-44`, `:45-63`;
  `_digest_cached.js.j2:9-42`; `_site_guard.js.j2:24-27`.

## Findings

### P2-1. `fileName` is taken from `location.pathname` undecoded, so the new `$filter` quoting is only half right

- `src/formwork/generator.py:242-245`; `tests/fixtures/expected/extract.js:195-198`;
  pin at `tests/test_generator.py:222-227`.
- `location.pathname` is always percent-encoded. A page whose file name is
  `Bob's page.aspx` has pathname `.../SitePages/Bob's%20page.aspx` (the URL
  standard does not encode `'` in a path, it does encode the space). The
  script builds `FileLeafRef eq 'Bob''s%20page.aspx'`, then
  `encodeURIComponent` turns the `%` into `%25`. The server decodes once and
  compares the literal `Bob's%20page.aspx` against `Bob's page.aspx`: zero
  rows, and the script aborts with `expected 1 page for
  SitePages/Bob's%20page.aspx, got 0`. A link that carried `%27` for the
  apostrophe fails the same way with no doubling ever applied.
- Pre-existing on `main` (same `fileName` derivation, `a74bee4`
  `generator.py:121`), so not a regression of this change. It is reported at
  P2 because the new test's comment states that "a page named `Bob's
  page.aspx` is legal" and that the rule "applies", while the emitted script
  cannot extract that page. The fact was ported; the input it is applied to
  was not looked at.
- Fix: `odataLiteral(decodeURIComponent(fileName))`, regenerate the extract
  golden, and change the pin to assert the decoded form. Consider decoding
  `PAGE_PATH` for the error message as well.

### P2-2. The throttle pins are satisfied by the function definitions alone

- `tests/test_generator.py:163-171` (`test_throttle_is_detected_on_the_final_url_not_the_status`).
- `"holdEveryLane("` matches `function holdEveryLane(seconds)`
  (`generator.py:105`) and `"passThrottleGate()"` matches `async function
  passThrottleGate() {` (`:102`). Delete `await passThrottleGate();` at
  `generator.py:118` and `await holdEveryLane(wait);` at `:127`: the test stays
  green, and every retry now goes out immediately with no pause, which is the
  opposite of the fact being pinned.
- `"THROTTLE_PAGE.test(res.url"` is satisfied by the message builder at
  `generator.py:122` alone. Change the `||` at `:95` to `&&` so the throttle
  page is only recognised when the status is also 429 or 503: the test stays
  green, and the measured 406 redirect, the one case the fact exists for, is
  never retried. `"res.status === 429 || res.status === 503"` still matches
  because the change is on the next line.
- The golden test would catch both edits, but only until someone regenerates
  the golden, which is exactly what the regeneration runner exists to make
  routine. The string pins are the machine check that survives regeneration
  and they do not currently pin the behaviour.
- Fix: pin the call sites with their `await` (`"await passThrottleGate();"`,
  `"await holdEveryLane(wait);"`) and pin `isThrottled` across its two lines
  with one regex, for example
  `r"res\.status === 503\s*\|\| THROTTLE_PAGE\.test\(res\.url"`. If a
  stronger check is wanted later, the prelude is plain JS apart from
  `location`; a `node` run with a stubbed `fetch` that returns one throttle
  redirect then a 200 would prove the loop, and node is already a CI
  dependency for `node --check`.

### P3-1. `postJson` is now dead code in all three scripts

- `src/formwork/generator.py:138-146`; emitted at `apply.js:94-102`.
- Its only caller on `main` was `getDigest`, which now issues its own
  `fetchWithRetry` so it can run the guarded parse on the raw response. Nothing
  calls `postJson` in the prelude or any body. It also contributes one of the
  `if (!x.ok)` matches to the `checks >= 6` floor at `test_generator.py:184`.
  Drop it and adjust the floor, or leave it with a comment saying it is kept
  for a future body.

### P3-2. Goldens embed the version four times and never exercise a real payload

- `tests/fixtures/expected/{extract,discover,apply}.js:1`;
  `extract.js:224` (`formworkVersion`); `tests/test_generator.py:6`.
- The apply golden uses the default arguments; this is documented in the
  module docstring, so the brief's question is answered. The defaults are
  stable, so that in itself is not brittle. Two things are:
  - Every version bump changes all three goldens with a diff that is only
    version strings. The regeneration runner makes it a one-command chore,
    but "review the diff like code" has nothing to review on that diff, and a
    release commit that forgets the step fails CI.
  - The default payload is `JSON.parse("{}")` (`apply.js:191`), so the one
    place the apply template interpolates operator data
    (`_APPLY_BODY.format(payload=json.dumps(...))`) is pinned only with an
    empty object. The only escaping test is `{"k":1}` at
    `test_generator.py:142-145`. A payload containing `{`, `}`, `"`, `\`,
    `'`, `</script>` and a non-ASCII character is the case that would catch a
    regression in that embedding. Suggest a second apply golden generated from
    such a fixture.

### P3-3. Inherited edges in `fetchWithRetry`: exhausted retries and `Retry-After` forms

- `src/formwork/generator.py:116-132`; `apply.js:72-88`.
- After the eighth throttled retry the final response is handed to
  `failed()`, whose message is the first 300 characters of the throttle page
  HTML, for example `page create -> 406 <!DOCTYPE html>...`, with no word
  "throttled" in the thrown error. The eight `console.warn` lines above it are
  the only diagnosis; a copied error message alone misleads.
- `Number(res.headers.get("Retry-After"))` is `NaN` for the HTTP-date form,
  so it is silently treated as absent. A large numeric value is honoured
  uncapped (`Retry-After: 3600` sleeps an hour; the cap of 60 s applies only to
  the fallback backoff, and the comment at `:111-112` reads as if it applied to
  both).
- All three behaviours are identical to `_http.js.j2:75-93`, so this is a
  faithful port. Noted so the choice is a known one.

### P3-4. Newline claim: the docstring is inexact and there is no `.gitattributes`

- `tests/test_generator.py:43-46` (`write_golden`); no `.gitattributes` in
  the repository; `core.autocrlf` unset here.
- The explicit `newline="\n"` is the right fix and the on-disk goldens are LF.
  The docstring's "reads as modified locally while producing an empty diff"
  describes neither case: with `autocrlf=false` a CRLF write shows a whole-file
  diff of line endings; with `autocrlf=true` git normalises on stage and the
  file shows clean. Reword.
- On a Windows checkout with `autocrlf=true` the goldens arrive as CRLF and
  the byte-for-byte test passes only because `read_text` translates them back
  on read (`:237`). A one-line `.gitattributes`
  (`tests/fixtures/expected/*.js text eol=lf`) would make the on-disk bytes
  match the claim. That is a new file outside the named set, so a follow-up,
  not this change.

## Not findings, recorded so they are not re-raised

- `getDigest` is still called per use with no cache (three POSTs in apply,
  four in discover). The advisory's step 1 asked for the guarded parse, not the
  cache, and the dispatcher's brief did not include it. In scope as delivered.
- The `getbytitle('Site Pages')` list title is locale-dependent and fails on
  a non-English web. Pre-existing on `main` and not touched by the port.
- `test_non_ok_responses_surface_the_server_reason` scans a 200-character
  window after each `if (!x.ok)`. With the current layout no empty branch is
  close enough to a neighbour's `failed(` to be satisfied by it; borderline in
  `createSitePage`, not currently exploitable.
