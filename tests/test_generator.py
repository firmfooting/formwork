"""Tests for the paste-in script generators.

Golden files
------------
``tests/fixtures/expected/{extract,discover,apply,findprobe}.js`` hold the
emitted scripts byte for byte (apply with its default arguments, findprobe
with the repository's FINDINGS.md). Any generator change fails the golden
tests until the fixtures are deliberately regenerated::

    .venv/bin/python tests/test_generator.py

That runs the same generator calls the golden tests do, so the two cannot
drift. Review the resulting diff like code: it is the paste-in the operator
will run. Regeneration is deliberately a separate, explicit act rather than a
flag on the test run; the friction is the point.
"""

import functools
import json
import pathlib
import re
import subprocess

import pytest

from formwork.dsl import UNMEASURED_PAGE_KEYS
from formwork.findings import load_findings
from formwork.generator import (
    generate_apply_script,
    generate_discover_script,
    generate_extract_script,
    generate_findprobe_script,
)

EXPECTED_SCHEMA = "formwork.bundle/v1"

#: Committed golden files: the emitted scripts, byte for byte.
EXPECTED = pathlib.Path(__file__).parent / "fixtures" / "expected"

#: The registry the findprobe golden embeds: the repository's own.
FINDINGS = pathlib.Path(__file__).parent.parent / "FINDINGS.md"

#: A payload carrying every character the JSON embedding has to survive:
#: braces, double quotes, a backslash, an apostrophe, angle brackets, a
#: closing script tag and a non-ASCII letter. The default apply golden
#: embeds only "{}", so this second golden is the one that pins the
#: embedding (review P3-2 / P3-4, 2026-09-06).
APPLY_PAYLOAD_NAME = "Bob's <page>"
APPLY_PAYLOAD = json.dumps(
    {"title": APPLY_PAYLOAD_NAME, "canvas": '<div>{"k": 1} \\ </script> ü</div>'}
)

#: Every generated script, by the name of its golden file.
GENERATORS = {
    "extract": generate_extract_script,
    "discover": generate_discover_script,
    "apply": generate_apply_script,
    "apply-payload": functools.partial(generate_apply_script, APPLY_PAYLOAD_NAME, APPLY_PAYLOAD, 1),
    "findprobe": lambda: generate_findprobe_script(load_findings(FINDINGS)),
}


def write_golden(path: pathlib.Path, text: str) -> None:
    """Explicit newline: the default emits CRLF on Windows, so the file reads
    as modified locally while producing an empty diff."""
    path.write_text(text, encoding="utf-8", newline="\n")


#: One backslash, composed: the pins below must survive any display or
#: transport layer that rewrites escape sequences in source text.
BS = chr(92)


def node_available() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


def node_check(script: str, tmp_path: pathlib.Path) -> subprocess.CompletedProcess:
    path = tmp_path / "script.js"
    path.write_text(script, encoding="utf-8")
    return subprocess.run(["node", "--check", str(path)], capture_output=True, check=False)


@pytest.mark.skipif(not node_available(), reason="node is not installed")
class TestExtractScript:
    def test_script_is_syntactically_valid_javascript(self, tmp_path):
        result = node_check(generate_extract_script(), tmp_path)
        assert result.returncode == 0, result.stderr.decode()

    def test_script_fetches_page_by_relative_site_pages_path(self):
        script = generate_extract_script()
        assert 'API("web/lists/getbytitle' in script
        assert "SitePages" in script
        assert "https://" + "placeholder" not in script  # no hardcoded tenant
        # Site-prefixed calls: unprefixed /_api hits the tenant root (measured).
        # The single '"/_api' occurrence is the API helper definition itself.
        assert script.count('"/_api') == 1

    def test_script_builds_expected_bundle_shape(self):
        """The bundle the script assembles must match the wire contract."""
        script = generate_extract_script()
        assert EXPECTED_SCHEMA in script
        for key in ("source", "webUrl", "webPath", "pagePath", "page", "CanvasContent1"):
            assert key in script

    def test_script_uses_camouflage_free_download(self):
        """Download via Blob + anchor, no external libraries."""
        script = generate_extract_script()
        assert "URL.createObjectURL" in script
        assert "formwork-bundle" in script


