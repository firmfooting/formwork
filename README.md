# formwork

Declarative SharePoint modern pages. Write the page as YAML, compile it against
the site's own component catalogue, preview it offline, and pour it in from
the browser console. Or copy an existing page from one site to another.

The name is the trade: formwork is the mould you build once and reuse for many
identical pours. Build a page once — news, quick links, document library,
whatever your layout is — then reuse the mould across teams, sites, or tenants.

No admin consent, no app registration. The paste-ins run in your own browser
session over same-origin REST, so they can only read and write what you can
already read and write.

## The authoring workflow

```
target site                     your laptop                          target site
┌─────────────┐  gen discover  ┌─────────────────────────────┐  gen apply  ┌─────────────┐
│ DevTools    │ ─────────────> │ page.yaml ──compile──> payload │ ─────────> │ DevTools    │
│ console     │  catalogue     │           └─preview─> html     │  paste-in  │ console     │
└─────────────┘                └─────────────────────────────┘             └─────────────┘
```

1. **Discover** the site once. `formwork gen discover` prints a paste-in that
   enumerates every placeable component via `GetClientSideWebParts` (73 on a
   stock team site, 285 including hidden and extension components), creates a
   scratch page, places one control per component across one-, two- and
   three-column sections, adds the text and styling probes described under
   [Measured SharePoint behaviour](#measured-sharepoint-behaviour), saves,
   reads back what SharePoint persisted, recycles the scratch page and
   downloads `formwork-discovery.json`: the site's component catalogue plus
   the measurements the compiler relies on. `formwork components
   formwork-discovery.json` lists what it found.

   The paste-in also carries the web-part property, one-third layout and
   list-binding probes under additive keys; the compiler reads them through
   the catalogue for a part's `properties`, a section's columns and a
   part's `bind`. For the list bindings it creates two containers of its
   own, the custom list "Formwork Probe Source" and the document library
   "Formwork Probe Docs", and recycles both after the scratch page; a
   refused create or recycle is recorded in the document rather than
   failing the run, so check the console line if either name already exists
   on the site.

2. **Declare** the page in `page.yaml`. Sections, columns, parts, text, and
   the emphasis of a part; see [Writing the spec](#writing-the-spec).

3. **Compile** it: `formwork compile page.yaml formwork-discovery.json`
   resolves every component against the live catalogue by alias or title,
   emits the section geometry (`sectionFactor` 8/4 for two-thirds, 12 for
   one, 4/4/4 for three), applies property overrides, compiles text parts to
   text controls and writes `formwork-payload.json`. It prints one line per
   placed part. An unknown or hidden component refuses to compile: nothing is
   placed that the site did not declare placeable. When `FINDINGS.md` is in
   the working directory (or named with `--findings`), compile also checks
   the age of every measurement the spec relies on; see
   [The findings registry](#the-findings-registry).

4. **Preview** it at any point, catalogue or not: `formwork preview page.yaml
   --out preview.html` renders the spec as a standalone HTML page, sections
   in order, columns at their factors on a 12-column grid, text parts inline,
   other parts as titled placeholder cards. Pass `--discovery` to show the
   catalogue's titles and descriptions. No SharePoint calls, no network. The
   preview validates the spec exactly as the compiler does, so a spec that
   previews will compile as far as the spec itself is concerned.

5. **Apply** it: `formwork gen apply formwork-payload.json --name "Team home"`
   prints the second paste-in with the payload embedded. Run it from the
   console on any page of the target site. It creates the page through the
   `sitepages` API, writes the canvas with an item MERGE under `If-Match`,
   then reads back what SharePoint stored and compares it byte for byte.
   If the bytes differ the script throws, naming the new page's item id and
   URL: the page exists with what SharePoint stored, and Formwork does not
   recycle it. Keep it or recycle it yourself. Compile emits text HTML in
   the stored spelling (`:` as `&#58;`, see "Text parts"), so that rewrite
   does not trip the check.

   **Provenance guard.** The payload carries a `provenance` stamp written by
   `compile`: the formwork version, the SHA-256 of the discovery file's
   bytes, the discovery's web id, web URL and timestamp, the spec name and
   the compile time (`compile` prints it on the line after "payload
   written"). When the compile used the template layer, the stamp also names
   the vars file and its SHA-256, a page's own `vars:` file and its SHA-256,
   and the sorted `--set` key names — never their values (see "Templated
   specs"). Before it creates anything, the apply script reads the web it
   runs on and refuses, listing the stamp's value beside the observed one,
   when the web id or URL differs, when the payload's formwork is newer than
   the script's own version, or when there is no stamp at all (a payload from
   before 0.5.0). To apply a payload on a different web on purpose, set
   `FORCE_SITE_MISMATCH = true` at the top of the script; nothing overrides
   the version check. `--promoted-state 1` sends `PromotedState` inside the
   create body, where it was measured persisting (beside the Article layout,
   `page.promoted-state.create-is-effective`); the post-create MERGE the
   script used before 0.5.0 read back 0 on the Home layout. The script prints
   the stored value beside the byte-exact result and warns if it differs.

## Writing the spec

```yaml
page: Team demo home
sections:
  - type: two-thirds
    parts:
      - component: NewsWebPart
        emphasis: 2
      - text: |
          ## Welcome
          The **team** page. See the [handbook](/sites/T/SitePages/Handbook.aspx).
        column: 2
  - type: one
    parts:
      - component: EventsWebPart
        displayTitle: What's on
        properties: {layoutId: "Compact"}
      - text: "<p>Raw <em>HTML</em> is fine too.</p>"
```

### Sections and parts

A section has a `type` (`one`, `two`, `three`, `two-thirds`, `one-third`)
and `parts`. A part names either a `component`, by alias or by catalogue
title, with optional `properties` and `displayTitle`, or a `text` block.
`column` places the part (1-based); it defaults to the first column.

### Text parts

Text is HTML when it starts with `<` or carries `format: html`, otherwise a
small markdown subset: `#` to `####` headings, paragraphs, `-`/`*` and `1.`
lists, `**bold**`, `*italic*`/`_italic_`, and `[text](url)` links (http,
https, mailto or relative). Anything else — blockquotes, tables, code,
images, rules, nested lists, raw tags — is refused with the line number
rather than guessed at. On both paths `<script>`, `<style>`, `<iframe>`,
`<textarea>`, `<svg>`, comments, inline `on*=` handlers,
`javascript:`/`data:`/`vbscript:` URLs, `data-sp-` attributes and control
characters are refused.

Text parts compile only against a discovery document whose text probes
persisted with at most the `:` to `&#58;` rewrite (measured 2026-09-06, see
below). A document without that measurement, or whose samples differ in any
other way, refuses to compile text parts and says why. Compile emits the
inner HTML in that stored spelling, every `:` as `&#58;` (in a style
attribute, an absolute `href`, running text), so the payload carries what
SharePoint will store and apply's byte-for-byte read-back holds. The
compiled part record keeps the HTML as you wrote it.

### Styled text

Text parts take inline styling as plain HTML. Measured 2026-09-06
(`styling.styleSamples` in
[tests/fixtures/discovery.styling.json](tests/fixtures/discovery.styling.json),
a live discover run on a stock team site): seven samples written into text
controls came back from SharePoint with no change other than the `:` to
`&#58;` rewrite it applies to every text control's HTML.

| sample | HTML the part carries | stored |
| --- | --- | --- |
| `color` | `<p><span style="color:#a4262c;">colour by style</span></p>` | yes, `:` stored as `&#58;` |
| `font-size` | `<p><span style="font-size:24px;">size by style</span></p>` | yes, `:` stored as `&#58;` |
| `background` | `<p><span style="background-color:#fff100;">background by style</span></p>` | yes, `:` stored as `&#58;` |
| `styled-link` | `<p><a href="https://example.com/" style="color:#0078d4;text-decoration:underline;">styled link</a></p>` | yes, `:` stored as `&#58;` |
| `mark` | `<p>Text with a <mark>marked</mark> word.</p>` | yes, byte-identical |
| `block-align` | `<p style="text-align:center;">centred paragraph</p>` | yes, `:` stored as `&#58;` |
| `rte-classes` | `<p><span class="fontColorRed">colour by class</span>, <span class="fontSizeLarge">size by class</span>, <span class="highlightColorYellow">highlight by class</span></p>` | yes, byte-identical |

"Stored" is the bytes SharePoint returned for `CanvasContent1`. Whether the
text web part renders each style is a browser question the probe does not
answer (`rendering` in `styling.unmeasured`). The markdown subset cannot
express any of this; write such a part as HTML. `tests/test_styling_evidence.py`
keeps this table equal to the fixture's sample list.

### Emphasis

A component part may carry `emphasis`, the per-control block SharePoint uses
for a section's background swatch:

```yaml
- component: NewsWebPart
  emphasis: 2               # shorthand for {zoneEmphasis: 2}
```

`zoneEmphasis` must be an integer from 1 to 4. Measured 2026-09-06
(`styling.sectionSamples` in the fixture above): a web-part control sent with
`{zoneEmphasis: 2}` and one sent with `{zoneEmphasis: 3, formworkProbe: "unknown key"}`
were stored byte-for-byte through the same item MERGE the apply paste-in
uses, and read back intact. 1 and 4 are the editor's other two swatches and
are accepted on that basis alone. Nothing else is: an unknown key inside the
block refuses (the probe shows unknown keys echo back, which proves survival,
not meaning), any other value refuses, and `emphasis` on a text part refuses
because every text control the probe read back carried `{}`.

What the measurement does not say is that the swatch shows on a page created
by apply. The mechanism probe (`styling.sectionEmphasisMechanism`, 2026-09-06)
found that section emphasis takes effect once the section is established
through the page model's `/_api/sitepages/pages(<id>)/SavePage`, whose body is
a JSON array of controls carrying `zoneId` GUIDs, not the HTML canvas; the
probe page, which was only ever item-merged, is recorded there as "emphasis
dropped", while on a SavePage-established page a newly merged control with
`zoneEmphasis` 3 persisted. The apply paste-in does not call SavePage, so a
section-level `emphasis:` key refuses and names that limitation. Put the key
on the parts, and expect the stored bytes rather than the colour until that
path is measured.

### Templated specs

A spec file is rendered as a Jinja2 template *before* the YAML parser sees
it, so one page per site (or per environment) can come from one spec.
Rendering is opt-in: it happens only when the command carries `--vars` or
`--set`, or the spec itself carries a top-level `vars:` key. With no flags
the spec's bytes reach the parser unchanged, so a spec holding literal
`{{ ... }}` text keeps compiling as data.

```yaml
vars: vars/finance.yaml      # this page's own vars file, relative to the spec
page: Finance {{ env }}
sections:
  - parts:
      - component: NewsWebPart
      - text: Managed by {{ team }}
```

```
formwork compile-pages pages/ formwork-discovery.json --out-dir build/ \
    --vars shared.yaml --set env=Training
```

- `--vars FILE` is a YAML mapping of template variables, read with
  `safe_load` only — a vars file is data, never code.
- `--set NAME=VALUE` names one variable and overrides the vars file; repeat
  it, and later pairs win. `compile`, `compile-pages` and `preview` all take
  both flags.
- A page's own `vars:` key, at column 0 and at most one per spec, names a
  vars file relative to the spec file; it outranks the shared `--vars`.
- Precedence, highest first: `--set` > the page's `vars:` file > the shared
  `--vars`. A page vars file naming a key an explicit `--set` also names is
  refused rather than silently losing the override.
- Missing variables fail loudly. `StrictUndefined` means a name the template
  uses but nobody supplies is a compile error naming the variable and the
  template line, never an empty string baked into a page.
- Values are substituted as text, not escaped: `&`, `<`, `>`, `"` and `'`
  reach the spec verbatim, so a URL with a query string or a title with an
  apostrophe is fine. `--set` refuses a value containing a newline (multi-line
  values belong in the vars file), and every `--set` value is a string.
- Refusals name the file, the position and the variable; a vars file's values
  are never echoed into a message or into `formwork-pages.json`.

When a compile used the template layer its provenance stamp records the vars
file name and the SHA-256 of its bytes, a page's `ownVarsFile` and its
SHA-256, and the sorted `--set` key names (`setKeys`) — never the values — so
two payloads built from the same spec with different `--set` values are not
stamp-identical.

### What compile refuses

Every refusal names the part or section and the reason, and each reason
cites its measurement. Beyond the unknown-component, text and emphasis
refusals above, the spec may not carry `theme` (a web-level setting, not a
page field) or a section `background` or `spacing`: the canvas shape for
those is unmeasured, so they are refused rather than guessed at. A page-level
`navigation` key is refused as unmeasured: adding a page to the site
navigation is a navigation-node write, not a page save, and no `FINDINGS.md`
row `page.navigation.*` records one; the refusal names the discover lane that
would measure it. Nothing in a spec is silently dropped.

## Multi-page

A site is several pages declared together. `formwork compile-pages` takes a
directory (or a glob) of specs and one discovery document, compiles every
`*.yaml` against that one document, and writes one payload per spec plus a
manifest, `formwork-pages.json`, that carries the run's provenance header.

```yaml
# pages/home.yaml
page: Team home
sections:
  - type: two-thirds
    parts:
      - component: NewsWebPart
      - text: |
          ## Welcome

          See the [news](/sites/T/SitePages/Team-news.aspx).
        column: 2
```

```yaml
# pages/news.yaml
page: Team news
sections:
  - type: one
    parts:
      - component: NewsWebPart
        properties: {layoutId: "List"}
```

```
formwork compile-pages pages/ formwork-discovery.json --out-dir build/
```

```text
compiled 2 of 2 pages against formwork-discovery.json (web 7d1e9b5c-3a2f-4c8e-9b0a-2f6d4e8c1a35, sha256 4f0c9a3e7b21): manifest build/formwork-pages.json
  ok    home.yaml -> home.payload.json (Team home, 2 parts)
  ok    news.yaml -> news.payload.json (Team news, 1 part)
```

Each page compiles alone against the same catalogue: one bad spec fails with
its own reason, the rest still build, the command exits 1 and the manifest
records every result. The header, `compiledWith`, names the formwork version,
the SHA-256 of the discovery bytes, the web id and URL and the discovery's
own timestamp once for the run; each page entry carries the spec, the title,
the payload name, the part count and any staleness warnings from
`FINDINGS.md` (the same ones `compile` prints, per page on stderr). Each
payload also carries that header plus its own spec name and the run's compile
time as `provenance`: the stamp the apply script checks (see step 5 of the
authoring workflow).

What multi-page deliberately does not do:

- It writes one payload per spec, not one combined artefact. `formwork gen
  apply` takes one payload and creates one page, so each payload is applied
  in turn; two specs with the same stem refuse before anything is written.
- There is no link resolution. A text part may link to another page of the
  set (the href above), and the href is emitted as written. Which file name
  a created page is given is a page-state question the discover lane
  measures (`pageState`, under "Measured SharePoint behaviour"); until a
  registry row records it, rewriting a link would be a guess.
- There is no transaction and no cross-page ordering. Pages compile in name
  order and are applied one paste-in at a time; nothing sequences them, and
  a page that fails to apply leaves the others as they are.
- `navigation` is refused at parse, per page, as in "What compile refuses":
  the write is unmeasured.

## Copying a page

The second workflow moves an existing page between sites.

1. **Extract** — `formwork gen extract` prints a paste-in. Run it from the
   console on the source page. It fetches the page item and the web and site
   identity and downloads `formwork-bundle.json`: page fields, the raw canvas
   markup (`CanvasContent1`) and source identity.

2. **Inspect** — `formwork inspect formwork-bundle.json` lists every
   site-bound value in the page's canvas, web part by web part: `baseUrl`
   links, `siteId`/`webId` properties, list ids and urls, searchable plain
   texts, and, detected but never rewritten, other `link` entries and
   `image` sources. Each is addressed by the web part's `instanceId`. The
   bundle carries no separate web-part list; the canvas is the source.

3. **Process** — rewrite what your mapping resolves and report the rest:

   ```
   formwork process formwork-bundle.json \
     --mapping mapping.json --page-name "Team home" --out payload.json
   ```

   Unresolved values are never guessed. They are left exactly as extracted
   and reported, so a partial mapping degrades to "as extracted", not to a
   broken page.

4. **Apply** — `formwork gen apply payload.json --name "Team home"`, as in
   the authoring workflow. A process payload's stamp names the formwork
   version and the bundle but no discovery web (a copy is bound by its
   mapping), so the apply script runs its version check and prints that the
   site check does not apply.

Mapping file shape:

```json
{
  "baseUrl": "https://tenant.sharepoint.com/sites/target",
  "siteId": "00000000-0000-0000-0000-000000000000",
  "webId": "00000000-0000-0000-0000-000000000000",
  "lists": {
    "Document library": {
      "id": "00000000-0000-0000-0000-000000000000",
      "url": "/sites/target/Shared Documents",
      "webRelativeUrl": "Shared Documents",
      "viewId": "00000000-0000-0000-0000-000000000000"
    }
  },
  "textOverrides": {"Documents": "Team documents"}
}
```

`lists` is keyed by source web part title. `textOverrides` is keyed by the
exact source text. Everything you omit stays as extracted and is reported as
unresolved. Any console session on the target site can read
`/_api/web?$select=Id,Title,Url` and `/_api/site?$select=Id,Url` for the ids.

Two kinds are report-only: `link` (a web part's `links` entries other than
`baseUrl`, such as a Quick links item's `items[n].sourceItem.url`) and
`image` (`imageSources`). Inspect and process list them; nothing rewrites
them, because no mapping key for them has been measured: such a value may
be external, page-relative or list-bound, and what a target site wants there
is not known. They stay as extracted.

Process re-serialises only the web parts whose values actually changed; a
mapping that restates an extracted value leaves that web part's bytes alone.

Copied: page title, description, layout type, promoted state, section
structure, column widths, web part choices and properties — everything in the
canvas. Not copied: the content behind the web parts (news posts, list items,
documents; a News web part on the target shows the target's news, and a
Document library web part needs its `lists` mapping to point at a library
that exists there), page permissions, analytics, comments, version history.
Images referenced as `imageSources` stay pointed at the source site; they are
report-only (above), with no mapping key yet.

## The canvas contract

A modern page's layout lives in `CanvasContent1` as HTML-encoded canvas
markup. Each control is a `div` whose `data-sp-controldata` and
`data-sp-webpartdata` attributes carry entity-escaped JSON; a text control
carries its HTML in a `data-sp-rte` child instead of web-part data. Formwork
parses this markup and addresses each web part by its `instanceId`, the
per-control GUID (the web part's `id` is the component type and repeats when
a page places the same part twice). Untouched controls stay byte-exact; a
control is re-escaped only when a value on it actually changed, in
SharePoint's own escaping style (`&#123;`, `&quot;`, `&#58;`), which is not
what generic HTML escapers produce. That holds on both paths: process
rewrites the extracted canvas in place, control by control, and compile
builds its controls from the same model. Text HTML is emitted with `:` as
`&#58;`, the stored spelling. So what process or compile emits is what
apply's read-back compares against.

## Measured SharePoint behaviour

Every claim formwork makes about SharePoint was measured on the shauntestazure
sandbox; nothing here is inferred from documentation. Dates are measurement
dates, and the fixtures named are the evidence.

**2026-09-05, a live-captured team-site home page** (`tests/fixtures/collabhome.*`)

- The canvas is entity-escaped JSON inside HTML attributes, in the style
  above. The parser's round-trip of that page is byte-exact, including a
  re-render after every control is marked dirty.

**2026-09-06, transport and page creation** (the v0.2.0 discover and apply runs)

- An unprefixed `/_api/...` from a page under `/sites/<name>/` resolves to the
  tenant root web, so every paste-in derives the site prefix from
  `location.pathname` and refuses to run off a `/SitePages/` page.
- `contextinfo` is POST-only; GET is refused with 405.
- Site Pages is a document library: a list-item POST into it is refused and
  `Files/add` of an `.aspx` is 403. Pages are created through
  `/_api/sitepages/pages` and then written with an item MERGE under the real
  etag.
- MERGE stores `CanvasContent1` as sent for web-part controls: discover placed
  73 components and read 73 back byte-exact.

**Transport facts ported from dbml-sharepoint** (partials read 2026-09-06; the
error-body finding is a live finding of 2026-07-24)

- A throttled browser session is not answered with 429: SharePoint redirects
  it to `/_layouts/15/throttle.htm`, which arrives as 406 because the calls
  ask for JSON. The paste-ins match the final URL, hold every request behind
  one gate, and retry honouring `Retry-After`.
- The server's reason lives at `error.message.value` in the error body; every
  non-OK response is reported with it next to the operation and status.
- The `contextinfo` response is parsed step by step; the blind
  `.d.GetContextWebInformation.FormDigestValue` chain turned a server refusal
  into a TypeError.
- Apostrophes in OData string literals are doubled, and URI-encoded when used
  in a path segment.

**2026-09-06, text and styling** (`tests/fixtures/discovery.styling.json`,
`tests/fixtures/savepage-section-emphasis.json`)

- Text controls (`controlType` 4, `editorType` CKEditor) sent through the
  item MERGE are stored byte-for-byte except that `:` in the inner HTML is
  rewritten as `&#58;`. Nine of nine samples: the two probe controls and the
  seven styled samples in the table above. All nine carried `emphasis: {}`
  both ways.
- Five one-control sections were stored byte-identical: `zoneEmphasis` 2,
  `zoneEmphasis` 3 with an unknown key echoed back, collapsible
  `zoneGroupMetadata`, full-width `sectionFactor` 0, vertical `layoutIndex` 2.
  Stored is not rendered.
- The page model refuses the HTML canvas: `SavePageAsDraft` with
  `CanvasContent1` set to the markup answered HTTP 500, "Unexpected character
  encountered while parsing value: <". The page model's `SavePage` takes a
  JSON array of controls whose positions carry `zoneId` GUIDs; the editor's
  own body for an emphasised page is the second fixture.
- Section emphasis takes effect once a section is established through
  SavePage; the item-merged probe page is recorded as "emphasis dropped", the
  editor-authored page keeps `zoneEmphasis` 3 on every control, and a control
  merged into a SavePage-established section persisted `zoneEmphasis` 3.
- Unmeasured, and therefore refused or undocumented rather than guessed:
  `theme` (a web-level setting; no page save can set it),
  `section-background` (canvas shape unknown), `section-spacing` (no known
  key), `rendering` (the probe reads persisted bytes only), the rules for
  generating `zoneId` GUIDs, vertical and collapsible sections through the
  SavePage path, and section background images.

**2026-09-07, page state and identity** (`_probe_pagestate.js.j2`, the lane
`formwork gen discover` and `formwork gen findprobe` share)

- Measured by the lane, not yet recorded: what SharePoint does with an
  explicit `FileName` at create, and with one carrying spaces and capitals;
  whether `Description` and `BannerImageUrl` survive the item MERGE (the
  banner as an `SP.FieldUrlValue`) and the page model's `SavePageAsDraft`;
  whether the `Article` layout and `PromotedState` 1 read back as requested
  at create and after the MERGE apply makes; a fresh draft's
  `OData__UIVersionString`, `CheckoutUserId` and moderation status, and the
  same after `checkoutpage` and `publish`; and `HasUniqueRoleAssignments` on
  every page created. Each is a sample under the document's `pageState` key,
  requested and persisted by page id, on a scratch page of the lane's own
  that is recycled before the download.
- The `FINDINGS.md` rows for these claims follow the first live run: a row
  cites a fixture, and none exists yet. Until then `compile` neither warns
  nor refuses on them, and `compile-pages` does no link resolution.
- Unmeasured by the lane, and named as such in the document: `navigation`
  (a navigation-node write, not a page save; the DSL refuses the key),
  `permission-break` (inheritance is read on every page, never broken),
  `banner-json` (only the two banner writes above are attempted) and
  `rendering`.

## The findings registry

[FINDINGS.md](FINDINGS.md) is the table of those claims, one row per
measured claim: a check-id (`page.<scope>.<question>`), the claim, the
measured date, the compact result, an evidence pointer into a fixture
(`tests/fixtures/<file>#<dotted.key>`) and the re-probe command that
re-derives it. It is data: `src/formwork/findings.py` parses it on load and
refuses a malformed row, and `tests/test_findings.py` checks that every
evidence pointer resolves, every date matches the run that produced the
fixture, and the table is byte-identical to its own canonical rendering.
The hand-measured section-emphasis mechanism is an ordinary row there; the
pin survives because the re-probe re-derives it.

Two commands read it.

- `formwork compile` warns (never refuses) when the newest row a spec relies
  on is older than `--findings-max-age` (default 90 days). A part relies on
  the component-merge row, its own `page.properties.<alias>` row when it
  sets `properties` (or the newest properties row when there is none for
  that alias), the list-binding row when it has `bind`, and the
  control-merge row when it has `emphasis`; a text part relies on the colon
  rewrite and, when its HTML carries a `style`, a `class` or a `<mark>`, on
  the styled-text row; a section relies on the row for its factors. Each
  warning names the check-id, the parts or sections that rely on it, its age
  and the re-probe command; a relied-on claim with no row at all is warned
  about the same way. Evidence ages, it does not vanish. Without a
  registry in the working directory compile is silent and unchanged; an
  explicit `--findings` that does not exist is an error.
- `formwork gen findprobe` prints the re-probe paste-in: the discover
  probe's own measurement legs (shared as template partials, so the two
  scripts carry the same bytes) plus a SavePage leg that establishes two
  emphasised sections on a second scratch page and item-merges a third
  control into one of them. It recycles everything it created, prints a
  verdict per row ("same" or "DIFFERS" against the result column, the
  discover-lane rows listed as not re-run here) and downloads
  `formwork-findprobe.json` with the evidence under discover's keys. A
  DIFFERS row is the cue to re-measure, fold the capture into the fixtures
  and add a dated row; the old row stays.

## Install

Releases are published as wheels on this repository's GitHub Releases page
(there is no PyPI publication — do not `pip install formwork` from PyPI; the
name is not ours there). Install a release wheel directly:

```
pipx install https://github.com/firmfooting/formwork/releases/latest/download/formwork-0.6.0-py3-none-any.whl
```

(pinning the URL to a known release is safer than `latest`; bump the version
as releases land.) Or with pip, into whatever environment you manage:

```
pip install <the same wheel URL>
```

Both give you the `formwork` command: `compile`, `compile-pages`, `preview`,
`process`, `inspect`, `components`, and the `gen` paste-in generators. One
caveat: `formwork gen findprobe` reads the findings registry from
`FINDINGS.md` in the working directory, so it only runs from a formwork
repository checkout — everything else runs anywhere.

## Development

```
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
```

`uv sync --locked` is what CI runs; relock with `uv lock` whenever you touch
`pyproject.toml`, or CI's `--locked` check fails the PR. (A plain venv +
`pip install -e '.[dev]'` also works locally, but uv is what the gates run.)

The paste-ins and the preview are Jinja templates under
`src/formwork/templates/` (`jinja2` is the one runtime dependency besides
PyYAML). The four scripts share one prelude partial, `_prelude.js.j2`, which
carries the measured transport facts with their citations and is the only
place the display layer names the Site Pages list; discover and findprobe
also share the probe setup, the measurement legs and the page-state lane
(`_probe_setup.js.j2`, `_probe_legs.js.j2`, `_probe_pagestate.js.j2`); each
script's template holds its own phase logic. `compile-pages` is
`src/formwork/multipage.py`, a loop over `dsl.compile_page` with the manifest
around it. Generated paste-ins are gated with `node --check` and compared byte for byte
with the goldens under `tests/fixtures/expected/` (extract, discover, apply,
apply with an awkward payload, and findprobe with the repository's
`FINDINGS.md`); after a deliberate template change, regenerate them with
`.venv/bin/python tests/test_generator.py` and review the diff like code.

The fixtures under `tests/fixtures/` are live captures (data already
anonymous and sandbox-bound) and are the ground truth for the canvas parser,
the text-part gate and the styling claims above; `tests/test_styling_evidence.py`
reads them next to this README. The version is written in `pyproject.toml`
and `src/formwork/__init__.py` and pinned equal, with the changelog's first
entry, by `tests/test_version.py`.

## Licence

MIT.
