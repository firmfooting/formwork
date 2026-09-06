// formwork discover v0.2.0 — run from any page of the site.
// Creates a scratch page, places components, reads back, recycles,
// and downloads formwork-discovery.json.
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
  async function postJson(url, body) {
    const res = await fetchWithRetry(url, {
      method: "POST",
      headers: { Accept: VERBOSE, "Content-Type": VERBOSE },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw await failed("POST " + url, res);
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
  async function createSitePage(title) {
    const digest = await getDigest();
    const res = await fetchWithRetry(API("sitepages/pages"), {
      method: "POST",
      headers: { Accept: VERBOSE, "Content-Type": VERBOSE, "X-RequestDigest": digest },
      body: JSON.stringify({
        __metadata: { type: "SP.Publishing.SitePage" },
        PageLayoutType: "Home",
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

  // 1. Enumerate every placeable component on this site.
  const partsRes = await fetchWithRetry(API("web/GetClientSideWebParts"), {
    headers: { Accept: "application/json;odata=nometadata" },
  });
  if (!partsRes.ok) throw await failed("GetClientSideWebParts", partsRes);
  const components = (await partsRes.json()).value || [];

  // 2. Create the scratch page, then write the discovery canvas onto it.
  const SCRATCH = "formwork-discovery-" + Date.now();

  // 3. Place one control per web part, spread across one/two/three-column
  //    sections, then save and read back what SharePoint persisted.
  const placeable = components.filter(c => c.ComponentType === 1);
  const sections = [];
  const FACTORS = {
    one: [12],
    two: [6, 6],
    three: [4, 4, 4],
  };
  let idx = 0;
  for (const [name, factors] of Object.entries(FACTORS)) {
    sections.push({ type: name, zoneIndex: (sections.length + 1) * 1000, factors });
  }
  const controls = [];
  const perColumn = {}; // "section:col" -> next controlIndex
  for (let i = 0; i < placeable.length; i++) {
    const s = i % sections.length;
    const section = sections[s];
    // Mostly column 1; every 4th part exercises column 2/3 when present.
    const col = (i % 4 === 3 && section.factors.length > 1) ? 2 : 1;
    const key = (s + 1) + ":" + col;
    perColumn[key] = (perColumn[key] || 0) + 1;
    controls.push({
      controlType: 3,
      id: "00000000-0000-0000-0000-" + String(i + 1).padStart(12, "0"),
      position: {
        zoneIndex: section.zoneIndex,
        sectionIndex: s + 1,
        controlIndex: perColumn[key],
        zoneId: null,
        sectionFactor: section.factors[col - 1],
        layoutIndex: 1,
      },
      webPartId: placeable[i].Id,
      emphasis: {},
    });
  }

  // 3a. Text controls are NOT web parts: controlType 4, no webPartId, no
  //     webpartdata; the HTML is the inner content of a data-sp-rte child.
  //     That is the shape PnP has written since 2017 and is what is SENT
  //     here. What SharePoint PERSISTS of it (wrapper, escaping, attribute
  //     order, which tags and styles survive) is the measurement this probe
  //     exists for, so two known bodies go into a fourth, one-column section
  //     and both the requested and the persisted blocks are downloaded
  //     verbatim. TODO(measure, 2026-09-06): live run pending; until it has
  //     been read, the compiler emits the requested shape.
  const TEXT_SAMPLES = [
    '<h2>Formwork text probe</h2><p>Paragraph with <b>bold</b>, ' +
      '<a href="https://example.com/">a link</a> and ' +
      '<span style="color:#a4262c;">a colour span</span>.</p>',
    '<p>Second text control: <strong>strong</strong>, <em>emphasis</em>, ' +
      'and a list.</p><ul><li>one</li><li>two</li></ul>',
  ];
  const textSection = { type: "text", zoneIndex: (sections.length + 1) * 1000, factors: [12] };
  sections.push(textSection);
  const textControls = TEXT_SAMPLES.map((html, i) => ({
    html: html,
    cd: {
      controlType: 4,
      id: "00000000-0000-0000-0001-" + String(i + 1).padStart(12, "0"),
      position: {
        zoneIndex: textSection.zoneIndex,
        sectionIndex: sections.length,
        controlIndex: i + 1,
        zoneId: null,
        sectionFactor: 12,
        layoutIndex: 1,
      },
      emphasis: {},
      editorType: "CKEditor",
    },
  }));

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/{/g, "&#123;").replace(/}/g, "&#125;")
      .replace(/:/g, "&#58;");
  }
  let canvas = "<div>";
  for (const cd of controls) {
    const comp = placeable.find(c => c.Id === cd.webPartId);
    const manifest = JSON.parse(comp.Manifest || "{}");
    const entry = (manifest.preconfiguredEntries || [])[0] || {};
    const wpd = {
      id: comp.Id,
      instanceId: cd.id,
      title: (entry.title || {}).default || manifest.alias || comp.Id,
      description: (entry.description || {}).default || "",
      serverProcessedContent: {},
      dataVersion: (entry.dataVersion || "1.0"),
      properties: (entry.properties || {}),
    };
    canvas += '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0"'
    canvas += ' data-sp-controldata="' + esc(JSON.stringify(cd)) + '">'
    canvas += '<div data-sp-webpartdata="' + esc(JSON.stringify(wpd)) + '"></div></div>';
  }
  // The control data is attribute-escaped exactly like a web part's; the
  // HTML itself is inner content and goes in as written.
  const textRequested = [];
  for (const t of textControls) {
    const block = '<div data-sp-canvascontrol="" data-sp-canvasdataversion="1.0"' +
      ' data-sp-controldata="' + esc(JSON.stringify(t.cd)) + '">' +
      '<div data-sp-rte="">' + t.html + '</div></div>';
    canvas += block;
    textRequested.push({ id: t.cd.id, html: t.html, controlData: t.cd, canvas: block });
  }
  canvas += "</div>";

  // 3b. Create the scratch page, then write the discovery canvas onto it.
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

  // 4a. The persisted text controls, verbatim. Split at control boundaries
  //     (the rule canvas.py parses by), decode each block's controldata
  //     through the browser's own HTML parser, keep controlType 4. The raw
  //     block is kept, not a re-serialisation: the bytes are the evidence.
  const CONTROL_OPEN = '<div data-sp-canvascontrol=""';
  // The last block would otherwise carry everything to the end of the
  // canvas — including the page wrapper's own "</div>", which would make
  // persisted != requested forever (review P2-2, 2026-09-06). The canvas
  // is exactly "<div>" + blocks + "</div>", so strip that one wrapper close.
  const wrapperClose = "</div>";
  const storedTail = stored.endsWith(wrapperClose) ? stored.slice(0, -wrapperClose.length) : stored;
  const storedBlocks = storedTail.split(CONTROL_OPEN).slice(1).map(b => CONTROL_OPEN + b);
  const controlDataOf = (block) => {
    try {
      const el = new DOMParser().parseFromString(block, "text/html")
        .querySelector("[data-sp-controldata]");
      return JSON.parse(el.getAttribute("data-sp-controldata"));
    } catch {
      return null;
    }
  };
  const textPersisted = [];
  for (const block of storedBlocks) {
    const cd = controlDataOf(block);
    if (cd && cd.controlType === 4) {
      textPersisted.push({ id: cd.id, controlData: cd, canvas: block });
    }
  }

  // 5. Recycle the scratch page (undo the write; evidence is downloaded).
  const recycleRes = await fetchWithRetry(
    PAGES + "/items(" + scratchId + ")/recycle",
    { method: "POST", headers: { Accept: VERBOSE, "X-RequestDigest": await getDigest() } }
  );

  // 6. Download the discovery document.
  const web = await getJson(API("web?$select=Id,Title,Url,ServerRelativeUrl"));
  const discovery = {
    schema: "formwork.discovery/v1",
    discoveredAt: new Date().toISOString(),
    web: {
      url: location.origin + (web.d.ServerRelativeUrl === "/" ? "" : web.d.ServerRelativeUrl),
      id: web.d.Id,
      title: web.d.Title,
    },
    components: components,
    placements: {
      placedCount: controls.length + textControls.length,
      textPlacedCount: textControls.length,
      requestedCanvasChars: canvas.length,
      storedCanvasChars: stored.length,
      storedControlCount: (stored.match(/data-sp-canvascontrol/g) || []).length,
      scratchPageId: scratchId,
      recycled: recycleRes.ok,
    },
    // Additive (schema stays v1): the two text controls as sent and as
    // SharePoint persisted them, matched by control id on the Python side.
    textControls: {
      requested: textRequested,
      persisted: textPersisted,
    },
    storedCanvas: stored,
  };
  const blob = new Blob([JSON.stringify(discovery, null, 2)],
                        { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "formwork-discovery.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  console.log("[formwork] discovery complete:",
    components.length, "components |",
    controls.length, "placed |",
    "stored", (stored.match(/data-sp-canvascontrol/g) || []).length, "controls |",
    "text controls persisted", textPersisted.length, "of", textRequested.length, "|",
    "scratch recycled:", recycleRes.ok);
})().catch(err => { console.error("[formwork] discover failed:", err); });