@pytest.mark.skipif(not node_available(), reason="node is not installed")
class TestDiscoverScript:
    def test_script_is_syntactically_valid_javascript(self, tmp_path):
        result = node_check(generate_discover_script(), tmp_path)
        assert result.returncode == 0, result.stderr.decode()

    def test_script_enumerates_components_and_places_them(self):
        script = generate_discover_script()
        assert "GetClientSideWebParts" in script
        assert "sectionFactor" in script
        assert "recycle" in script
        assert "formwork-discovery.json" in script

    def test_script_cleans_up_the_scratch_page(self):
        script = generate_discover_script()
        # recycle happens before download: no residue if the download stalls
        assert script.index("recycle") < script.index("URL.createObjectURL")

    def test_script_places_two_known_text_controls(self):
        # A text block is not a web part: controlType 4, no webPartId, the
        # HTML as inner content of a data-sp-rte child (the shape PnP sends).
        # One builder for every text control on the page (the M1 samples,
        # the M3 style samples, the page-model marker): one literal.
        script = generate_discover_script()
        assert script.count("controlType: 4") == 1
        assert "editorType: \"CKEditor\"" in script
        assert "'<div data-sp-rte=\"\">' + html + '</div></div>'" in script
        # Two samples, with the constructs the compiler's converter emits:
        # a heading, bold, a link, a colour span, strong/em and a list.
        start = script.index("const TEXT_SAMPLES = [")
        samples = script[start : script.index("];", start)]
        for construct in ("<h2>", "<b>", '<a href="https://example.com/">', "color:#a4262c;",
                          "<strong>", "<em>", "<ul><li>"):
            assert construct in samples, construct
        # Their control data goes through the same attribute escaper as a
        # web part's, and the blocks are written before the scratch save.
        assert "esc(JSON.stringify(cd))" in script
        assert "textBlock(t.cd, t.html)" in script
        assert script.index("data-sp-rte") < script.index('failed("scratch save"')
        # The measured result is stated where the shape is sent (784d52b).
        assert "is rewritten as" in script and "'&#58;'" in script

    def test_script_reads_back_the_persisted_text_controls_verbatim(self):
        script = generate_discover_script()
        # Split on the same boundary canvas.py parses by; decode through
        # the browser's parser; keep the raw block, not a re-serialisation.
        assert "const CONTROL_OPEN = '<div data-sp-canvascontrol=\"\"';" in script
        assert 'new DOMParser().parseFromString(block, "text/html")' in script
        assert "cd.controlType === 4" in script
        assert "textPersisted.push({ id: cd.id, controlData: cd, canvas: block });" in script
        # Read back before recycling; carried under the additive key.
        assert script.index("textPersisted.push") < script.index('/recycle"')
        assert re.search(
            r"textControls: \{\n\s*requested: textRequested,\n\s*persisted: textPersisted,",
            script,
        )
        assert 'schema: "formwork.discovery/v1"' in script  # still v1: additive
        # The measurement is cited where the shape is assumed, by its row.
        assert "finding: page.text.styled-html (FINDINGS.md, 2026-09-06)" in script
        # The M1 persisted list is the M1 samples only: the M3 style samples
        # are text controls too and must not leak into the compile gate.
        assert "cd.controlType === 4 && textIds.has(cd.id)" in script

    def test_script_places_styled_text_samples_under_an_additive_key(self):
        """M3 (a): styled HTML, one text control per sample, requested and
        persisted paired by control id under styling.styleSamples."""
        script = generate_discover_script()
        start = script.index("const STYLE_SAMPLES = [")
        samples = script[start : script.index("];", start)]
        # The style attribute (colour, size, background, a styled link, a
        # block alignment), a <mark>, and the editor's own class idiom.
        for construct in (
            'style="color:#a4262c;"',
            'style="font-size:24px;"',
            'style="background-color:#fff100;"',
            '<a href="https://example.com/" style="color:#0078d4;text-decoration:underline;">',
            "<mark>marked</mark>",
            '<p style="text-align:center;">',
            'class="fontColorRed"',
            'class="fontSizeLarge"',
            'class="highlightColorYellow"',
        ):
            assert construct in samples, construct
        assert samples.count("label:") == 7
        # Own id range, own section, the shared text-control builder, and
        # the same requested/persisted pairing the M1 samples use.
        assert '"00000000-0000-0000-0002-"' in script
        assert "textBlock(s.cd, s.html)" in script
        assert "const stylePersisted = persistedFor(storedBlocks, styleRequested);" in script
        assert re.search(
            r"styleSamples: \{\n\s*requested: styleRequested,\n\s*persisted: stylePersisted,",
            script,
        )
        assert script.index("const stylePersisted") < script.index('/recycle"')
        # The measurement is cited where the samples are declared.
        assert script.index("finding: page.text.styled-html") < start

    def test_script_places_section_style_variants_one_per_section(self):
        """M3 (b, c): section-level styling rides on each control in the
        section; one web-part control per variant, each in its own section."""
        script = generate_discover_script()
        start = script.index("const SECTION_SAMPLES = [")
        samples = script[start : script.index("];", start)]
        for construct in (
            "zoneEmphasis: 2",  # PnP's Soft emphasis, the known shape
            'zoneEmphasis: 3, formworkProbe: "unknown key"',  # unknown-key survival
            "zoneGroupMetadata: {",  # collapsible section
            "sectionFactor: 0",  # full width
            "layoutIndex: 2, isLayoutReflowOnTop: false",  # vertical section
        ):
            assert construct in samples, construct
        assert samples.count("label:") == 5
        # Web-part controls (the brief's (b)), on the first placeable part,
        # each variant a section of its own, requested/persisted by id.
        assert "webPartId: placeable[0].Id" in script
        assert "emphasis: s.emphasis" in script
        assert '"00000000-0000-0000-0003-"' in script
        assert "const block = webPartBlock(s.cd);" in script
        assert re.search(
            r"sectionSamples: \{\n\s*requested: sectionRequested,\n\s*persisted: sectionPersisted,",
            script,
        )
        # The refusal that guards placeable[0] names the call that came back empty.
        assert "returned no placeable web part (ComponentType 1)" in script

    def test_script_measures_the_page_model_save_path_without_failing_the_run(self):
        """M3 second readback: the same canvas through SavePageAsDraft, with a
        marker control so the readback shows whether the body was applied.
        A refusal is recorded (status and server reason), never thrown."""
        script = generate_discover_script()
        assert 'API("sitepages/pages(" + scratchId + ")/SavePageAsDraft")' in script
        # After the MERGE readback, before the recycle.
        merge_readback = script.index('failed("scratch read back"')
        assert merge_readback < script.index("SavePageAsDraft") < script.index('/recycle"')
        # Non-fatal, with the server's reason surfaced through spError.
        assert "pageModelSave.reason = spError(" in script
        assert "} catch (err) {\n    pageModelSave.reason = bounded(err);" in script
        # The marker and the two verdicts a reader needs before trusting it.
        assert 'const MARKER_ID = "00000000-0000-0000-0004-000000000001";' in script
        assert "pageModelSave.bodyApplied = after.some(b => b.id === MARKER_ID);" in script
        assert "kept.canvas === before.get(id)" in script
        assert "pageModelSave: pageModelSave," in script

    def test_script_names_what_it_did_not_measure(self):
        """The findings that are structural rather than behavioural ('cannot
        be set via a page save') travel with the document, dated by the run."""
        script = generate_discover_script()
        start = script.index("unmeasured: [")
        block = script[start : script.index("],", start)]
        for topic in ("theme", "section-background", "section-spacing", "rendering"):
            assert f'topic: "{topic}"' in block, topic

    def test_script_places_each_representative_part_twice_with_one_property_changed(self):
        """M5 (1): six parts, a default and a modified instance each, the
        modified one carrying ONE flat property, requested and persisted
        paired by control id under webpartProperties. The stored value at
        the path is decoded on the JS side so the Python side judges a
        value, not a block. ListWebPart stands in for DocumentLibraryWebPart,
        which the site's catalogue does not carry."""
        script = generate_discover_script()
        start = script.index("const PROPERTY_SAMPLES = [")
        samples = script[start : script.index("];", start)]
        for alias in ("NewsWebPart", "QuickLinksWebPart", "ImageWebPart", "EventsWebPart",
                      "HeroWebPart", "ListWebPart"):
            assert f'component: "{alias}"' in samples, alias
        assert samples.count("path:") == 6
        # Types spread: boolean, enum, text with a ':' (the measured rewrite),
        # numeric string, boolean.
        assert 'path: "showChrome", value: false' in samples
        assert 'path: "captionText", value: "Formwork caption probe: image"' in samples
        assert 'path: "heroLayoutThreshold", value: "320"' in samples
        assert 'for (const variant of ["default", "modified"])' in script
        assert 'padId("0005", propertyControls.length + 1)' in script
        assert "webPartBlock(p.cd, { properties: p.properties })" in script
        assert "storedValue: present ? props[p.propertyPath] : null" in script
        assert re.search(
            r"webpartProperties: \{\n\s*requested: propertyRequested,\n\s*"
            r"persisted: propertyPersisted,\n\s*skipped: propertySkipped,",
            script,
        )
        # The absent part is a finding, not a throw.
        assert "propertySkipped.push({ component: sample.component," in script

    def test_script_places_the_one_third_layouts_and_a_column_two_control(self):
        """M5 (2): 8/4 and 4/8 splits, and a 4/8 split whose column-2
        control is written before its column-1 control, each control
        requested/persisted by id under layoutVariants."""
        script = generate_discover_script()
        start = script.index("const LAYOUT_SAMPLES = [")
        samples = script[start : script.index("];", start)]
        assert 'section: "split-8-4", factors: [8, 4], columns: [1]' in samples
        assert 'section: "split-4-8", factors: [4, 8], columns: [1]' in samples
        assert 'section: "split-4-8-two", factors: [4, 8], columns: [2, 1]' in samples
        assert 'padId("0006", layoutControls.length + 1)' in script
        assert "sectionFactor: section.factors[col - 1]" in script
        assert "const layoutPersisted = persistedFor(storedBlocks, layoutRequested);" in script
        assert re.search(
            r"layoutVariants: \{\n\s*requested: layoutRequested,\n\s*persisted: layoutPersisted,",
            script,
        )

    def test_script_binds_parts_to_two_fixture_lists_it_creates_and_recycles(self):
        """M5 (3): a custom list and a document library created BEFORE the
        scratch page with their real ids, URLs and default view read from
        web/lists; the library and list entries of ListWebPart bound to
        each, Quick links pointed at each default view; both recycled AFTER
        the scratch page and before the download, each outcome recorded."""
        script = generate_discover_script()
        assert 'API("web/lists")' in script
        assert '{ key: "list", title: "Formwork Probe Source", baseTemplate: 100 }' in script
        assert '{ key: "library", title: "Formwork Probe Docs", baseTemplate: 101 }' in script
        assert '__metadata: { type: "SP.List" }' in script
        assert "?$select=Id,Title,DefaultViewUrl,RootFolder/ServerRelativeUrl," in script
        assert "DefaultView/Id" in script
        assert "&$expand=RootFolder,DefaultView" in script
        # The measured binding shape (collabhome.bundle.json, 2026-09-05),
        # filled from the fixture, never guessed.
        for key in (
            "selectedListId: probe.id",
            "selectedListUrl: probe.serverRelativeUrl",
            "webRelativeListUrl: probe.webRelativeUrl",
            "webpartHeightKey: 4",
            "selectedViewId: probe.defaultViewId",
            "searchablePlainTexts: { listTitle: probe.title }",
            '"items[0].sourceItem.url": location.origin + probe.defaultViewUrl',
            '"items[0].title": probe.title',
        ):
            assert key in script, key
        start = script.index("const BINDING_SAMPLES = [")
        samples = script[start : script.index("];", start)]
        assert samples.count("label:") == 6
        assert samples.count('target: "library"') == 3
        assert samples.count('target: "list"') == 3
        assert samples.count("library: true") == 2
        assert samples.count("library: false") == 2
        assert 'padId("0007", bindingControls.length + 1)' in script
        assert re.search(
            r"listBindings: \{\n\s*fixtures: probeLists,\n\s*requested: bindingRequested,\n\s*"
            r"persisted: bindingPersisted,\n\s*skipped: bindingSkipped,",
            script,
        )
        # Fixtures before the page; page recycled, then the lists, then the download.
        assert script.index('API("web/lists")') < script.index("await createSitePage(SCRATCH)")
        page_recycle = script.index('")/recycle"')
        list_recycle = script.index("')/recycle\"")
        assert page_recycle < list_recycle < script.index("URL.createObjectURL")
        # Non-fatal at both ends, with the server's reason.
        assert "probe.reason = spError(" in script
        assert "probe.recycleReason = spError(" in script
        assert "bindingSkipped.push({ label: s.label," in script
        # The M1/M3 web-part blocks still go through the same builder with
        # no options, so their bytes are unchanged by the M5 overrides.
        assert "const block = webPartBlock(s.cd);" in script
        assert "Object.assign({}, entry.properties || {}, o.properties || {})" in script
        assert 'schema: "formwork.discovery/v1"' in script

    def test_script_measures_page_state_on_scratch_pages_it_recycles(self):
        """M7 (2026-09-07): six scratch pages of the lane's own, each created
        through sitepages/pages with one identity or state field under test
        (an explicit FileName, one needing normalisation, the Article layout,
        PromotedState at create and by item MERGE, checkout then publish),
        read back three ways (page entity, list item, the item's
        HasUniqueRoleAssignments), recycled after the M5 lists and before the
        download; the document carries the samples under an additive
        pageState key and names what the lane did not measure."""
        script = generate_discover_script()
        start = script.index("// 5d. Page state and identity")
        lane = script[start : script.index("// 6. Download the discovery document.")]
        assert lane.count('await pageStateSample("') == 6
        for pin in (
            'const PAGE_STATE = "formwork-pagestate-" + STAMP;',
            'FileName: PAGE_STATE + "-explicit.aspx"',
            '"Formwork PageState " + STAMP + " Needs Slug.aspx"',
            'create: { PageLayoutType: "Article" }',
            'create: { PageLayoutType: "Article", PromotedState: 1 }',
            "merge: { PromotedState: 1 }",
            'pageAction(id, "checkoutpage")',
            'pageAction(id, "publish")',
            'pageAction(id, "SavePageAsDraft"',
            'API("sitepages/pages(" + id + ")/" + action)',
            '__metadata: { type: "SP.Publishing.SitePage" }',
            '__metadata: { type: "SP.FieldUrlValue" }',
            '__metadata: { type: "SP.Data.SitePagesItem" }',
            '"X-HTTP-Method": "MERGE", "If-Match": item.d.__metadata.etag',
            "?$select=Id,HasUniqueRoleAssignments",
            '"OData__UIVersionString", "CheckoutUserId"',
            "sample.pageId = page.Id;",
            "sample.persisted.created = pick(page, PAGE_FIELDS);",
            'pageStateSample("filename-explicit", ["fileName", "description", "bannerImageUrl"]',
            'pageStateSample("filename-normalised", ["fileName", "permissionInheritance"]',
            'pageStateSample("layout-article", ["layout"]',
            'pageStateSample("promoted-at-create", ["promotedState", "layout"]',
            'pageStateSample("promoted-merge-flip", ["promotedState"]',
            'pageStateSample("publish-state", ["publishState"]',
        ):
            assert pin in lane, pin
        # The additive key, in discover's document, with the day it ran.
        assert re.search(
            r"pageState: \{\n\s*measuredAt: new Date\(\)\.toISOString\(\)\.slice\(0, 10\),\n"
            r"\s*scratchPrefix: PAGE_STATE,\n\s*pageKeys: pageStateKeys,\n"
            r"\s*samples: pageStateSamples,\n\s*unmeasured: pageStateUnmeasured,",
            script,
        )
        # What is not claimed is named; the DSL's refused page keys first.
        for key in UNMEASURED_PAGE_KEYS:
            assert f'topic: "{key}"' in lane, key
        for topic in ("permission-break", "banner-json", "rendering"):
            assert f'topic: "{topic}"' in lane, topic
        # Recycled after the M5 lists and before the download, non-fatally;
        # a refused create is a sample with the reason, not a thrown run.
        page_state_recycle = script.index('PAGES + "/items(" + sample.pageId + ")/recycle"')
        assert script.index("')/recycle\"") < page_state_recycle
        assert page_state_recycle < script.index("URL.createObjectURL")
        assert "sample.recycleReason = spError(" in lane
        assert 'throw await failed("page-state create " + sample.label, res);' in lane
        assert "sample.reason = bounded(err);" in lane
        # The lane is the third shared partial: findprobe carries it too.
        findprobe = GENERATORS["findprobe"]()
        assert lane in findprobe
        assert "pageStateScratchIds: pageStateSamples.map(s => s.pageId)," in findprobe


