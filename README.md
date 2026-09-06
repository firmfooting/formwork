# formwork

SharePoint page copier: extract a modern page with a console paste-in, process
the bundle, and pour it into another site.

The name is the trade: formwork is the mould you build once and reuse for many
identical pours. Build a page once — news, quick links, document library,
whatever your layout is — then reuse the mould across teams, sites, or tenants.

## How it works

Three steps, two paste-ins, one small CLI.

```
source page                your laptop                 target site
┌─────────────┐   1. gen extract   ┌──────────┐   3. gen apply   ┌─────────────┐
│ DevTools    │ ─────────────────> │ formwork │ ───────────────> │ DevTools    │
│ console     │   paste-in saves   │ process  │   paste-in saves │ console     │
│             │   formwork-        │          │   the new page   │             │
│             │   bundle.json      │          │                  │             │
└─────────────┘                    └──────────┘                  └─────────────┘
```

1. **Extract** — `formwork gen extract` prints a self-contained JavaScript
   paste-in. Run it from the browser console on the source page. It fetches
   the page item and web/site identity over same-origin REST and downloads
   `formwork-bundle.json`: page fields, the raw canvas markup
   (`CanvasContent1`), and source identity. No admin consent, no app
   registration — your existing session is the credential, and it can only
   read what you can already see.

2. **Process** — the CLI inventories every site-bound value in the bundle
   (`baseUrl` links, `siteId`/`webId` properties, list ids and urls,
   searchable plain texts), rewrites what your target mapping resolves, and
   flags what it could not:

   ```
   formwork inspect formwork-bundle.json
   formwork process formwork-bundle.json \
     --mapping mapping.json --page-name "Team home" --out payload.json
   ```

   Unresolved values are never guessed. They are left exactly as extracted and
   reported, so a partial mapping degrades to "as extracted", not to a broken
   page.

3. **Apply** — `formwork gen apply payload.json --name "Team home"` prints the
   second paste-in with the processed payload embedded. Run it from the
   console on any page of the target site: it creates the page (through the
   `sitepages` API — Site Pages is a document library, so files/add of an
   `.aspx` is refused), writes the canvas with MERGE + etag concurrency
   control, then verifies by reading back what SharePoint actually stored and
   comparing byte-for-byte.

## Building pages from scratch: the discovery DSL

Copying is half the tool. The other half is a small declarative DSL for
creating pages from nothing.

