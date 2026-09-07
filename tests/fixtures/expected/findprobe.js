// formwork findprobe v0.6.0 — run from any page of the site.
// Re-runs every measurement FINDINGS.md records: creates two probe lists
// and a scratch page, places the text, styling, property, layout and
// list-binding probes, reads back, establishes section emphasis through
// SavePage on a second scratch page, recycles all four, diffs each result
// against the registry and downloads formwork-findprobe.json.
(async () => {
  const SCHEMA = "formwork.bundle/v1";
  const VERBOSE = "application/json;odata=verbose";
  // The site prefix of the page this script runs on, e.g.
  // "/sites/TeamX" from "/sites/TeamX/SitePages/Home.aspx", or "" on the
  // tenant root site.
  const SITE = location.pathname.match(/^(\/.*)\/SitePages\//i);
  const PREFIX = SITE ? SITE[1] : "";
  if (!/^\/SitePages\//i.test(location.pathname) && !SITE) {
    throw new Error("Run this from a modern page under .../SitePages/");
  }
  const API = (path) => PREFIX + "/_api/" + path.replace(/^\/+/, "");
  // OData string literals: getbytitle and $filter take single-quoted
  // literals where an embedded apostrophe must be DOUBLED (''), and
  // encodeURIComponent alone does not escape it (dbml-sharepoint
  // _site_guard.js.j2:24-27, read 2026-09-06). odataLiteral doubles;
  // odataName doubles and URI-encodes for use inside a path segment.
  const odataLiteral = (s) => String(s).replace(/'/g, "''");
  const odataName = (name) => encodeURIComponent(odataLiteral(name));
  const listByTitle = (title) => API("web/lists/getbytitle('" + odataName(title) + "')");
  const PAGES = listByTitle("Site Pages");
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const bounded = (e) => String((e && e.message) || e).slice(0, 300);
  // SharePoint's REST error body carries the human-readable reason at
  // error.message.value; fall back to (bounded) raw text. A bare HTTP
  // status left a blocked run undiagnosable (dbml-sharepoint
  // _http.js.j2:25-34, live finding 2026-07-24).
  const spError = (text) => {
    let message = text;
    try {
      message = JSON.parse(text)?.error?.message?.value || text;
    } catch {}
    return String(message).slice(0, 300);
  };
  // Every non-OK response is raised through here, so the operator reads the
  // server's reason next to the operation and the status.
  async function failed(what, res) {
    const body = await res.text().catch((e) => "body unreadable: " + bounded(e));
    return new Error(what + " -> " + res.status + " " + spError(body));
  }
  // A throttled BROWSER session is not answered with 429: SharePoint
  // redirects it to the throttling page, which is HTML and so arrives as
  // 406 Not Acceptable because every call here asks for JSON. Match the
  // FINAL URL, not the status: keying on 406 would also retry every genuine
  // content-negotiation refusal (dbml-sharepoint _http.js.j2:36-44, read
  // 2026-09-06). 429 and 503 are the API-style answers and carry Retry-After.
  const THROTTLE_PAGE = /\/_layouts\/15\/throttle\.htm(\?|$)/i;
  const isThrottled = (res) => res.status === 429 || res.status === 503
    || THROTTLE_PAGE.test(res.url || "");
  // One pause for the whole run, not one per caller: the first refused
  // request opens the gate and every request waits on it before going out,
  // so nothing keeps spending quota against a tenant that is already
  // refusing (dbml-sharepoint _http.js.j2:45-63). These scripts are
  // sequential today; the gate is what keeps that true under a retry.
  let throttleGate = null;
  async function passThrottleGate() {
    while (throttleGate) await throttleGate;
  }
  function holdEveryLane(seconds) {
    if (!throttleGate) {
      throttleGate = sleep(seconds * 1000).then(() => { throttleGate = null; });
    }
    return throttleGate;
  }
  // Retry-After-aware fetch: honour the server's Retry-After (seconds), else
  // back off exponentially (capped at 60s), up to `attempts` before handing
  // the final response to the caller's own error handling. The browser
  // redirect is an HTML page with no Retry-After, so on that path the
  // backoff is all there is.
  async function fetchWithRetry(url, opts, attempts = 8) {
    for (let i = 0; ; i++) {
      await passThrottleGate();
      const res = await fetch(url, opts);
      if (isThrottled(res) && i < attempts) {
        const wait = Number(res.headers.get("Retry-After")) || Math.min(2 ** i, 60);
        const how = THROTTLE_PAGE.test(res.url || "")
          ? "redirected to the throttling page (HTTP " + res.status + ")"
          : "HTTP " + res.status;
        console.warn("[formwork] throttled, " + how + "; waiting " + wait +
          "s, retry " + (i + 1) + "/" + attempts);
        await holdEveryLane(wait);
        continue;
      }
      return res;
    }
  }
  async function getJson(url) {
    const res = await fetchWithRetry(url, { headers: { Accept: VERBOSE } });
    if (!res.ok) throw await failed("GET " + url, res);
    return res.json();
  }
  // The context digest must be POSTed — GET is refused with 405. This is the
  // one place a contextinfo response is parsed, and each step is guarded: the
  // blind .d.GetContextWebInformation.FormDigestValue chain is what reported
  // dbml-sharepoint #282 as a TypeError in place of the server's reason
  // (dbml-sharepoint _digest_cached.js.j2:9-42, read 2026-09-06).
  async function getDigest() {
    const digestFailed = (detail) =>
      new Error("contextinfo (request digest) failed: " + detail);
    let res;
    try {
      res = await fetchWithRetry(API("contextinfo"), {
        method: "POST",
        headers: { Accept: VERBOSE, "Content-Type": VERBOSE },
        body: "{}",
      });
    } catch (err) {
      // fetch rejects outright on a network or CORS failure: no status to
      // report, only the operation.
      throw digestFailed("no response (" + bounded(err) + ")");
    }
    if (!res.ok) {
      const body = await res.text().catch((e) => "body unreadable: " + bounded(e));
      throw digestFailed("HTTP " + res.status + " " + spError(body));
    }
    let info = null;
    try {
      info = (await res.json())?.d?.GetContextWebInformation;
    } catch (err) {
      throw digestFailed("HTTP " + res.status + " with an unreadable body (" + bounded(err) + ")");
    }
    // A 200 carrying no GetContextWebInformation is the same blind
    // dereference one step further along.
    if (!info || typeof info !== "object" || Array.isArray(info)) {
      throw digestFailed("HTTP " + res.status + " carried no GetContextWebInformation");
    }
    if (typeof info.FormDigestValue !== "string" || !info.FormDigestValue.trim()) {
      throw digestFailed("HTTP " + res.status + " carried no usable FormDigestValue");
    }
    return info.FormDigestValue;
  }
  // Pages are created through the sitepages API: Files/add refuses .aspx
  // (403), and a list-item POST into Site Pages is refused outright.
  // `fields` ride in the create body beside the layout: apply sends
  // PromotedState there, where it persisted (page.promoted-state.create-is-effective).
  async function createSitePage(title, fields) {
    const digest = await getDigest();
    const res = await fetchWithRetry(API("sitepages/pages"), {
      method: "POST",
      headers: { Accept: VERBOSE, "Content-Type": VERBOSE, "X-RequestDigest": digest },
      body: JSON.stringify({
        __metadata: { type: "SP.Publishing.SitePage" },
        PageLayoutType: "Home",
        ...fields,
      }),
    });
    if (!res.ok) throw await failed("page create", res);
    const page = (await res.json()).d;
    return {
      id: page.Id,
      url: page.Url,
      title: title,
      setFields: async (fields) => {
        const itemRes = await fetchWithRetry(
          PAGES + "/items(" + page.Id + ")",
          { headers: { Accept: VERBOSE } }
        );
        if (!itemRes.ok) throw await failed("item read", itemRes);
        const item = (await itemRes.json()).d;
        const mergeRes = await fetchWithRetry(
          PAGES + "/items(" + page.Id + ")",
          {
            method: "POST",
            headers: {
              Accept: VERBOSE,
              "Content-Type": VERBOSE,
              "X-RequestDigest": await getDigest(),
              "X-HTTP-Method": "MERGE",
              "If-Match": item.__metadata.etag,
            },
            body: JSON.stringify({
              __metadata: { type: "SP.Data.SitePagesItem" },
              ...fields,
            }),
          }
        );
        if (!mergeRes.ok) throw await failed("item update", mergeRes);
      },
    };
  }

  // 0. The registry as generated: check-id, lane, measured date and the
  //    recorded result. A findprobe-lane row is judged word for word against
  //    the verdict computed in step 6; a discover-lane row is listed, not
  //    re-run (formwork gen discover re-derives it).
  const FINDINGS = [
    {
      "checkId": "page.components.merge-byte-exact",
      "lane": "discover",
      "measured": "2026-09-06",
      "result": "stored count equals placed count"
    },
    {
      "checkId": "page.layout.default-factors",
      "lane": "discover",
      "measured": "2026-09-06",
      "result": "12, 6/6, 4/4/4 read back"
    },
    {
      "checkId": "page.text.colon-rewrite",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "2/2 byte-exact after the ':' fold"
    },
    {
      "checkId": "page.text.styled-html",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "7/7 byte-exact after the ':' fold; byte-identical: mark, rte-classes"
    },
    {
      "checkId": "page.emphasis.control-merge",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "2/2 byte-exact; zoneEmphasis 2, 3 read back"
    },
    {
      "checkId": "page.section.variants-merge",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "3/3 byte-exact"
    },
    {
      "checkId": "page.page-model.draft-refuses-html",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "refused 500: Unexpected character encountered while parsing value: <"
    },
    {
      "checkId": "page.emphasis.section-savepage",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "SavePage 200; zoneEmphasis survived 2, 3; merged control 3"
    },
    {
      "checkId": "page.properties.news-web-part",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "2/2 byte-exact; showChrome true to false round-tripped"
    },
    {
      "checkId": "page.properties.quick-links-web-part",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "2/2 byte-exact; layoutId \"CompactCard\" to \"List\" round-tripped"
    },
    {
      "checkId": "page.properties.image-web-part",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "2/2 byte-exact; captionText \"\" to \"Formwork caption probe: image\" round-tripped"
    },
    {
      "checkId": "page.properties.events-web-part",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "2/2 byte-exact; layout \"Filmstrip\" to \"Compact\" round-tripped"
    },
    {
      "checkId": "page.properties.hero-web-part",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "2/2 byte-exact; heroLayoutThreshold \"640\" to \"320\" round-tripped"
    },
    {
      "checkId": "page.properties.list-web-part",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "2/2 byte-exact; isDocumentLibrary false to true round-tripped"
    },
    {
      "checkId": "page.layout.factors-8-4",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "1/1 byte-exact"
    },
    {
      "checkId": "page.layout.factors-4-8",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "3/3 byte-exact; written order kept"
    },
    {
      "checkId": "page.bind.list-library-keys",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "6/6 byte-exact"
    },
    {
      "checkId": "page.page-state.filename-slug",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "explicit: ignored (stored d0i8msje.aspx); slug-needing: ignored (stored b1xk6f0f.aspx)"
    },
    {
      "checkId": "page.page-state.description-banner",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "description null; banner persisted"
    },
    {
      "checkId": "page.page-state.layout-article",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "PageLayoutType Article"
    },
    {
      "checkId": "page.page-state.promoted-state",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "at create 1; after merge 0 (merge status 204)"
    },
    {
      "checkId": "page.page-state.publish-flow",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "fresh 0.1 checked out; checkoutpage 200; publish 200 -> 1.0, checked out false"
    },
    {
      "checkId": "page.page-state.permission-inheritance",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "false"
    },
    {
      "checkId": "page.promoted-state.create-is-effective",
      "lane": "findprobe",
      "measured": "2026-09-06",
      "result": "PromotedState 1 at create beside Article"
    }
  ];

  // 1. Enumerate every placeable component on this site.
  const partsRes = await fetchWithRetry(API("web/GetClientSideWebParts"), {
    headers: { Accept: "application/json;odata=nometadata" },
  });
  if (!partsRes.ok) throw await failed("GetClientSideWebParts", partsRes);
  const components = (await partsRes.json()).value || [];

  // 2. Create the scratch page, then write the discovery canvas onto it.
  const SCRATCH = "formwork-discovery-" + Date.now();

  // 2a. The web the probes run on. Its server-relative root is what a
  //     list-bound part's webRelativeListUrl is relative to: measured on
  //     the live CollabHome canvas (tests/fixtures/collabhome.bundle.json,
  //     2026-09-05), selectedListUrl "/sites/TestSampleTeam/Shared
  //     Documents" travels with webRelativeListUrl "Shared Documents".
  const web = await getJson(API("web?$select=Id,Title,Url,ServerRelativeUrl"));
  const webRoot = web.d.ServerRelativeUrl === "/" ? "" : web.d.ServerRelativeUrl;
  const webRelative = (serverRelativeUrl) =>
    serverRelativeUrl.startsWith(webRoot + "/")
      ? serverRelativeUrl.slice(webRoot.length + 1) : serverRelativeUrl;

  // 2b. M5 list-binding fixtures: a custom list and a document library of
  //     this run's own, created BEFORE the scratch page so the binding
  //     probe (3g) writes real ids and URLs, read back from _api/web/lists
  //     rather than guessed. Both are recycled after the scratch page (5a).
  //     Non-fatal: a refused create is recorded with the server's reason
  //     and every binding that targets it is skipped, not invented. A list
  //     created but not fully described (the detail read failed) is still
  //     recycled; only a binding needs the detail.
  const PROBE_LISTS = [
    { key: "list", title: "Formwork Probe Source", baseTemplate: 100 },
    { key: "library", title: "Formwork Probe Docs", baseTemplate: 101 },
  ];
  const probeLists = [];
  for (const spec of PROBE_LISTS) {
    const probe = {
      key: spec.key, title: spec.title, baseTemplate: spec.baseTemplate,
      created: false, status: 0, reason: "",
      id: null, serverRelativeUrl: null, webRelativeUrl: null, defaultViewId: null, defaultViewUrl: null,
      recycled: null, recycleStatus: 0, recycleReason: "",
    };
    probeLists.push(probe);
    try {
      const createRes = await fetchWithRetry(API("web/lists"), {
        method: "POST",
        headers: { Accept: VERBOSE, "Content-Type": VERBOSE, "X-RequestDigest": await getDigest() },
        body: JSON.stringify({
          __metadata: { type: "SP.List" },
          Title: spec.title,
          BaseTemplate: spec.baseTemplate,
        }),
      });
      probe.status = createRes.status;
      if (!createRes.ok) {
        probe.reason = spError(await createRes.text().catch((e) => "body unreadable: " + bounded(e)));
        continue;
      }
      probe.created = true;
      probe.id = (await createRes.json()).d.Id;
      const detail = (await getJson(API("web/lists(guid'" + probe.id + "')" +
        "?$select=Id,Title,DefaultViewUrl,RootFolder/ServerRelativeUrl,DefaultView/Id" +
        "&$expand=RootFolder,DefaultView"))).d;
      probe.serverRelativeUrl = detail.RootFolder.ServerRelativeUrl;
      probe.webRelativeUrl = webRelative(detail.RootFolder.ServerRelativeUrl);
      probe.defaultViewId = detail.DefaultView.Id;
      probe.defaultViewUrl = detail.DefaultViewUrl;
    } catch (err) {
      probe.reason = bounded(err);
    }
  }

  // 3. The catalogue spread is discover's; the legs need the placeable
  //    parts, the section list they extend and an empty control list.
  const placeable = components.filter(c => c.ComponentType === 1);
  if (!placeable.length) {
    throw new Error("GetClientSideWebParts returned no placeable web part (ComponentType 1)");
  }
  const sections = [];
  const controls = [];

  // 3a. Text controls are NOT web parts: controlType 4, no webPartId, no
  //     webpartdata; the HTML is the inner content of a data-sp-rte child.
  //     That is the shape PnP has written since 2017 and is what is SENT
  //     here. Two known bodies go into a fourth, one-column section and
  //     both the requested and the persisted blocks are downloaded
  //     verbatim. Measured (shauntestazure, 2026-09-06, 75 controls):
  //     SharePoint stores the block byte-identically except that ':' in
  //     the inner HTML — text and attribute values alike — is rewritten as
  //     '&#58;'. The compiler gates on that measurement
  //     (catalogue.TextControlSample.persisted_matches).
  const TEXT_SAMPLES = [
    '<h2>Formwork text probe</h2><p>Paragraph with <b>bold</b>, ' +
      '<a href="https://example.com/">a link</a> and ' +
      '<span style="color:#a4262c;">a colour span</span>.</p>',
    '<p>Second text control: <strong>strong</strong>, <em>emphasis</em>, ' +
      'and a list.</p><ul><li>one</li><li>two</li></ul>',
  ];
  const textControlData = (id, zoneIndex, sectionIndex, controlIndex) => ({
    controlType: 4,
    id: id,
    position: {
      zoneIndex: zoneIndex,
      sectionIndex: sectionIndex,
      controlIndex: controlIndex,
      zoneId: null,
      sectionFactor: 12,
      layoutIndex: 1,
    },
    emphasis: {},
    editorType: "CKEditor",
  });
  const textSection = { type: "text", zoneIndex: (sections.length + 1) * 1000, factors: [12] };
  sections.push(textSection);
  const textControls = TEXT_SAMPLES.map((html, i) => ({
    html: html,
    cd: textControlData("00000000-0000-0000-0001-" + String(i + 1).padStart(12, "0"),
      textSection.zoneIndex, sections.length, i + 1),
  }));

  // 3b. M3 styling probe: what SharePoint keeps of styled text. Each sample
  //     is a text control of its own in a fifth, one-column section, so a
  //     dropped or rewritten construct is attributable to one sample. The
  //     inline-style samples are what a DSL author would write; the last
  //     sample carries the class names SharePoint's own editor writes for
  //     colour, size and highlight, so the two idioms are measured side by
  //     side. Persistence only: whether the text web part RENDERS an inline
  //     style is a browser question this readback cannot answer.
  //     finding: page.text.styled-html (FINDINGS.md, 2026-09-06): 7/7 came
  //     back with only the ':' rewrite; the DSL passes styled HTML through.
  const STYLE_SAMPLES = [
    { label: "color", html: '<p><span style="color:#a4262c;">colour by style</span></p>' },
    { label: "font-size", html: '<p><span style="font-size:24px;">size by style</span></p>' },
    { label: "background",
      html: '<p><span style="background-color:#fff100;">background by style</span></p>' },
    { label: "styled-link",
      html: '<p><a href="https://example.com/" style="color:#0078d4;text-decoration:underline;">' +
        'styled link</a></p>' },
    { label: "mark", html: '<p>Text with a <mark>marked</mark> word.</p>' },
    { label: "block-align", html: '<p style="text-align:center;">centred paragraph</p>' },
    { label: "rte-classes",
      html: '<p><span class="fontColorRed">colour by class</span>, ' +
        '<span class="fontSizeLarge">size by class</span>, ' +
        '<span class="highlightColorYellow">highlight by class</span></p>' },
  ];
  const styleSection = { type: "style", zoneIndex: (sections.length + 1) * 1000, factors: [12] };
  sections.push(styleSection);
  const styleControls = STYLE_SAMPLES.map((s, i) => ({
    label: s.label,
    html: s.html,
    cd: textControlData("00000000-0000-0000-0002-" + String(i + 1).padStart(12, "0"),
      styleSection.zoneIndex, sections.length, i + 1),
  }));

  // 3c. M3 section probe. The styling the canvas model carries per section
  //     lives on every control IN the section, not on a section object:
  //     emphasis.zoneEmphasis (0 none, 1 neutral, 2 soft, 3 strong),
  //     zoneGroupMetadata (collapsible sections), position.sectionFactor 0
  //     (full width) and position.layoutIndex 2 (the vertical section,
  //     with position.isLayoutReflowOnTop). Those are the PnP shapes. Each
  //     variant gets a section of its own holding one web-part control
  //     (the first placeable part), so a normalisation can be pinned to one
  //     key; an unknown key rides along in one emphasis block to show
  //     whether unknown keys are dropped. Theme/accent colour and section
  //     backgrounds are NOT probed: see `unmeasured` in the document.
  const SECTION_SAMPLES = [
    { label: "emphasis-soft", emphasis: { zoneEmphasis: 2 } },
    { label: "emphasis-unknown-key", emphasis: { zoneEmphasis: 3, formworkProbe: "unknown key" } },
    { label: "collapsible", emphasis: {}, zoneGroupMetadata: {
        type: 1, isExpanded: true, showDividerLine: false, iconAlignment: "left",
        headingLevel: 2, displayName: "Formwork collapsible probe" } },
    { label: "full-width", emphasis: {}, sectionFactor: 0 },
    { label: "vertical", emphasis: {}, layoutIndex: 2, isLayoutReflowOnTop: false },
  ];
  const sectionControls = SECTION_SAMPLES.map((s, i) => {
    const factor = s.sectionFactor === undefined ? 12 : s.sectionFactor;
    const section = { type: "m3-" + s.label, zoneIndex: (sections.length + 1) * 1000, factors: [factor] };
    sections.push(section);
    const position = {
      zoneIndex: section.zoneIndex,
      sectionIndex: sections.length,
      controlIndex: 1,
      zoneId: null,
      sectionFactor: factor,
      layoutIndex: s.layoutIndex === undefined ? 1 : s.layoutIndex,
    };
    if (s.isLayoutReflowOnTop !== undefined) position.isLayoutReflowOnTop = s.isLayoutReflowOnTop;
    const cd = {
      controlType: 3,
      id: "00000000-0000-0000-0003-" + String(i + 1).padStart(12, "0"),
      position: position,
      webPartId: placeable[0].Id,
      emphasis: s.emphasis,
    };
    if (s.zoneGroupMetadata) cd.zoneGroupMetadata = s.zoneGroupMetadata;
    return { label: s.label, cd: cd };
  });

  // The manifest a placeable component embeds, its preconfigured entries
  // and the placeable part behind an alias. A part missing from this site
  // is a finding (recorded under `skipped`), never a throw.
  const manifestOf = (comp) => JSON.parse(comp.Manifest || "{}");
  const entriesOf = (comp) => manifestOf(comp).preconfiguredEntries || [];
  const byAlias = (alias) => placeable.find(c => manifestOf(c).alias === alias) || null;
  const hasOwn = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  const padId = (range, n) => "00000000-0000-0000-" + range + "-" + String(n).padStart(12, "0");
  const controlAt = (id, section, sectionIndex, col, controlIndex, webPartId) => ({
    controlType: 3,
    id: id,
    position: {
      zoneIndex: section.zoneIndex,
      sectionIndex: sectionIndex,
      controlIndex: controlIndex,
      zoneId: null,
      sectionFactor: section.factors[col - 1],
      layoutIndex: 1,
    },
    webPartId: webPartId,
    emphasis: {},
  });

  // 3e. M5 property probe: does a flat, visible property survive the item
  //     MERGE byte-for-byte? Six representative parts, each placed TWICE in
  //     a one-column section of its own: the manifest's first entry as-is
  //     ("default"), then the same with ONE top-level property changed
  //     ("modified"), the types spread across boolean, enum, free text with
  //     a ':' (the one rewrite measured on text, 2026-09-06) and a numeric
  //     string. Nothing nested: the shape question is whether a value at a
  //     path comes back equal, judged on the Python side
  //     (catalogue.PropertySample.value_round_tripped). The site's
  //     catalogue has no DocumentLibraryWebPart: "Document library" is the
  //     second preconfigured entry of ListWebPart (isDocumentLibrary true;
  //     tests/fixtures/discovery.styling.json, 2026-09-06), so the list
  //     part is the sixth here and the library entry is measured in 3g.
  //     finding: page.properties.<alias> rows (FINDINGS.md, 2026-09-06):
  //     12/12 byte-exact, the changed value read back equal.
  const PROPERTY_SAMPLES = [
    { component: "NewsWebPart", path: "showChrome", value: false },
    { component: "QuickLinksWebPart", path: "layoutId", value: "List" },
    { component: "ImageWebPart", path: "captionText", value: "Formwork caption probe: image" },
    { component: "EventsWebPart", path: "layout", value: "Compact" },
    { component: "HeroWebPart", path: "heroLayoutThreshold", value: "320" },
    { component: "ListWebPart", path: "isDocumentLibrary", value: true },
  ];
  const propertyControls = [];
  const propertySkipped = [];
  for (const sample of PROPERTY_SAMPLES) {
    const comp = byAlias(sample.component);
    if (!comp) {
      propertySkipped.push({ component: sample.component,
        why: "no placeable component (ComponentType 1) with that alias on this site" });
      continue;
    }
    const defaults = (entriesOf(comp)[0] || {}).properties || {};
    const section = { type: "m5-" + sample.component, zoneIndex: (sections.length + 1) * 1000, factors: [12] };
    sections.push(section);
    for (const variant of ["default", "modified"]) {
      const modified = variant === "modified";
      const oldValue = hasOwn(defaults, sample.path) ? defaults[sample.path] : null;
      propertyControls.push({
        component: sample.component,
        variant: variant,
        path: sample.path,
        defaultHasKey: hasOwn(defaults, sample.path),
        oldValue: oldValue,
        newValue: modified ? sample.value : oldValue,
        properties: modified ? { [sample.path]: sample.value } : {},
        cd: controlAt(padId("0005", propertyControls.length + 1), section, sections.length, 1,
          modified ? 2 : 1, comp.Id),
      });
    }
  }

  // 3f. M5 layout probe: the two-column factor orders and column order.
  //     Step 3 places 6/6 and 4/4/4 only; PnP's one-third layouts are 8/4
  //     and 4/8, and a control's column is only its sectionFactor plus its
  //     controlIndex within that column. Three sections on the first
  //     placeable part: 8/4 with one control in column 1, 4/8 with one in
  //     column 1, and 4/8 with a control in column 2 WRITTEN BEFORE one in
  //     column 1, so the readback shows whether SharePoint keeps the
  //     factors and the written order, or re-sorts by column. finding:
  //     page.layout.factors-8-4, factors-4-8 (FINDINGS.md, 2026-09-06):
  //     4/4 byte-exact, written order kept.
  const LAYOUT_SAMPLES = [
    { section: "split-8-4", factors: [8, 4], columns: [1] },
    { section: "split-4-8", factors: [4, 8], columns: [1] },
    { section: "split-4-8-two", factors: [4, 8], columns: [2, 1] },
  ];
  const layoutControls = [];
  for (const s of LAYOUT_SAMPLES) {
    const section = { type: "m5-" + s.section, zoneIndex: (sections.length + 1) * 1000, factors: s.factors };
    sections.push(section);
    const perCol = {};
    for (const col of s.columns) {
      perCol[col] = (perCol[col] || 0) + 1;
      layoutControls.push({
        label: s.section + "-col" + col,
        cd: controlAt(padId("0006", layoutControls.length + 1), section, sections.length, col,
          perCol[col], placeable[0].Id),
      });
    }
  }

  // 3g. M5 list-binding probe, the measurement M5 most needs: the shape of
  //     a part bound to a list. Each binding is the live CollabHome shape
  //     (tests/fixtures/collabhome.bundle.json, 2026-09-05) layered over
  //     the manifest entry's defaults, with the ids and URLs of the fixture
  //     containers from 2b. Measured library shape: properties
  //     selectedListId, selectedListUrl (server-relative root folder),
  //     webRelativeListUrl (no leading slash), webpartHeightKey 4,
  //     selectedViewId, hideCommandBar false; serverProcessedContent with
  //     searchablePlainTexts.listTitle. Measured Quick links shape
  //     (dataVersion "2.2"): an items[] entry whose url and title live in
  //     serverProcessedContent.links["items[0].sourceItem.url"] and
  //     .searchablePlainTexts["items[0].title"], links.baseUrl the web's
  //     absolute URL, componentDependencies.layoutComponentId the entry's
  //     own. The library part and the list part are the two preconfigured
  //     entries of ListWebPart (isDocumentLibrary true / false); each is
  //     bound to BOTH containers, and Quick links points one item at each
  //     container's default view, so a cross-type binding (a library part
  //     on a custom list) is measured next to the matching one.
  const listBinding = (probe) => ({
    properties: {
      selectedListId: probe.id,
      selectedListUrl: probe.serverRelativeUrl,
      webRelativeListUrl: probe.webRelativeUrl,
      webpartHeightKey: 4,
      selectedViewId: probe.defaultViewId,
      hideCommandBar: false,
    },
    spc: { htmlStrings: {}, searchablePlainTexts: { listTitle: probe.title }, imageSources: {}, links: {} },
  });
  const quickLinksBinding = (probe, comp) => ({
    dataVersion: "2.2",
    properties: {
      items: [{ id: 1, description: null, altText: "", thumbnailType: 3,
        sourceItem: { itemType: 2, fileExtension: "", progId: "" } }],
    },
    spc: {
      htmlStrings: {},
      searchablePlainTexts: { title: "Quick links", "items[0].title": probe.title },
      imageSources: {},
      links: { baseUrl: location.origin + webRoot,
        "items[0].sourceItem.url": location.origin + probe.defaultViewUrl },
      componentDependencies: {
        layoutComponentId: ((entriesOf(comp)[0] || {}).properties || {}).layoutComponentId || "" },
    },
  });
  const BINDING_SAMPLES = [
    { label: "library-part-to-library", component: "ListWebPart", library: true, target: "library" },
    { label: "list-part-to-library", component: "ListWebPart", library: false, target: "library" },
    { label: "quick-links-to-library", component: "QuickLinksWebPart", target: "library" },
    { label: "library-part-to-list", component: "ListWebPart", library: true, target: "list" },
    { label: "list-part-to-list", component: "ListWebPart", library: false, target: "list" },
    { label: "quick-links-to-list", component: "QuickLinksWebPart", target: "list" },
  ];
  const bindingSection = { type: "m5-bindings", zoneIndex: (sections.length + 1) * 1000, factors: [12] };
  sections.push(bindingSection);
  const bindingControls = [];
  const bindingSkipped = [];
  for (const s of BINDING_SAMPLES) {
    const comp = byAlias(s.component);
    const probe = probeLists.find(p => p.key === s.target);
    const entry = s.library === undefined ? 0
      : entriesOf(comp || {}).findIndex(e => Boolean((e.properties || {}).isDocumentLibrary) === s.library);
    if (!comp) {
      bindingSkipped.push({ label: s.label, why: "no placeable component with alias " + s.component });
    } else if (entry < 0) {
      bindingSkipped.push({ label: s.label,
        why: s.component + " has no preconfigured entry with isDocumentLibrary " + s.library });
    } else if (!probe.serverRelativeUrl) {
      bindingSkipped.push({ label: s.label,
        why: "fixture " + s.target + " not available: " + (probe.reason || "not described") });
    } else {
      const binding = s.library === undefined ? quickLinksBinding(probe, comp) : listBinding(probe);
      bindingControls.push({
        label: s.label,
        component: s.component,
        entry: entry,
        target: probe,
        binding: binding,
        cd: controlAt(padId("0007", bindingControls.length + 1), bindingSection, sections.length, 1,
          bindingControls.length + 1, comp.Id),
      });
    }
  }

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/{/g, "&#123;").replace(/}/g, "&#125;")
      .replace(/:/g, "&#58;");
  }
  // The webpartdata of a control: the manifest's preconfigured entry
  // (opts.entry, default the first) with opts.properties layered over the
  // entry's defaults, opts.spc as serverProcessedContent and opts.dataVersion
  // over the entry's. Without opts this is exactly the M1 shape, so the
  // step-3 and 3c blocks are byte-stable against the M5 probes.
  function webPartData(cd, opts) {
    const o = opts || {};
    const comp = placeable.find(c => c.Id === cd.webPartId);
    const manifest = manifestOf(comp);
    const entry = (manifest.preconfiguredEntries || [])[o.entry || 0] || {};
    return {
      id: comp.Id,
      instanceId: cd.id,
      title: (entry.title || {}).default || manifest.alias || comp.Id,
      description: (entry.description || {}).default || "",
      serverProcessedContent: o.spc || {},
      dataVersion: o.dataVersion || entry.dataVersion || "1.0",
      properties: Object.assign({}, entry.properties || {}, o.properties || {}),
    };
  }
  function webPartBlock(cd, opts) {
    const wpd = webPartData(cd, opts);
    return '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0"' +
      ' data-sp-controldata="' + esc(JSON.stringify(cd)) + '">' +
      '<div data-sp-webpartdata="' + esc(JSON.stringify(wpd)) + '"></div></div>';
  }
  // The control data is attribute-escaped exactly like a web part's; the
  // HTML itself is inner content and goes in as written.
  const textBlock = (cd, html) =>
    '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0"' +
    ' data-sp-controldata="' + esc(JSON.stringify(cd)) + '">' +
    '<div data-sp-rte="">' + html + '</div></div>';

  let canvas = "<div>";
  for (const cd of controls) {
    canvas += webPartBlock(cd);
  }
  const textRequested = [];
  for (const t of textControls) {
    const block = textBlock(t.cd, t.html);
    canvas += block;
    textRequested.push({ id: t.cd.id, html: t.html, controlData: t.cd, canvas: block });
  }
  const styleRequested = [];
  for (const s of styleControls) {
    const block = textBlock(s.cd, s.html);
    canvas += block;
    styleRequested.push({ label: s.label, id: s.cd.id, html: s.html, controlData: s.cd, canvas: block });
  }
  const sectionRequested = [];
  for (const s of sectionControls) {
    const block = webPartBlock(s.cd);
    canvas += block;
    sectionRequested.push({ label: s.label, id: s.cd.id, controlData: s.cd, canvas: block });
  }
  const propertyRequested = [];
  for (const p of propertyControls) {
    const block = webPartBlock(p.cd, { properties: p.properties });
    canvas += block;
    propertyRequested.push({ component: p.component, id: p.cd.id, variant: p.variant,
      propertyPath: p.path, defaultHasKey: p.defaultHasKey, oldValue: p.oldValue, newValue: p.newValue,
      controlData: p.cd, canvas: block });
  }
  const layoutRequested = [];
  for (const l of layoutControls) {
    const block = webPartBlock(l.cd);
    canvas += block;
    layoutRequested.push({ label: l.label, id: l.cd.id, controlData: l.cd, canvas: block });
  }
  const bindingTarget = (probe) => ({
    key: probe.key, title: probe.title, listId: probe.id, serverRelativeUrl: probe.serverRelativeUrl,
    webRelativeUrl: probe.webRelativeUrl, defaultViewId: probe.defaultViewId,
    defaultViewUrl: probe.defaultViewUrl,
  });
  const bindingRequested = [];
  for (const b of bindingControls) {
    const opts = { entry: b.entry, properties: b.binding.properties, spc: b.binding.spc,
      dataVersion: b.binding.dataVersion };
    const block = webPartBlock(b.cd, opts);
    canvas += block;
    bindingRequested.push({ label: b.label, component: b.component, entry: b.entry, id: b.cd.id,
      target: bindingTarget(b.target), controlData: b.cd, webPartData: webPartData(b.cd, opts),
      canvas: block });
  }
  canvas += "</div>";

  // 3d. Create the scratch page, then write the discovery canvas onto it.
  const scratch = await createSitePage(SCRATCH);
  const scratchId = scratch.id;
  await scratch.setFields({ Title: SCRATCH });

  const itemRes = await fetchWithRetry(
    PAGES + "/items(" + scratchId + ")",
    { headers: { Accept: VERBOSE } }
  );
  if (!itemRes.ok) throw await failed("scratch read", itemRes);
  const etag = (await itemRes.json()).d.__metadata.etag;
  const saveRes = await fetchWithRetry(
    PAGES + "/items(" + scratchId + ")",
    {
      method: "POST",
      headers: {
        Accept: VERBOSE,
        "Content-Type": "application/json;odata=verbose",
        "X-RequestDigest": await getDigest(),
        "X-HTTP-Method": "MERGE",
        "If-Match": etag,
      },
      body: JSON.stringify({
        __metadata: { type: "SP.Data.SitePagesItem" },
        CanvasContent1: canvas,
      }),
    }
  );
  if (!saveRes.ok) throw await failed("scratch save", saveRes);

  // 4. Read back the persisted canvas.
  const readRes = await fetchWithRetry(
    PAGES + "/items(" + scratchId + ")?$select=CanvasContent1",
    { headers: { Accept: VERBOSE } }
  );
  if (!readRes.ok) throw await failed("scratch read back", readRes);
  const stored = (await readRes.json()).d.CanvasContent1 || "";

  // 4a. The persisted controls, verbatim. Split at control boundaries (the
  //     rule canvas.py parses by), decode each block's controldata through
  //     the browser's own HTML parser. The raw block is kept, not a
  //     re-serialisation: the bytes are the evidence.
  const CONTROL_OPEN = '<div data-sp-canvascontrol=""';
  // The last block would otherwise carry everything to the end of the
  // canvas — including the page wrapper's own "</div>", which would make
  // persisted != requested forever (review P2-2, 2026-09-06). The canvas
  // is exactly "<div>" + blocks + "</div>", so strip that one wrapper close.
  const wrapperClose = "</div>";
  const attributeJson = (block, attr) => {
    try {
      const el = new DOMParser().parseFromString(block, "text/html")
        .querySelector("[" + attr + "]");
      return JSON.parse(el.getAttribute(attr));
    } catch {
      return null;
    }
  };
  const controlDataOf = (block) => attributeJson(block, "data-sp-controldata");
  const webPartDataOf = (block) => attributeJson(block, "data-sp-webpartdata");
  // Every control of a stored canvas, in order, as {id, controlData, canvas}.
  const persistedControls = (storedCanvas) => {
    const tail = storedCanvas.endsWith(wrapperClose)
      ? storedCanvas.slice(0, -wrapperClose.length) : storedCanvas;
    return tail.split(CONTROL_OPEN).slice(1).map(b => CONTROL_OPEN + b).map(block => {
      const cd = controlDataOf(block);
      return { id: cd ? cd.id : null, controlData: cd, canvas: block };
    });
  };
  // The persisted blocks of one sample set, matched by control id and
  // labelled from the requested side.
  const persistedFor = (blocks, requested) => {
    const labels = new Map(requested.map(r => [r.id, r.label]));
    return blocks.filter(b => labels.has(b.id)).map(b => (
      { label: labels.get(b.id), id: b.id, controlData: b.controlData, canvas: b.canvas }));
  };
  const storedBlocks = persistedControls(stored);
  const textIds = new Set(textRequested.map(t => t.id));
  const textPersisted = [];
  for (const { controlData: cd, canvas: block } of storedBlocks) {
    if (cd && cd.controlType === 4 && textIds.has(cd.id)) {
      textPersisted.push({ id: cd.id, controlData: cd, canvas: block });
    }
  }
  const stylePersisted = persistedFor(storedBlocks, styleRequested);
  const sectionPersisted = persistedFor(storedBlocks, sectionRequested);
  // 4a'. The M5 probes read back the same way; the property and binding
  //      rows also decode the stored webpartdata, so the Python side can
  //      judge a value at a path without re-parsing the block. `present`
  //      tells a stored null apart from a dropped key.
  const propertyPersisted = [];
  for (const p of propertyRequested) {
    const kept = storedBlocks.find(b => b.id === p.id);
    if (!kept) continue;
    const wpd = webPartDataOf(kept.canvas);
    const props = (wpd && wpd.properties) || {};
    const present = hasOwn(props, p.propertyPath);
    propertyPersisted.push({ id: p.id, propertyPath: p.propertyPath, present: present,
      storedValue: present ? props[p.propertyPath] : null, controlData: kept.controlData,
      webPartData: wpd, canvas: kept.canvas });
  }
  const layoutPersisted = persistedFor(storedBlocks, layoutRequested);
  const bindingPersisted = persistedFor(storedBlocks, bindingRequested).map(b => ({
    label: b.label, id: b.id, controlData: b.controlData, webPartData: webPartDataOf(b.canvas),
    canvas: b.canvas }));

  // 4b. The other write path. The MERGE above stores CanvasContent1 as sent
  //     (measured 2026-09-06: byte-identical for web parts, ':' rewritten in
  //     text inner HTML). SavePageAsDraft on the sitepages API is the page
  //     model's own save; whether IT re-serialises the canvas, normalises
  //     the section keys or drops what it does not know is the measurement
  //     here. The same canvas goes in with one extra text control appended
  //     as a marker, so the readback shows whether the body was applied at
  //     all (bodyApplied) before anything is concluded from it. Non-fatal:
  //     a refusal is a finding too, and the evidence above still downloads.
  const MARKER_ID = "00000000-0000-0000-0004-000000000001";
  const markerBlock = textBlock(
    textControlData(MARKER_ID, styleSection.zoneIndex, sections.indexOf(styleSection) + 1,
      styleControls.length + 1),
    "<p>Formwork page-model save marker</p>");
  const canvasForPageModel = canvas.slice(0, -wrapperClose.length) + markerBlock + wrapperClose;
  const probeIds = new Set([...textRequested, ...styleRequested, ...sectionRequested].map(r => r.id));
  const pageModelSave = {
    attempted: true,
    ok: false,
    status: 0,
    reason: "",
    markerId: MARKER_ID,
    bodyApplied: null,
    storedCanvasChars: 0,
    storedControlCount: 0,
    probeControlsUnchanged: null,
    controls: [],
    storedCanvas: null,
  };
  try {
    const draftRes = await fetchWithRetry(
      API("sitepages/pages(" + scratchId + ")/SavePageAsDraft"),
      {
        method: "POST",
        headers: { Accept: VERBOSE, "Content-Type": VERBOSE, "X-RequestDigest": await getDigest() },
        body: JSON.stringify({
          __metadata: { type: "SP.Publishing.SitePage" },
          Title: SCRATCH,
          CanvasContent1: canvasForPageModel,
        }),
      }
    );
    pageModelSave.status = draftRes.status;
    if (!draftRes.ok) {
      pageModelSave.reason = spError(await draftRes.text().catch((e) => "body unreadable: " + bounded(e)));
    } else {
      const againRes = await fetchWithRetry(
        PAGES + "/items(" + scratchId + ")?$select=CanvasContent1",
        { headers: { Accept: VERBOSE } }
      );
      if (!againRes.ok) throw await failed("read back after SavePageAsDraft", againRes);
      const storedAgain = (await againRes.json()).d.CanvasContent1 || "";
      const before = new Map(storedBlocks.map(b => [b.id, b.canvas]));
      const after = persistedControls(storedAgain);
      pageModelSave.ok = true;
      pageModelSave.bodyApplied = after.some(b => b.id === MARKER_ID);
      pageModelSave.storedCanvasChars = storedAgain.length;
      pageModelSave.storedControlCount = after.length;
      pageModelSave.probeControlsUnchanged = [...probeIds].every(id => {
        const kept = after.find(b => b.id === id);
        return Boolean(kept) && kept.canvas === before.get(id);
      });
      pageModelSave.controls = after.filter(b => probeIds.has(b.id) || b.id === MARKER_ID);
      pageModelSave.storedCanvas = storedAgain;
    }
  } catch (err) {
    pageModelSave.reason = bounded(err);
  }

  // 5. Recycle the scratch page (undo the write; evidence is downloaded).
  const recycleRes = await fetchWithRetry(
    PAGES + "/items(" + scratchId + ")/recycle",
    { method: "POST", headers: { Accept: VERBOSE, "X-RequestDigest": await getDigest() } }
  );

  // 5a. Recycle the M5 fixture lists (2b), after the page that bound to
  //     them. Each outcome is recorded on its fixture row; a refusal is a
  //     finding for the operator (the list is left in place), not a throw.
  for (const probe of probeLists) {
    if (!probe.id) continue;
    try {
      const res = await fetchWithRetry(
        API("web/lists(guid'" + probe.id + "')/recycle"),
        { method: "POST", headers: { Accept: VERBOSE, "X-RequestDigest": await getDigest() } }
      );
      probe.recycled = res.ok;
      probe.recycleStatus = res.status;
      if (!res.ok) {
        probe.recycleReason = spError(await res.text().catch((e) => "body unreadable: " + bounded(e)));
      }
    } catch (err) {
      probe.recycled = false;
      probe.recycleReason = bounded(err);
    }
  }

  // 5b. The section-emphasis mechanism (page.emphasis.section-savepage).
  //     The item MERGE keeps zoneEmphasis on a control (3c), but a section
  //     is only established by the page model: SavePage with a JSON-array
  //     CanvasContent1 whose controls carry position.zoneId, and a control
  //     item-merged into that zone afterwards reads back with the zone's
  //     emphasis (tests/fixtures/savepage-section-emphasis.json and
  //     discovery.styling.json styling.sectionEmphasisMechanism, 2026-09-06).
  //     Re-derived on a second scratch page after the legs' own recycle, so
  //     the readback above is exactly discover's. Non-fatal: a refusal is
  //     the finding, recorded with the server's reason.
  const SAVEPAGE_IDS = [
    "00000000-0000-0000-0008-000000000001",
    "00000000-0000-0000-0008-000000000002",
    "00000000-0000-0000-0008-000000000003",
  ];
  const sectionEmphasis = {
    attempted: true, ok: false, status: 0, reason: "", pageId: null, zoneIds: [], survived: [],
    mergedOk: false, mergedStatus: 0, mergedEmphasis: null, survivedAfterMerge: [],
    recycled: null, summary: "",
  };
  const savePageControl = (id, zoneIndex, zoneId, controlIndex, zoneEmphasis) => ({
    controlType: 3,
    id: id,
    position: { zoneIndex: zoneIndex, sectionIndex: 1, controlIndex: controlIndex,
      zoneId: zoneId, sectionFactor: 12, layoutIndex: 1 },
    webPartId: placeable[0].Id,
    emphasis: { zoneEmphasis: zoneEmphasis },
  });
  // The zoneEmphasis a stored control carries, or "none" when the control
  // or its emphasis is missing: the readback the recorded result quotes.
  const emphasisOf = (blocks, id) => {
    const kept = blocks.find(b => b.id === id);
    const emphasis = kept && kept.controlData && kept.controlData.emphasis;
    return emphasis && emphasis.zoneEmphasis !== undefined ? emphasis.zoneEmphasis : "none";
  };
  const readCanvas = async (pageId, what) => {
    const res = await fetchWithRetry(
      PAGES + "/items(" + pageId + ")?$select=CanvasContent1",
      { headers: { Accept: VERBOSE } }
    );
    if (!res.ok) throw await failed(what, res);
    return (await res.json()).d.CanvasContent1 || "";
  };
  const mergeCanvas = async (pageId, canvasHtml) => {
    const itemRes = await fetchWithRetry(
      PAGES + "/items(" + pageId + ")",
      { headers: { Accept: VERBOSE } }
    );
    if (!itemRes.ok) throw await failed("SavePage page read", itemRes);
    const etag = (await itemRes.json()).d.__metadata.etag;
    return fetchWithRetry(
      PAGES + "/items(" + pageId + ")",
      {
        method: "POST",
        headers: { Accept: VERBOSE, "Content-Type": VERBOSE, "X-RequestDigest": await getDigest(),
          "X-HTTP-Method": "MERGE", "If-Match": etag },
        body: JSON.stringify({
          __metadata: { type: "SP.Data.SitePagesItem" },
          CanvasContent1: canvasHtml,
        }),
      }
    );
  };
  try {
    const zoneIds = [crypto.randomUUID(), crypto.randomUUID()];
    sectionEmphasis.zoneIds = zoneIds;
    // Two one-column sections, soft (2) and strong (3), in the body shape the
    // fixture recorded: the control data plus the embedded webPartData.
    const established = [
      savePageControl(SAVEPAGE_IDS[0], 1, zoneIds[0], 1, 2),
      savePageControl(SAVEPAGE_IDS[1], 2, zoneIds[1], 1, 3),
    ].map(cd => ({
      position: cd.position, emphasis: cd.emphasis, id: cd.id, controlType: 3,
      isFromSectionTemplate: false, addedFromPersistedData: false,
      webPartData: webPartData(cd), webPartId: cd.webPartId,
    }));
    const savePage = await createSitePage(SCRATCH + "-savepage");
    sectionEmphasis.pageId = savePage.id;
    await savePage.setFields({ Title: SCRATCH + "-savepage" });
    const savePageRes = await fetchWithRetry(
      API("sitepages/pages(" + savePage.id + ")/SavePage"),
      {
        method: "POST",
        headers: { Accept: VERBOSE, "Content-Type": VERBOSE, "X-RequestDigest": await getDigest() },
        body: JSON.stringify({
          __metadata: { type: "SP.Publishing.SitePage" },
          CanvasContent1: JSON.stringify(established),
          LayoutWebpartsContent: "[]",
          BannerImageUrl: "/_layouts/15/images/sitepagethumbnail.png",
        }),
      }
    );
    sectionEmphasis.status = savePageRes.status;
    if (!savePageRes.ok) {
      sectionEmphasis.reason =
        spError(await savePageRes.text().catch((e) => "body unreadable: " + bounded(e)));
    } else {
      sectionEmphasis.ok = true;
      const storedSave = await readCanvas(savePage.id, "read back after SavePage");
      const afterSave = persistedControls(storedSave);
      sectionEmphasis.survived = SAVEPAGE_IDS.slice(0, 2).map(id => emphasisOf(afterSave, id));
      // A third control, item-merged into the second zone with its emphasis:
      // the apply path, once SavePage has established the zone.
      const merged = savePageControl(SAVEPAGE_IDS[2], 2, zoneIds[1], 2, 3);
      const mergedCanvas = storedSave.endsWith(wrapperClose)
        ? storedSave.slice(0, -wrapperClose.length) + webPartBlock(merged) + wrapperClose
        : storedSave + webPartBlock(merged);
      const mergeRes = await mergeCanvas(savePage.id, mergedCanvas);
      sectionEmphasis.mergedStatus = mergeRes.status;
      if (!mergeRes.ok) {
        sectionEmphasis.reason =
          spError(await mergeRes.text().catch((e) => "body unreadable: " + bounded(e)));
      } else {
        sectionEmphasis.mergedOk = true;
        const afterMerge = persistedControls(await readCanvas(savePage.id, "read back after the merge"));
        sectionEmphasis.mergedEmphasis = emphasisOf(afterMerge, SAVEPAGE_IDS[2]);
        sectionEmphasis.survivedAfterMerge = SAVEPAGE_IDS.slice(0, 2).map(id => emphasisOf(afterMerge, id));
      }
    }
  } catch (err) {
    sectionEmphasis.reason = bounded(err);
  }
  // The summary is the row's result grammar: what FINDINGS.md quotes.
  const survivedText = "zoneEmphasis survived " + sectionEmphasis.survived.join(", ");
  if (!sectionEmphasis.ok) {
    sectionEmphasis.summary = sectionEmphasis.status
      ? "SavePage refused " + sectionEmphasis.status + ": " +
        (sectionEmphasis.reason || spError(sectionEmphasis.reason || ""))
      : "failed: " + (sectionEmphasis.reason || "(no reason captured)");
  } else if (!sectionEmphasis.mergedOk) {
    sectionEmphasis.summary = "SavePage " + sectionEmphasis.status + "; " + survivedText + "; merge " +
      (sectionEmphasis.mergedStatus ? "refused " + sectionEmphasis.mergedStatus + ": " : "failed: ") +
      sectionEmphasis.reason;
  } else {
    const afterMerge = sectionEmphasis.survivedAfterMerge.join(", ");
    sectionEmphasis.summary = "SavePage " + sectionEmphasis.status + "; " + survivedText +
      "; merged control " + sectionEmphasis.mergedEmphasis +
      (afterMerge === sectionEmphasis.survived.join(", ") ? "" : "; after the merge " + afterMerge);
  }

  // 5c. Recycle the SavePage scratch page. Non-fatal, recorded on the row.
  if (sectionEmphasis.pageId !== null) {
    try {
      const res = await fetchWithRetry(
        PAGES + "/items(" + sectionEmphasis.pageId + ")/recycle",
        { method: "POST", headers: { Accept: VERBOSE, "X-RequestDigest": await getDigest() } }
      );
      sectionEmphasis.recycled = res.ok;
      if (!res.ok) {
        sectionEmphasis.reason += " | recycle " + res.status + " " +
          spError(await res.text().catch((e) => "body unreadable: " + bounded(e)));
      }
    } catch (err) {
      sectionEmphasis.recycled = false;
      sectionEmphasis.reason += " | recycle failed: " + bounded(err);
    }
  }

  // 5d. Page state and identity (M7, 2026-09-07). Create is only birth:
  //     the prelude's createSitePage sends PageLayoutType alone and the
  //     apply path sets everything else by item MERGE. Each sample below
  //     creates one scratch page with one thing asked of it and records,
  //     keyed by page id, what was requested and what came back from three
  //     reads: the page entity (sitepages/pages), the list item (the fields
  //     setFields writes) and the item's HasUniqueRoleAssignments. A
  //     refused create is a sample with ok:false and the server's reason,
  //     never a throw; every page that got an id is recycled in 5e. What
  //     the lane does not measure is named under pageStateUnmeasured.
  const STAMP = Date.now();
  const PAGE_STATE = "formwork-pagestate-" + STAMP;
  const PAGE_FIELDS = ["Id", "Title", "FileName", "Url", "AbsoluteUrl", "UniqueId",
    "PageLayoutType", "PromotedState", "Description", "BannerImageUrl", "BannerThumbnailUrl",
    "Version", "VersionInfo", "IsPageCheckedOutToCurrentUser", "FirstPublished"];
  const ITEM_FIELDS = ["Id", "Title", "FileLeafRef", "FileRef", "PageLayoutType", "PromotedState",
    "Description", "BannerImageUrl", "OData__UIVersionString", "CheckoutUserId",
    "FirstPublishedDate", "OData__ModerationStatus"];
  const BANNER_URL = location.origin + "/_layouts/15/images/sitepagethumbnail.png";
  const pageStateSamples = [];
  let pageStateKeys = null;
  // The fields asked for, and the names that were not in the entity: a
  // missing name is a finding about the entity, not a failed read.
  const pick = (entity, keys) => {
    const fields = {};
    const missing = [];
    for (const key of keys) {
      if (entity && hasOwn(entity, key)) fields[key] = entity[key]; else missing.push(key);
    }
    return { fields: fields, missing: missing };
  };
  // A read that must not fail the sample: {ok, status, reason, d}.
  async function tryGet(url) {
    try {
      const res = await fetchWithRetry(url, { headers: { Accept: VERBOSE } });
      if (!res.ok) {
        return { ok: false, status: res.status, d: null,
          reason: spError(await res.text().catch((e) => "body unreadable: " + bounded(e))) };
      }
      return { ok: true, status: res.status, reason: "", d: (await res.json()).d };
    } catch (err) {
      return { ok: false, status: 0, reason: bounded(err), d: null };
    }
  }
  // The three reads. The entity and the item are the measurement and throw
  // into the sample; the permission read is recorded either way. The first
  // page read also lists every key the two entities carried, so a banner
  // or state key this lane did not ask for is visible in the document.
  async function readPageState(id) {
    const page = await getJson(API("sitepages/pages(" + id + ")"));
    const item = await getJson(PAGES + "/items(" + id + ")");
    if (!pageStateKeys) {
      pageStateKeys = {
        page: Object.keys(page.d).filter(k => !k.startsWith("__")),
        item: Object.keys(item.d).filter(k => !k.startsWith("__")),
      };
    }
    const perms = await tryGet(PAGES + "/items(" + id + ")?$select=Id,HasUniqueRoleAssignments");
    return {
      page: pick(page.d, PAGE_FIELDS),
      item: pick(item.d, ITEM_FIELDS),
      permissions: { ok: perms.ok, status: perms.status, reason: perms.reason,
        hasUniqueRoleAssignments: perms.d ? perms.d.HasUniqueRoleAssignments : null },
    };
  }
  // The create the prelude makes, with the fields under test beside
  // PageLayoutType. The entity the POST answers with is the first
  // persisted view (persisted.created); the reads after it are the rest.
  async function createPageState(sample, fields) {
    const res = await fetchWithRetry(API("sitepages/pages"), {
      method: "POST",
      headers: { Accept: VERBOSE, "Content-Type": VERBOSE, "X-RequestDigest": await getDigest() },
      body: JSON.stringify({ __metadata: { type: "SP.Publishing.SitePage" }, ...fields }),
    });
    sample.status = res.status;
    if (!res.ok) throw await failed("page-state create " + sample.label, res);
    const page = (await res.json()).d;
    sample.pageId = page.Id;
    sample.persisted.created = pick(page, PAGE_FIELDS);
    return page.Id;
  }
  // The item MERGE apply makes (prelude setFields: the real etag,
  // SP.Data.SitePagesItem), recorded rather than thrown so a refused field
  // is a finding on the sample.
  async function mergeItem(id, fields) {
    const outcome = { ok: false, status: 0, reason: "" };
    try {
      const item = await getJson(PAGES + "/items(" + id + ")");
      const res = await fetchWithRetry(PAGES + "/items(" + id + ")", {
        method: "POST",
        headers: {
          Accept: VERBOSE, "Content-Type": VERBOSE, "X-RequestDigest": await getDigest(),
          "X-HTTP-Method": "MERGE", "If-Match": item.d.__metadata.etag,
        },
        body: JSON.stringify({ __metadata: { type: "SP.Data.SitePagesItem" }, ...fields }),
      });
      outcome.status = res.status;
      outcome.ok = res.ok;
      if (!res.ok) {
        outcome.reason = spError(await res.text().catch((e) => "body unreadable: " + bounded(e)));
      }
    } catch (err) {
      outcome.reason = bounded(err);
    }
    return outcome;
  }
  // A page-model action on sitepages/pages(<id>): checkoutpage, publish,
  // SavePageAsDraft. Non-fatal, recorded the same way.
  async function pageAction(id, action, body) {
    const outcome = { action: action, ok: false, status: 0, reason: "" };
    try {
      const res = await fetchWithRetry(API("sitepages/pages(" + id + ")/" + action), {
        method: "POST",
        headers: { Accept: VERBOSE, "Content-Type": VERBOSE, "X-RequestDigest": await getDigest() },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      outcome.status = res.status;
      outcome.ok = res.ok;
      if (!res.ok) {
        outcome.reason = spError(await res.text().catch((e) => "body unreadable: " + bounded(e)));
      }
    } catch (err) {
      outcome.reason = bounded(err);
    }
    return outcome;
  }
  // One sample per scratch page: the requested block is what the steps
  // send, the persisted block what each step read back, by step name.
  async function pageStateSample(label, topics, requested, run) {
    const sample = { label: label, topics: topics, pageId: null, requested: requested,
      persisted: {}, ok: false, status: 0, reason: "", recycled: null, recycleStatus: 0,
      recycleReason: "" };
    pageStateSamples.push(sample);
    try {
      await run(sample);
      sample.ok = true;
    } catch (err) {
      sample.reason = bounded(err);
    }
    return sample;
  }

  // (1) fileName, explicit, with a Title: the FileName the POST asked for
  //     against the entity's FileName and Url and the item's FileLeafRef
  //     and FileRef. The same page then carries the description and
  //     banner probes: the item MERGE of Description and BannerImageUrl
  //     (a URL field on the item, so SP.FieldUrlValue), read back; then
  //     the page model's own BannerImageUrl through SavePageAsDraft with
  //     no canvas in the body (page.page-model.draft-refuses-html was
  //     about an HTML CanvasContent1; a body without one is a different
  //     question), read back again.
  await pageStateSample("filename-explicit", ["fileName", "description", "bannerImageUrl"], {
    create: { Title: PAGE_STATE + " explicit", FileName: PAGE_STATE + "-explicit.aspx",
      PageLayoutType: "Home" },
    merge: { Description: "Formwork page-state probe " + STAMP,
      BannerImageUrl: { __metadata: { type: "SP.FieldUrlValue" }, Url: BANNER_URL, Description: "" } },
    pageModel: { BannerImageUrl: BANNER_URL },
  }, async (sample) => {
    const id = await createPageState(sample, sample.requested.create);
    sample.persisted.read = await readPageState(id);
    sample.persisted.merge = await mergeItem(id, sample.requested.merge);
    sample.persisted.afterMerge = await readPageState(id);
    sample.persisted.pageModel = await pageAction(id, "SavePageAsDraft",
      { __metadata: { type: "SP.Publishing.SitePage" }, ...sample.requested.pageModel });
    sample.persisted.afterPageModel = await readPageState(id);
  });

  // (2) fileName needing normalisation: spaces and upper case, as an
  //     editor would type a title. Refused, slugified or kept: recorded.
  //     Its read is also the cleanest permission-inheritance measurement
  //     (a page with nothing but its create behind it).
  await pageStateSample("filename-normalised", ["fileName", "permissionInheritance"], {
    create: { FileName: "Formwork PageState " + STAMP + " Needs Slug.aspx", PageLayoutType: "Home" },
  }, async (sample) => {
    const id = await createPageState(sample, sample.requested.create);
    sample.persisted.read = await readPageState(id);
  });

  // (3) A layout beyond Home: PageLayoutType "Article" at create.
  await pageStateSample("layout-article", ["layout"], {
    create: { PageLayoutType: "Article" },
  }, async (sample) => {
    const id = await createPageState(sample, sample.requested.create);
    sample.persisted.read = await readPageState(id);
  });

  // (4) A news page at birth: PromotedState 1 beside the Article layout.
  await pageStateSample("promoted-at-create", ["promotedState", "layout"], {
    create: { PageLayoutType: "Article", PromotedState: 1 },
  }, async (sample) => {
    const id = await createPageState(sample, sample.requested.create);
    sample.persisted.read = await readPageState(id);
  });

  // (5) The flip apply makes today: a Home page, then PromotedState 1 by
  //     item MERGE (setFields), read back.
  await pageStateSample("promoted-merge-flip", ["promotedState"], {
    create: { PageLayoutType: "Home" },
    merge: { PromotedState: 1 },
  }, async (sample) => {
    const id = await createPageState(sample, sample.requested.create);
    sample.persisted.read = await readPageState(id);
    sample.persisted.merge = await mergeItem(id, sample.requested.merge);
    sample.persisted.afterMerge = await readPageState(id);
  });

  // (6) Publish state: a fresh page's version string, checkout user and
  //     moderation status; then checkoutpage and publish through the page
  //     model, each read back.
  await pageStateSample("publish-state", ["publishState"], {
    create: { PageLayoutType: "Home" },
    actions: ["checkoutpage", "publish"],
  }, async (sample) => {
    const id = await createPageState(sample, sample.requested.create);
    sample.persisted.fresh = await readPageState(id);
    sample.persisted.checkout = await pageAction(id, "checkoutpage");
    sample.persisted.afterCheckout = await readPageState(id);
    sample.persisted.publish = await pageAction(id, "publish");
    sample.persisted.afterPublish = await readPageState(id);
  });

  // What this lane deliberately does not claim, and why. The DSL refuses
  // the first as a page key until a lane measures it (dsl.py,
  // UNMEASURED_PAGE_KEYS).
  const pageStateUnmeasured = [];
  pageStateUnmeasured.push({ topic: "navigation",
    why: "Adding a page to the site navigation is a navigation-node write (web/Navigation/" +
      "QuickLaunch), not a page save; this lane writes pages only. No FINDINGS.md row " +
      "page.navigation.* exists, so the DSL refuses a navigation key." });
  pageStateUnmeasured.push({ topic: "permission-break",
    why: "HasUniqueRoleAssignments is READ on every page (persisted.*.permissions); breaking " +
      "inheritance (BreakRoleInheritance) is a permission write this lane does not attempt." });
  pageStateUnmeasured.push({ topic: "banner-json",
    why: "The banner is written two ways only (the item's URL field by MERGE, the page model's " +
      "BannerImageUrl by SavePageAsDraft). Any other banner-bearing key of the page entity is " +
      "listed under pageKeys and not written, because its shape is not assumed." });
  pageStateUnmeasured.push({ topic: "rendering",
    why: "This lane reads persisted fields only; whether the layout, banner or promoted state " +
      "renders as such is a browser question outside this readback." });

  // 5e. Recycle every page-state page (5d), each outcome on its sample. A
  //     refusal leaves the page in place and is the operator's cue; never
  //     a throw, and before the download.
  for (const sample of pageStateSamples) {
    if (sample.pageId === null) continue;
    try {
      const res = await fetchWithRetry(
        PAGES + "/items(" + sample.pageId + ")/recycle",
        { method: "POST", headers: { Accept: VERBOSE, "X-RequestDigest": await getDigest() } }
      );
      sample.recycled = res.ok;
      sample.recycleStatus = res.status;
      if (!res.ok) {
        sample.recycleReason = spError(await res.text().catch((e) => "body unreadable: " + bounded(e)));
      }
    } catch (err) {
      sample.recycled = false;
      sample.recycleReason = bounded(err);
    }
  }
  const pageStateRecycled = pageStateSamples.map(s => s.label + " " + (s.recycled === null
    ? "n/a" : s.recycled ? "ok" : "FAILED " + s.recycleStatus + " " + s.recycleReason)).join(", ");

  // 6. Verdicts: one string per findprobe-lane check-id, in the words the
  //    registry's result column uses, so a re-run's judgement is a string
  //    comparison. "byte-exact" is the stored block equal to the requested
  //    one; the text rows fold ':' to '&#58;' on both sides first, the one
  //    rewrite measured on text (page.text.colon-rewrite).
  const fold = canvas => canvas.replace(/:/g, "&#58;");
  const byId = new Map(storedBlocks.map(b => [b.id, b.canvas]));
  const byteExact = requested => requested.filter(r => byId.get(r.id) === r.canvas).length;
  const foldExact = requested =>
    requested.filter(r => byId.has(r.id) && fold(byId.get(r.id)) === fold(r.canvas)).length;
  const ratio = (n, of) => n + "/" + of;
  const labels = rows => rows.map(r => r.label).join(", ");
  const verdicts = {};
  verdicts["page.text.colon-rewrite"] =
    ratio(foldExact(textRequested), textRequested.length) + " byte-exact after the ':' fold";
  const identical = styleRequested.filter(r => byId.get(r.id) === r.canvas);
  verdicts["page.text.styled-html"] =
    ratio(foldExact(styleRequested), styleRequested.length) + " byte-exact after the ':' fold" +
    "; byte-identical: " + (identical.length ? labels(identical) : "none");
  const emphasisRows = sectionRequested.filter(r => r.label.startsWith("emphasis-"));
  const variantRows = sectionRequested.filter(r => !r.label.startsWith("emphasis-"));
  verdicts["page.emphasis.control-merge"] =
    ratio(byteExact(emphasisRows), emphasisRows.length) + " byte-exact; zoneEmphasis " +
    emphasisRows.map(r => emphasisOf(storedBlocks, r.id)).join(", ") + " read back";
  verdicts["page.section.variants-merge"] =
    ratio(byteExact(variantRows), variantRows.length) + " byte-exact";
  verdicts["page.page-model.draft-refuses-html"] = pageModelSave.ok
    ? "accepted " + pageModelSave.status +
      (pageModelSave.bodyApplied ? ", body applied" : ", body NOT applied")
    : "refused " + pageModelSave.status + ": " + pageModelSave.reason.split(". ")[0];
  // The property verdicts are keyed by alias slug, the same slug the Python
  // side computes (findings.alias_slug): NewsWebPart is news-web-part.
  const slug = alias => alias.replace(/([a-z0-9])([A-Z])/g, "$1-$2")
    .replace(/([A-Z])([A-Z][a-z])/g, "$1-$2").toLowerCase();
  for (const sample of PROPERTY_SAMPLES) {
    const skipped = propertySkipped.find(s => s.component === sample.component);
    const rows = propertyRequested.filter(r => r.component === sample.component);
    const modified = rows.find(r => r.variant === "modified");
    const kept = modified ? propertyPersisted.find(p => p.id === modified.id) : null;
    const roundTripped = Boolean(kept) && kept.present &&
      JSON.stringify(kept.storedValue) === JSON.stringify(modified.newValue);
    verdicts["page.properties." + slug(sample.component)] = skipped
      ? "not placed: " + skipped.why
      : ratio(byteExact(rows), rows.length) + " byte-exact; " + sample.path + " " +
        JSON.stringify(modified.oldValue) + " to " + JSON.stringify(modified.newValue) +
        (roundTripped ? " round-tripped" : " NOT round-tripped");
  }
  const layoutRows = prefix => layoutRequested.filter(r => r.label.startsWith(prefix));
  verdicts["page.layout.factors-8-4"] =
    ratio(byteExact(layoutRows("split-8-4")), layoutRows("split-8-4").length) + " byte-exact";
  const writtenOrder = layoutRows("split-4-8-two").map(r => r.id);
  const storedOrder = storedBlocks.map(b => b.id).filter(id => writtenOrder.includes(id));
  verdicts["page.layout.factors-4-8"] =
    ratio(byteExact(layoutRows("split-4-8")), layoutRows("split-4-8").length) +
    " byte-exact; written order " + (storedOrder.join() === writtenOrder.join() ? "kept" : "CHANGED");
  verdicts["page.bind.list-library-keys"] =
    ratio(byteExact(bindingRequested), bindingRequested.length) + " byte-exact" +
    (bindingSkipped.length ? "; skipped " + labels(bindingSkipped) : "");
  verdicts["page.emphasis.section-savepage"] = sectionEmphasis.summary;

  // Page-state verdicts (M7): one per FINDINGS.md row, computed from the
  // measured FIELDS the claims rest on — never from create success or
  // server-assigned ids (review 2026-09-07 P1-2: "ok (page 16)" diffs on
  // every run and reverses of the claim still read "same").
  const psByLabel = {};
  for (const s of pageStateSamples) psByLabel[s.label] = s;
  const psField = (label, path, fallback) => {
    // Dotted path through a sample's persisted steps; a missing path or
    // sample yields the fallback so the verdict stays a stable string.
    let node = psByLabel[label];
    node = node && node.persisted ? node.persisted : null;
    for (const part of path.split(".")) {
      if (node && hasOwn(node, part)) node = node[part];
      else return fallback;
    }
    // A null at the end of the path is a MEASURED null, not a missing path
    // (review 2026-09-07 P2-4: Description reads null — that is the answer).
    return node === undefined ? fallback : String(node);
  };
  // filename-slug: did the server keep the requested FileName? Compare the
  // requested name with the stored one — run-independent by construction.
  const fileNameKept = label => {
    const s = psByLabel[label];
    if (!s) return "no sample";
    const wanted = s.requested && s.requested.create
      ? s.requested.create.FileName : null;
    const got = psField(label, "created.fields.FileName", null)
      || psField(label, "read.page.fields.FileName", null);
    return wanted && got ? (got === wanted ? "kept" : "ignored (stored " + got + ")")
      : "no read";
  };
  verdicts["page.page-state.filename-slug"] =
    "explicit: " + fileNameKept("filename-explicit") +
    "; slug-needing: " + fileNameKept("filename-normalised");
  // description-banner: the AFTER-MERGE reads, folded to stable words —
  // a banner URL in a cell would be tenant-specific.
  const bannerKept = (() => {
    const s = psByLabel["filename-explicit"];
    if (!s) return "no sample";
    const wanted = s.requested && s.requested.merge && s.requested.merge.BannerImageUrl
      ? s.requested.merge.BannerImageUrl.Url : null;
    const got = psField("filename-explicit", "afterMerge.page.fields.BannerImageUrl", null);
    return wanted && got ? (got === wanted ? "persisted" : "changed") : "not persisted";
  })();
  verdicts["page.page-state.description-banner"] =
    "description " + psField("filename-explicit", "afterMerge.page.fields.Description", "missing") +
    "; banner " + bannerKept;
  // layout-article: the stored layout type, not the create's exit code.
  verdicts["page.page-state.layout-article"] =
    "PageLayoutType " + psField("layout-article", "read.page.fields.PageLayoutType", "missing");
  // promoted-state: the two measured values, causal claim left to the row.
  verdicts["page.page-state.promoted-state"] =
    "at create " + psField("promoted-at-create", "read.page.fields.PromotedState", "missing") +
    "; after merge " + psField("promoted-merge-flip", "afterMerge.page.fields.PromotedState", "missing") +
    " (merge status " + (() => { const s = psByLabel["promoted-merge-flip"];
      return s && s.persisted && s.persisted.merge ? s.persisted.merge.status : "?"; })() + ")";
  // create-is-effective (M8): the value AND the layout it was measured
  // beside, so the row cannot be read as a Home-layout result.
  verdicts["page.promoted-state.create-is-effective"] =
    "PromotedState " + psField("promoted-at-create", "read.page.fields.PromotedState", "missing") +
    " at create beside " + psField("promoted-at-create", "read.page.fields.PageLayoutType", "missing");
  // publish-flow: the flow's end state in fixed wording, from the steps.
  const publishFlow = (() => {
    const s = psByLabel["publish-state"];
    if (!s) return "no sample";
    const freshV = psField("publish-state", "fresh.page.fields.Version", "?");
    const pub = s.persisted && s.persisted.publish ? s.persisted.publish.status : "?";
    const afterV = psField("publish-state", "afterPublish.page.fields.Version", "?");
    const stillOut = psField("publish-state", "afterPublish.page.fields.IsPageCheckedOutToCurrentUser", "?");
    return "fresh " + freshV + " checked out; checkoutpage " +
      (s.persisted && s.persisted.checkout ? s.persisted.checkout.status : "?") +
      "; publish " + pub + " -> " + afterV + ", checked out " + stillOut;
  })();
  verdicts["page.page-state.publish-flow"] = publishFlow;
  verdicts["page.page-state.permission-inheritance"] =
    psField("filename-normalised", "read.permissions.hasUniqueRoleAssignments", "missing");

  // 7. Diff against the registry and download. "same" means the row still
  //    holds; "DIFFERS" is the operator's cue to re-measure, fold the new
  //    capture into the fixtures and add a dated row. A verdict no row
  //    records is listed under `unregistered`.
  const report = FINDINGS.map(row => {
    if (row.lane !== "findprobe") {
      return { checkId: row.checkId, measured: row.measured, recorded: row.result,
        reprobed: "not re-run here: formwork gen discover", verdict: "discover lane" };
    }
    const reprobed = hasOwn(verdicts, row.checkId)
      ? verdicts[row.checkId] : "no leg computes this check-id";
    return { checkId: row.checkId, measured: row.measured, recorded: row.result,
      reprobed: reprobed, verdict: reprobed === row.result ? "same" : "DIFFERS" };
  });
  const registered = new Set(FINDINGS.map(row => row.checkId));
  const unregistered = Object.keys(verdicts).filter(id => !registered.has(id))
    .map(id => ({ checkId: id, reprobed: verdicts[id] }));
  const counts = {
    same: report.filter(r => r.verdict === "same").length,
    differs: report.filter(r => r.verdict === "DIFFERS").length,
    discoverLane: report.filter(r => r.verdict === "discover lane").length,
  };
  const findprobe = {
    schema: "formwork.findprobe/v1",
    probedAt: new Date().toISOString(),
    web: {
      url: location.origin + webRoot,
      id: web.d.Id,
      title: web.d.Title,
    },
    registry: FINDINGS,
    verdicts: report,
    unregistered: unregistered,
    counts: counts,
    // The evidence under discover's own keys, so a DIFFERS row can be read
    // the way its fixture was, plus the SavePage leg's record.
    evidence: {
      textControls: { requested: textRequested, persisted: textPersisted },
      styling: {
        styleSamples: { requested: styleRequested, persisted: stylePersisted },
        sectionSamples: { requested: sectionRequested, persisted: sectionPersisted },
        pageModelSave: pageModelSave,
        sectionEmphasisMechanism: sectionEmphasis,
      },
      webpartProperties: { requested: propertyRequested, persisted: propertyPersisted,
        skipped: propertySkipped },
      layoutVariants: { requested: layoutRequested, persisted: layoutPersisted },
      listBindings: { fixtures: probeLists, requested: bindingRequested,
        persisted: bindingPersisted, skipped: bindingSkipped },
      // The M7 page-state lane (5d), under discover's key and in its shape,
      // listed rather than judged: its rows are discover-lane rows.
      pageState: {
        measuredAt: new Date().toISOString().slice(0, 10),
        scratchPrefix: PAGE_STATE,
        pageKeys: pageStateKeys,
        samples: pageStateSamples,
        unmeasured: pageStateUnmeasured,
      },
      storedCanvas: stored,
    },
    placements: {
      scratchPageId: scratchId,
      recycled: recycleRes.ok,
      requestedCanvasChars: canvas.length,
      storedCanvasChars: stored.length,
      storedControlCount: storedBlocks.length,
      savePageScratchId: sectionEmphasis.pageId,
      savePageRecycled: sectionEmphasis.recycled,
      pageStateScratchIds: pageStateSamples.map(s => s.pageId),
      pageStateRecycled: pageStateSamples.map(s => s.recycled),
    },
  };
  const blob = new Blob([JSON.stringify(findprobe, null, 2)],
                        { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "formwork-findprobe.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  console.table(report);
  console.log("[formwork] findprobe complete:",
    counts.same, "same |", counts.differs, "DIFFERS |", counts.discoverLane, "discover lane |",
    unregistered.length, "unregistered |",
    "scratch recycled:", recycleRes.ok, "|",
    "SavePage scratch recycled:", sectionEmphasis.recycled, "|",
    "probe lists recycled:", probeLists.map(p => p.key + " " + (p.recycled === null
      ? "n/a" : p.recycled ? "ok" : "FAILED " + p.recycleStatus + " " + p.recycleReason)).join(", "), "|",
    "page-state samples ok", pageStateSamples.filter(s => s.ok).length, "of", pageStateSamples.length, "|",
    "page-state pages recycled:", pageStateRecycled);
})().catch(err => { console.error("[formwork] findprobe failed:", err); });