@pytest.mark.skipif(not node_available(), reason="node is not installed")
class TestApplyScript:
    def test_script_is_syntactically_valid_javascript(self, tmp_path):
        result = node_check(generate_apply_script(), tmp_path)
        assert result.returncode == 0, result.stderr.decode()

    def test_script_creates_page_then_patches_canvas(self):
        script = generate_apply_script()
        assert "AddFolder" not in script  # legacy: no misleading calls
        assert 'API("web/lists/getbytitle' in script
        assert "sitepages/pages" in script  # measured: Files/add of .aspx -> 403
        # digest + MERGE + etag concurrency control
        assert "contextinfo" in script
        assert "X-HTTP-Method" in script
        assert "IF-MATCH" in script.upper().replace("_", "-") or "If-Match" in script

    def test_script_reports_verification_step(self):
        script = generate_apply_script()
        assert "CanvasContent1" in script
        assert "verify" in script.lower()

    def test_digest_is_posted_not_get(self):
        # GET /_api/contextinfo is refused with 405 (measured live).
        for script in (generate_apply_script(), generate_discover_script()):
            assert "getDigest" in script
            assert 'getJson("/_api/contextinfo")' not in script

    def test_script_accepts_page_name_variable(self):
        script = generate_apply_script("My Copied Page")
        assert '"My Copied Page"' in script

    def test_embedded_payload_is_configurable(self):
        script = generate_apply_script(page_name="X", canvas_payload='{"k":1}')
        assert '"X"' in script
        assert json.dumps('{"k":1}') in script  # JSON-embedded, quotes escaped

    def test_awkward_payload_decodes_back_to_itself(self):
        # The golden pins the bytes; this pins the meaning: the literal the
        # script parses at runtime is the payload, character for character.
        script = GENERATORS["apply-payload"]()
        literal = re.search(r'JSON\.parse\("(.+)"\);', script)
        assert literal, "no embedded payload literal found"
        assert json.loads(f'"{literal.group(1)}"') == APPLY_PAYLOAD
        assert f"const PAGE_NAME = {json.dumps(APPLY_PAYLOAD_NAME)};" in script
        assert "const PROMOTED_STATE = 1;" in script


