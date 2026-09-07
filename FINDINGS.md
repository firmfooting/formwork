# Findings

The measured SharePoint claims formwork relies on, one row each. This file
is data, not decoration: `src/formwork/findings.py` parses the table on load
and refuses a row that does not follow the grammar, so it cannot drift into
prose.

- **check-id** is `<surface>.<scope>.<question>`: lowercase hyphenated
  segments, the surface `page` today.
- **claim** is the sentence the code relies on.
- **measured** is the UTC date of the live run that produced the evidence (the script stamps `toISOString`, so an AEST morning run is dated the previous day).
- **result** is the compact outcome the re-probe reproduces word for word.
  `formwork gen findprobe` prints "same" or "DIFFERS" per row by comparing
  its verdict string to this cell.
- **evidence** points into a live capture as
  `tests/fixtures/<file>#<dotted.key>`.
- **re-probe** is the generator command that re-derives the claim. Only two
  mechanisms exist: `formwork gen discover` (the catalogue run re-derives
  what its own spread measures) and `formwork gen findprobe` (re-runs the
  measurement legs, plus the SavePage section-emphasis leg, and diffs each
  result against this table).

`formwork compile` warns when the newest row a spec relies on is older than
`--findings-max-age` (default 90 days), naming the check-id and its re-probe
command. It never refuses: evidence ages, it does not vanish.

A re-measured claim is a new row with the same check-id and the new date;
the old row stays. The newest row is the one compile judges age by. The
table is the last thing in this file and is byte-identical to what
`findings.render_findings` writes back (pinned by `tests/test_findings.py`).

## Registry