1. **Discover** — `formwork gen discover` prints a paste-in that runs against
   any site: it enumerates every placeable component via
   `GetClientSideWebParts` (73 on a stock team site, 285 including hidden and
   extension components), creates a scratch page, places one control per
   component across one/two/three-column sections plus two text controls
   with known HTML in a fourth section, saves, reads back what SharePoint
   persisted (the text controls verbatim, under `textControls`), recycles
   the scratch page, and downloads `formwork-discovery.json` as the site's
   component catalogue.

   The same run measures styling, under an additive `styling` key: seven
   text controls carrying styled HTML (colour, font size, background, a
   styled link, `<mark>`, block alignment, SharePoint's own RTE classes),
   five one-control sections each carrying one section-level variant
   (`zoneEmphasis` 2 and 3 with an unknown key, collapsible
   `zoneGroupMetadata`, full-width `sectionFactor` 0, vertical
   `layoutIndex` 2), and a second save through the page model
   (`SavePageAsDraft`) with a marker control, so the document says whether
   that path applied the body or ignored it. Each sample is recorded as
   requested and as persisted; the `styling.unmeasured` list names what the
   run cannot settle (theme, section background, section spacing,
   rendering) and why.

2. **Declare** — write the page you want:

   ```yaml
   page: Team demo home
   sections:
     - type: two-thirds
       parts:
         - component: NewsWebPart
         - text: |
             ## Welcome
             The **team** page. See the [handbook](/sites/T/SitePages/Handbook.aspx).
           column: 2
     - type: one
       parts:
         - component: EventsWebPart
         - text: "<p>Raw <em>HTML</em> is fine too.</p>"
   ```

   A part is either a `component` (by alias or title, with optional
   `properties` and `displayTitle`) or a `text` block. Text is HTML when it
   starts with `<` or carries `format: html`, otherwise a small markdown
   subset: `#` to `####` headings, paragraphs, `-`/`*` and `1.` lists,
   `**bold**`, `*italic*`/`_italic_`, and `[text](url)` links (http, https,
   mailto or relative). Anything else — blockquotes, tables, code, images,
   rules, nested lists, raw tags — is refused with the line number rather
   than guessed at. The HTML must not carry `data-sp-` attributes.

3. **Preview** — `formwork preview page.yaml --out preview.html` renders the
   spec as a standalone HTML page: sections in order, columns at their
   factors on a 12-column grid, text parts inline, other parts as titled
   placeholder cards. Pass `--discovery formwork-discovery.json` to show the
   catalogue's titles and descriptions; without it, titles are the aliases.
   No SharePoint calls, no network.

4. **Compile** — `formwork compile page.yaml formwork-discovery.json` resolves
   every component against the live catalogue (by alias or title), emits
   correct section geometry (`sectionFactor` 8/4 for two-thirds, 12 for one,
   4/4/4 for three), applies property overrides, compiles text blocks to
   text controls (`controlType` 4, not web parts), and produces an apply
   payload. An unknown or hidden component refuses to compile — nothing is
   placed that the site did not declare placeable.

   The text-control shape the compiler emits is the one the discover script
   sends. Measured live (2026-09-06, a stock team site): SharePoint stores
   that shape byte-for-byte except that `:` inside the control's HTML is
   rewritten as `&#58;`. Compiling text parts therefore requires a discovery
   document whose `textControls` samples persisted with only that
   difference; a document without the measurement, or one whose samples
   differ in any other way, refuses to compile text parts and says why.

## The canvas contract

A modern page's layout lives in `CanvasContent1` as HTML-encoded canvas
markup. Each control is a `div` whose `data-sp-controldata` /
`data-sp-webpartdata` attributes carry entity-escaped JSON. Formwork parses
this markup, keeps untouched controls byte-exact, and re-escapes only the
controls it changed — matching SharePoint's own escaping style (`&#123;`,
`&quot;`, `&#58;`), which is not what generic HTML escapers produce. The
round-trip is tested against a live-captured page.

## What copies, what does not

Copied: page title, description, layout type, promoted state, section
structure, column widths, web part choices and properties — everything in the
canvas.

Not copied (by design in v0.1):

- Site pages behind the page: news posts, list items, documents the web parts
  display. A News web part copied to another site shows the target site's
  news; a Document library web part needs its `lists` mapping to point at a
  library that exists on the target.
- Page permissions, page-level analytics, comments, version history.
- Images stored as `imageSources` are left as extracted when unresolved —
  they will keep pointing at the source site until you map them.

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
unresolved.

## Getting the ids for the mapping

Run `formwork gen extract`-style discovery on the TARGET site — any console
session there can read `/_api/web?$select=Id,Title,Url` and
`/_api/site?$select=Id,Url`. `formwork inspect` on the bundle tells you which
list titles you need ids for.

## Development

```
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy src
```

The paste-ins and the preview are Jinja templates under
`src/formwork/templates/` (`jinja2` is the one runtime dependency besides
PyYAML). The three scripts share one prelude partial, `_prelude.js.j2`,
which carries the measured transport facts and is the only place the display
layer names the Site Pages list; each script's template holds its own phase
logic. Generated paste-ins are additionally gated with `node --check` and
compared byte for byte with the goldens under `tests/fixtures/expected/`;
after a deliberate template change, regenerate them with
`.venv/bin/python tests/test_generator.py` and review the diff like code. The
fixtures under `tests/fixtures/` were captured from a live modern page (with
its data already anonymous and sandbox-bound) and are the ground truth for the
canvas parser.

## Licence

MIT.