@pytest.mark.parametrize("name", sorted(GENERATORS))
class TestTransportFacts:
    """Transport facts ported from dbml-sharepoint v0.4.0 (read 2026-09-06).

    One pin per fact, on every generated script, so the prelude cannot lose a
    fact without a test going red. Each names the partial the fact came from;
    the Jinja comments at the top of _prelude.js.j2 carry the same citations
    (pinned by test_prelude_cites_the_four_transport_facts_with_dates).
    """

    def test_throttle_is_detected_on_the_final_url_not_the_status(self, name):
        # A throttled browser session is redirected to the throttling page,
        # which arrives as 406 because the script asked for JSON. Detection
        # keys on the final URL (dbml-sharepoint _http.js.j2:36-44), and one
        # gate holds every lane (_http.js.j2:45-63). Pins are composed with
        # BS (one backslash) so no transport layer can rewrite escapes.
        script = GENERATORS[name]()
        throttle_re = (
            "/" + BS + "/_layouts" + BS + "/15" + BS + "/throttle"
            + BS + ".htm(" + BS + "?|$)/i"
        )
        assert throttle_re in script
        # `||` here, not `&&`: a throttled browser session arrives as 406
        # from the redirect, not 429/503. Pin the expression across both
        # lines so `||` -> `&&` cannot slip through (review P2-2).
        detection = re.search(
            "res" + BS + ".status === 429 [|][|] res" + BS + ".status === 503"
            + BS + "s* [|][|] " + BS + "s*THROTTLE_PAGE" + BS + ".test"
            + BS + "(res" + BS + ".url",
            script,
        )
        assert detection, "throttle detection must key on the final URL"
        assert "Retry-After" in script
        # Pin the call sites with their await: the bare definitions would
        # otherwise satisfy the pin while the calls were deleted (P2-2).
        assert "await passThrottleGate();" in script
        assert "await holdEveryLane(wait);" in script
        # Every request goes out through fetchWithRetry: the one bare fetch()
        # is the wrapper's own call.
        assert script.count("await fetch(") == 1
        assert "await fetchWithRetry(" in script

    def test_non_ok_responses_surface_the_server_reason(self, name):
        # error.message.value is the server's reason; a bare status left a
        # blocked run undiagnosable (dbml-sharepoint _http.js.j2:25-34, live
        # finding 2026-07-24).
        script = GENERATORS[name]()
        assert "?.error?.message?.value" in script
        # No throw is left carrying only the status.
        assert not re.search(r'-> " \+ \w+\.status\)', script)
        # Every non-OK branch raises through failed(), which shapes the body
        # with spError, or shapes it with spError directly (the digest).
        checks = list(re.finditer(r"if \(!\w+\.ok\)", script))
        assert len(checks) >= 6, "the pin is meaningless if nothing is checked"
        for check in checks:
            window = script[check.end() : check.end() + 200]
            assert "failed(" in window or "spError(" in window, window

    def test_contextinfo_parse_is_guarded(self, name):
        # The blind .d.GetContextWebInformation.FormDigestValue chain is what
        # reported dbml-sharepoint #282 as a TypeError in place of the
        # server's reason (dbml-sharepoint _digest_cached.js.j2:9-42).
        script = GENERATORS[name]()
        assert not re.search(r"\)\s*\.d\s*\.GetContextWebInformation", script)
        assert "?.d?.GetContextWebInformation" in script
        assert "contextinfo (request digest) failed: " in script
        for guard in (
            "no response (",
            "with an unreadable body (",
            "carried no GetContextWebInformation",
            "carried no usable FormDigestValue",
        ):
            assert guard in script, guard
        # Still POSTed (GET -> 405), and parsed in exactly one place.
        assert re.search(r'API\("contextinfo"\), \{\n\s*method: "POST"', script)
        assert script.count("?.d?.GetContextWebInformation") == 1

    def test_list_titles_are_odata_quoted(self, name):
        # getbytitle('...') takes an OData literal: an embedded apostrophe is
        # doubled, then the whole is URI-encoded (dbml-sharepoint
        # _site_guard.js.j2:24-27).
        script = GENERATORS[name]()
        assert "const odataLiteral = (s) => String(s).replace(/'/g, \"''\");" in script
        assert "const odataName = (name) => encodeURIComponent(odataLiteral(name));" in script
        # The only getbytitle left is the helper; every list URL goes through it.
        assert script.count("getbytitle(") == 1
        assert "getbytitle('\" + odataName(title) + \"')" in script
        assert "'Site Pages'" not in script
        assert 'listByTitle("Site Pages")' in script