| check-id | claim | measured | result | evidence | re-probe |
| --- | --- | --- | --- | --- | --- |
| page.components.merge-byte-exact | An item MERGE of CanvasContent1 stores every web-part control as sent: the stored control count equals the placed count and each block reads back byte for byte | 2026-09-06 | stored count equals placed count | tests/fixtures/discovery.m5.json#placements | formwork gen discover |
| page.layout.default-factors | One-, two- and three-column sections (sectionFactor 12; 6 and 6; 4, 4 and 4) read back with the factors as written | 2026-09-06 | 12, 6/6, 4/4/4 read back | tests/fixtures/discovery.m5.json#storedCanvas | formwork gen discover |
| page.text.colon-rewrite | A text control (controlType 4, the HTML as the inner content of a data-sp-rte child) is stored byte-identically except that ':' in the inner HTML is rewritten as '&#58;' | 2026-09-06 | 2/2 byte-exact after the ':' fold | tests/fixtures/discovery.styling.json#textControls | formwork gen findprobe |
| page.text.styled-html | Inline style attributes, a styled link, a mark element and the editor's own colour, size and highlight classes survive in text HTML with only the ':' rewrite | 2026-09-06 | 7/7 byte-exact after the ':' fold; byte-identical: mark, rte-classes | tests/fixtures/discovery.styling.json#styling.styleSamples | formwork gen findprobe |
| page.emphasis.control-merge | emphasis.zoneEmphasis on a web-part control survives the item MERGE, an unknown key beside it included | 2026-09-06 | 2/2 byte-exact; zoneEmphasis 2, 3 read back | tests/fixtures/discovery.styling.json#styling.sectionSamples | formwork gen findprobe |
| page.section.variants-merge | zoneGroupMetadata (collapsible), sectionFactor 0 (full width) and layoutIndex 2 with isLayoutReflowOnTop (vertical) are stored as written by the item MERGE | 2026-09-06 | 3/3 byte-exact | tests/fixtures/discovery.styling.json#styling.sectionSamples | formwork gen findprobe |
| page.page-model.draft-refuses-html | SavePageAsDraft refuses an HTML CanvasContent1: the page model parses the field as JSON, so the item MERGE is the write path for an HTML canvas | 2026-09-06 | refused 500: Unexpected character encountered while parsing value: < | tests/fixtures/discovery.styling.json#styling.pageModelSave | formwork gen findprobe |
| page.emphasis.section-savepage | Section emphasis is established only by SavePage with a JSON-array CanvasContent1 whose controls carry position.zoneId; a control item-merged into that zone afterwards reads back with the zone's zoneEmphasis | 2026-09-06 | SavePage 200; zoneEmphasis survived 2, 3; merged control 3 | tests/fixtures/discovery.styling.json#styling.sectionEmphasisMechanism | formwork gen findprobe |
| page.properties.news-web-part | NewsWebPart placed twice, the manifest default and then with showChrome changed, stores both blocks byte for byte and the changed value reads back equal | 2026-09-06 | 2/2 byte-exact; showChrome true to false round-tripped | tests/fixtures/discovery.m5.json#webpartProperties | formwork gen findprobe |
| page.properties.quick-links-web-part | QuickLinksWebPart placed twice, the manifest default and then with layoutId changed, stores both blocks byte for byte and the changed value reads back equal | 2026-09-06 | 2/2 byte-exact; layoutId "CompactCard" to "List" round-tripped | tests/fixtures/discovery.m5.json#webpartProperties | formwork gen findprobe |
| page.properties.image-web-part | ImageWebPart placed twice, the manifest default and then with captionText changed to a value carrying a ':', stores both blocks byte for byte and the changed value reads back equal | 2026-09-06 | 2/2 byte-exact; captionText "" to "Formwork caption probe: image" round-tripped | tests/fixtures/discovery.m5.json#webpartProperties | formwork gen findprobe |
| page.properties.events-web-part | EventsWebPart placed twice, the manifest default and then with layout changed, stores both blocks byte for byte and the changed value reads back equal | 2026-09-06 | 2/2 byte-exact; layout "Filmstrip" to "Compact" round-tripped | tests/fixtures/discovery.m5.json#webpartProperties | formwork gen findprobe |
| page.properties.hero-web-part | HeroWebPart placed twice, the manifest default and then with heroLayoutThreshold changed, stores both blocks byte for byte and the changed value reads back equal | 2026-09-06 | 2/2 byte-exact; heroLayoutThreshold "640" to "320" round-tripped | tests/fixtures/discovery.m5.json#webpartProperties | formwork gen findprobe |
| page.properties.list-web-part | ListWebPart placed twice, the manifest default and then with isDocumentLibrary changed, stores both blocks byte for byte and the changed value reads back equal | 2026-09-06 | 2/2 byte-exact; isDocumentLibrary false to true round-tripped | tests/fixtures/discovery.m5.json#webpartProperties | formwork gen findprobe |
| page.layout.factors-8-4 | An 8/4 section stores its column-1 control with sectionFactor 8 as written | 2026-09-06 | 1/1 byte-exact | tests/fixtures/discovery.m5.json#layoutVariants | formwork gen findprobe |
| page.layout.factors-4-8 | 4/8 sections store their controls as written, a column-2 control written before its column-1 neighbour included: SharePoint keeps the written order rather than re-sorting by column | 2026-09-06 | 3/3 byte-exact; written order kept | tests/fixtures/discovery.m5.json#layoutVariants | formwork gen findprobe |
| page.bind.list-library-keys | The library and list entries of ListWebPart and a Quick links item, bound to a custom list and a document library through selectedListId, selectedListUrl, webRelativeListUrl, selectedViewId and serverProcessedContent, store byte for byte | 2026-09-06 | 6/6 byte-exact | tests/fixtures/discovery.m5.json#listBindings | formwork gen findprobe |
| page.page-state.filename-slug | On the Home layout apply creates with, a FileName sent at create through sitepages/pages is ignored and the server assigns the name itself (an eight-character slug); whether Article honours FileName is unmeasured | 2026-09-06 | explicit: ignored (stored d0i8msje.aspx); slug-needing: ignored (stored b1xk6f0f.aspx) | tests/fixtures/discovery.pagestate.json#pageState | formwork gen findprobe |
| page.page-state.description-banner | BannerImageUrl sent by item MERGE (SP.FieldUrlValue) is persisted on the page entity after the merge; Description sent by the same MERGE returns 204 and stays null on entity and item | 2026-09-06 | description null; banner persisted | tests/fixtures/discovery.pagestate.json#pageState | formwork gen findprobe |
| page.page-state.layout-article | A page created with PageLayoutType Article persists the layout type | 2026-09-06 | PageLayoutType Article | tests/fixtures/discovery.pagestate.json#pageState | formwork gen findprobe |
| page.page-state.promoted-state | PromotedState 1 sent at create (beside the Article layout) persists as 1; the same MERGE on a fresh Home-layout draft returns 204 and reads back 0 — the create-then-MERGE path apply used before 0.5.0 left the page at 0, and whether that is the write path or the Home layout is not separated by this lane (the confound named by review 2026-09-07 P1-3); apply now sends the field at create on the evidence of page.promoted-state.create-is-effective | 2026-09-06 | at create 1; after merge 0 (merge status 204) | tests/fixtures/discovery.pagestate.json#pageState | formwork gen findprobe |
| page.page-state.publish-flow | A fresh draft is version 0.1 checked out to its creator; checkoutpage on the already-checked-out page is a 200 with no field change; publish returns 200 and moves the version to 1.0 with the checkout cleared | 2026-09-06 | fresh 0.1 checked out; checkoutpage 200; publish 200 -> 1.0, checked out false | tests/fixtures/discovery.pagestate.json#pageState | formwork gen findprobe |
| page.page-state.permission-inheritance | A page created by sitepages/pages does not break role inheritance: HasUniqueRoleAssignments reads false on the fresh item | 2026-09-06 | false | tests/fixtures/discovery.pagestate.json#pageState | formwork gen findprobe |
| page.promoted-state.create-is-effective | PromotedState 1 sent inside the sitepages/pages create body beside the Article layout persists as 1 on the page entity; apply sends PromotedState in its create body on this evidence, and the Home layout apply creates with PromotedState at create is not yet a sample of its own | 2026-09-06 | PromotedState 1 at create beside Article | tests/fixtures/discovery.pagestate.json#pageState.samples.3 | formwork gen findprobe |
