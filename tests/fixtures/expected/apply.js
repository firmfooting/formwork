// formwork apply v__FORMWORK_VERSION__ — run from any page of the TARGET site.
// Checks the payload's provenance stamp against this web, creates the page,
// writes the embedded canvas via REST, verifies.
//
// Provenance guard (architecture review 2026-09-06, P2-1). The payload carries
// the stamp formwork compile wrote: formwork version, discovery sha256, web id
// and URL, spec name, timestamps. Before anything is created this script reads
// the current web and REFUSES when its id or URL differs from the stamp's, or
// when the payload was compiled by a formwork newer than this script's own
// v__FORMWORK_VERSION__. To apply a payload on a web other than the one it was
// compiled against, edit FORCE_SITE_MISMATCH below to true; the difference is
// still printed. Nothing overrides the version check: a newer compile may rely
// on a measurement this script does not carry.
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

  const PAGE_NAME = "Formwork copy";
  const PAYLOAD = JSON.parse("{}");
  const PROMOTED_STATE = 0;
  const FORMWORK_VERSION = "__FORMWORK_VERSION__";
  // The one operator switch, documented in the header: true applies this
  // payload on a web whose id or URL differs from the stamp's. It never
  // covers the version check.
  const FORCE_SITE_MISMATCH = false;

  // 0. Provenance guard. Fail closed: each refusal is thrown before a page
  //    exists, and names the stamp's value beside the observed one.
  const STAMP = PAYLOAD.provenance;
  if (!STAMP || typeof STAMP !== "object" || typeof STAMP.formwork !== "string") {
    throw new Error(
      "provenance: the payload carries no stamp (PAYLOAD.provenance), so nothing binds it " +
      "to a web or to a formwork version: it predates formwork 0.5.0 or was written by " +
      "hand. Nothing was created. Recompile it (formwork compile or compile-pages), or " +
      "re-run formwork process."
    );
  }
  // Dotted numeric versions, segment by segment: "0.5.0" is newer than "0.4.10".
  const newerThan = (a, b) => {
    const as = String(a).split(".").map(n => parseInt(n, 10) || 0);
    const bs = String(b).split(".").map(n => parseInt(n, 10) || 0);
    for (let i = 0; i < Math.max(as.length, bs.length); i++) {
      if ((as[i] || 0) !== (bs[i] || 0)) return (as[i] || 0) > (bs[i] || 0);
    }
    return false;
  };
  if (newerThan(STAMP.formwork, FORMWORK_VERSION)) {
    throw new Error(
      "provenance: the payload was compiled by formwork " + STAMP.formwork +
      ", newer than this script's v" + FORMWORK_VERSION + ". Nothing was created. A newer " +
      "compile may rely on a measurement this script does not carry, so " +
      "FORCE_SITE_MISMATCH does not cover this: regenerate the script with formwork " +
      STAMP.formwork + " or newer (formwork gen apply)."
    );
  }
  // The web this console belongs to, read the way discover recorded it:
  // web.d.Id, and location.origin plus the web's server-relative root ("" on
  // the root web), so the two URLs compare like for like (discover.js.j2).
  const webRes = await fetchWithRetry(API("web?$select=Id,ServerRelativeUrl"), {
    headers: { Accept: VERBOSE },
  });
  if (!webRes.ok) throw await failed("web read", webRes);
  const here = (await webRes.json()).d;
  const hereUrl =
    location.origin + (here.ServerRelativeUrl === "/" ? "" : here.ServerRelativeUrl);
  const stampOrigin = "formwork " + STAMP.formwork + ", " +
    (typeof STAMP.spec === "string"
      ? "spec " + STAMP.spec + " compiled " + STAMP.compiledAt
      : "bundle " + STAMP.bundle + " processed " + STAMP.processedAt);
  if (typeof STAMP.discoveryWebId === "string") {
    // A compile stamp: bound to the discovery document's web.
    const mismatches = [];
    if (STAMP.discoveryWebId !== here.Id) {
      mismatches.push("web id: stamp " + STAMP.discoveryWebId + ", this web " + here.Id);
    }
    if (STAMP.discoveryWebUrl !== hereUrl) {
      mismatches.push("web url: stamp " + STAMP.discoveryWebUrl + ", this web " + hereUrl);
    }
    if (mismatches.length && !FORCE_SITE_MISMATCH) {
      throw new Error(
        "provenance mismatch: " + mismatches.join("; ") + ". The payload (" + stampOrigin +
        ") was compiled against discovery sha256 " + STAMP.discoverySha256 + " discovered " +
        STAMP.discoveredAt + ", so its canvas was compiled for that web, not this one. " +
        "Nothing was created. Run this from the web it was compiled against, recompile " +
        "against this web's discovery document, or set FORCE_SITE_MISMATCH = true in this " +
        "script to apply it here anyway."
      );
    }
    if (mismatches.length) {
      console.warn("[formwork] FORCE_SITE_MISMATCH: applying despite " + mismatches.join("; "));
    } else {
      console.log("[formwork] provenance OK:", stampOrigin,
        "| web " + here.Id + " at " + hereUrl + " matches the stamp");
    }
  } else {
    // A process stamp: a copied page is bound to its mapping, not to a
    // discovery document, so there is no web to compare and the site check
    // does not apply. The version check above did.
    console.log("[formwork] provenance:", stampOrigin,
      "| no discovery binding (process payload): site check not applicable");
  }

  // 1. Create the page through the sitepages API. PromotedState travels IN
  //    the create body: sent at create it persisted as 1 (FINDINGS
  //    page.promoted-state.create-is-effective, measured 2026-09-06 beside the
  //    Article layout, discovery.pagestate.json pageState.samples.3). Sent by
  //    the post-create item MERGE this script made before 0.5.0 it returned
  //    204 and read back 0 on the Home layout (page.page-state.promoted-state;
  //    review 2026-09-07 P1-3). This script creates Home, and Home with
  //    PromotedState at create is not yet a sample of its own, so step 3
  //    prints what persisted. 0 sends nothing: it is the measured default.
  const created = await createSitePage(
    PAGE_NAME,
    PROMOTED_STATE === 1 ? { PromotedState: 1 } : {}
  );

  // 2. Write the canvas with MERGE + etag concurrency control.
  const itemRes = await fetchWithRetry(
    PAGES + "/items(" + created.id + ")",
    { headers: { Accept: VERBOSE } }
  );
  if (!itemRes.ok) throw await failed("read item", itemRes);
  const etag = (await itemRes.json()).d.__metadata.etag;

  const mergeRes = await fetchWithRetry(
    PAGES + "/items(" + created.id + ")",
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
        CanvasContent1: PAYLOAD.canvas,
        Title: PAYLOAD.title,
      }),
    }
  );
  if (!mergeRes.ok) throw await failed("canvas write", mergeRes);

  // 3. Verify: read back what SharePoint actually stored.
  const verifyRes = await fetchWithRetry(
    PAGES + "/items(" + created.id + ")?$select=CanvasContent1,Title,PromotedState",
    { headers: { Accept: VERBOSE } }
  );
  if (!verifyRes.ok) throw await failed("verify read", verifyRes);
  const stored = (await verifyRes.json()).d;
  const storedLen = (stored.CanvasContent1 || "").length;
  const byteExact = stored.CanvasContent1 === PAYLOAD.canvas;
  console.log("[formwork] page created:",
    location.origin + created.url,
    "| canvas stored:", storedLen, "chars",
    "| byte-exact:", byteExact,
    "| PromotedState:", stored.PromotedState, "(requested " + PROMOTED_STATE + ")");
  if (Number(stored.PromotedState) !== PROMOTED_STATE) {
    // The page exists either way, and a promoted state is a flag the operator
    // can change in the UI, so this is a warning, not the canvas throw below.
    console.warn("[formwork] PromotedState read back " + stored.PromotedState +
      ", requested " + PROMOTED_STATE + ": the Home layout with PromotedState at create is " +
      "not yet measured (page.page-state.promoted-state); re-probe with formwork gen findprobe.");
  }
  if (!byteExact) {
    // The page exists: it was created and merged before this check ran.
    // Nothing here recycles it (an unmeasured auto-delete would be a new
    // behaviour); keeping or recycling it is the operator's call. Compile
    // spells ':' as '&#58;' inside text HTML, the stored spelling measured
    // 2026-09-06, so a mismatch here is a real difference, not that rewrite.
    throw new Error(
      "canvas mismatch: sent " + PAYLOAD.canvas.length + " chars, stored " + storedLen +
      ". The page EXISTS with what SharePoint stored: item " + created.id + " at " +
      location.origin + created.url +
      ". Formwork does not recycle it; keep it or recycle it yourself."
    );
  }
  console.log("[formwork] verify OK — reload the new page to inspect it.");
})().catch(err => { console.error("[formwork] apply failed:", err); });