#: The package the templates live in.
PACKAGE = pathlib.Path(__file__).parent.parent / "src" / "formwork"


def test_site_pages_title_is_named_only_by_the_display_layer():
    """One source of truth for the list title: the Jinja templates emit it,
    and exactly one of them (the shared prelude) names it. No Python module
    carries the literal, so the display layer cannot drift from the code."""
    python_hits = sorted(
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if "Site Pages" in path.read_text(encoding="utf-8")
    )
    assert python_hits == [], python_hits
    emitters = sorted(
        path.name
        for path in (PACKAGE / "templates").glob("*.j2")
        if 'listByTitle("Site Pages")' in path.read_text(encoding="utf-8")
    )
    assert emitters == ["_prelude.js.j2"]


def test_prelude_cites_the_four_transport_facts_with_dates():
    """The citations are Jinja comments, stripped from every emitted script,
    so no golden or script pin can hold them (review P3-8, 2026-09-06). Read
    the template: each fact names its dbml-sharepoint partial and a date."""
    prelude = (PACKAGE / "templates" / "_prelude.js.j2").read_text(encoding="utf-8")
    facts = re.findall(
        r"Transport fact (\d) \(dbml-sharepoint (_\w+\.js\.j2):[^,]+,\s+"
        r"(?:read|live finding)\s+(20\d\d-\d\d-\d\d)\)",
        prelude,
    )
    assert facts == [
        ("1", "_http.js.j2", "2026-09-06"),
        ("2", "_http.js.j2", "2026-07-24"),
        ("3", "_digest_cached.js.j2", "2026-09-06"),
        ("4", "_site_guard.js.j2", "2026-09-06"),
    ]
    # And none of it reaches the operator's paste-in.
    for name, generate in GENERATORS.items():
        assert "Transport fact" not in generate(), name


