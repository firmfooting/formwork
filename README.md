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

2. **Declare** the page in `page.yaml`. Sections, columns, parts, text, and
   the emphasis of a part; see [Writing the spec](#writing-the-spec).

3. **Compile** it: `formwork compile page.yaml formwork-discovery.json`
   resolves every component against the live catalogue by alias or title,
   emits the section geometry (`sectionFactor` 8/4 for two-thirds, 12 for
   one, 4/4/4 for three), applies property overrides, compiles text parts to
   text controls and writes `formwork-payload.json`. It prints one line per
   placed part. An unknown or hidden component refuses to compile: nothing is
   placed that the site did not declare placeable.

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

### What compile refuses

Every refusal names the part or section and the reason, and each reason
cites its measurement. Beyond the unknown-component, text and emphasis
refusals above, the spec may not carry `theme` (a web-level setting, not a
page field) or a section `background` or `spacing`: the canvas shape for
those is unmeasured, so they are refused rather than guessed at. Nothing in a
spec is silently dropped.

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
   the authoring workflow.

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

## Development

```
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy src
```

The paste-ins and the preview are Jinja templates under
`src/formwork/templates/` (`jinja2` is the one runtime dependency besides
PyYAML). The three scripts share one prelude partial, `_prelude.js.j2`, which
carries the measured transport facts with their citations and is the only
place the display layer names the Site Pages list; each script's template
holds its own phase logic. Generated paste-ins are gated with `node --check`
and compared byte for byte with the goldens under `tests/fixtures/expected/`
(extract, discover, apply, and apply with an awkward payload); after a
deliberate template change, regenerate them with
`.venv/bin/python tests/test_generator.py` and review the diff like code.

The fixtures under `tests/fixtures/` are live captures (data already
anonymous and sandbox-bound) and are the ground truth for the canvas parser,
the text-part gate and the styling claims above; `tests/test_styling_evidence.py`
reads them next to this README. The version is written in `pyproject.toml`
and `src/formwork/__init__.py` and pinned equal, with the changelog's first
entry, by `tests/test_version.py`.

## Licence

MIT.