def test_prelude_carries_no_post_json_helper():
    """postJson had no caller in any script once getDigest grew its own
    guarded fetch; it is gone from the prelude (review P3-1, 2026-09-06)."""
    for name, generate in GENERATORS.items():
        assert "postJson" not in generate(), name


def test_apply_mismatch_names_the_page_it_leaves_behind_and_never_recycles_it():
    """The byte-exact check runs after the page is created and merged, so a
    mismatch leaves a page behind. The thrown error says the page exists,
    names its item id and URL, and states that Formwork does not recycle
    it; nothing in the apply script calls recycle (review P1-1, 2026-09-06).
    The comparison itself stays strict: compile emits ':' as '&#58;' in text
    HTML (test_dsl, test_styling_evidence), so nothing here folds."""
    for name in ("apply", "apply-payload"):
        script = GENERATORS[name]()
        assert "stored.CanvasContent1 === PAYLOAD.canvas" in script, name
        assert 'The page EXISTS with what SharePoint stored: item " + created.id' in script, name
        assert "location.origin + created.url" in script, name
        assert "Formwork does not recycle it; keep it or recycle it yourself." in script, name
        assert "recycle(" not in script and "/recycle" not in script, name
        assert script.index("[formwork] page created:") < script.index("The page EXISTS"), name


def test_extract_bundle_carries_no_web_part_list():
    """The bundle's web parts are read from its canvas; the extract script
    writes no ``webParts`` key (it only ever wrote an empty list, and a
    rewriter that read it rewrote nothing: review P1-2, 2026-09-06)."""
    script = generate_extract_script()
    assert "webParts" not in script
    assert "page: page,\n    sections: [],\n  };" in script


def test_extract_filter_literal_doubles_apostrophes():
    # The same OData rule applies to the $filter literal the extract script
    # builds from the page's file name (a page named "Bob's page.aspx" is
    # legal). Doubling only: the whole filter is URI-encoded once, after.
    script = generate_extract_script()
    assert "\"FileLeafRef eq '\" + odataLiteral(fileName) + \"'\"" in script


@pytest.mark.parametrize("name", sorted(GENERATORS))
def test_script_matches_golden(name):
    """Golden-file regression: each generated script must match its committed
    fixture byte for byte. See the module docstring for the regeneration
    command."""
    golden_path = EXPECTED / f"{name}.js"
    assert golden_path.exists(), f"golden file missing: {golden_path}"
    assert GENERATORS[name]() == golden_path.read_text(encoding="utf-8"), (
        f"the {name} script output has changed. If the change is intentional, "
        "regenerate the golden files (see the module docstring for the command) "
        "and review the diff."
    )


if __name__ == "__main__":  # pragma: no cover
    # Regenerate the goldens. Deliberately not a pytest flag: see
    # test_script_matches_golden. Uses the SAME generator calls the test does.
    EXPECTED.mkdir(parents=True, exist_ok=True)
    for _name, _generate in GENERATORS.items():
        _target = EXPECTED / f"{_name}.js"
        write_golden(_target, _generate())
        print(f"wrote {_target}")
