"""Paste-in script generators.

Formwork's operator interface is two console paste-ins generated here:

* the extract script runs on the SOURCE page's site, fetches the page item
  and the web's identity over same-origin REST, assembles a formwork bundle,
  and downloads it as formwork-bundle.json;
* the apply script runs on any page of the TARGET site, reads the processed
  payload embedded in it, creates the new page, writes the canvas, and
  verifies by reading back what SharePoint actually stored.

All fetches use relative URLs so the same script body works on any tenant and
site; only the embedded payload differs per apply run.
"""

import json

from . import __version__

# Shared prelude: same-origin fetch helpers with verbose OData headers.
#
# Measured constraints (shauntestazure sandbox, 2026-09-06):
# - unprefixed "/_api/..." fetches from a sub-site page resolve against the
#   TENANT ROOT web, not the site in the address bar. Every REST call must
#   carry the site prefix, derived here from location.pathname.
# - contextinfo is POST-only (GET -> 405).
# - Site Pages is a document library: list-item POST is refused
#   ("use SPFileCollection.Add()"), and Files/add of an .aspx is refused
#   (403). Pages are created through /_api/sitepages/pages.
_JS_PRELUDE = """(async () => {
  const SCHEMA = "formwork.bundle/v1";
  const VERBOSE = "application/json;odata=verbose";
  // The site prefix of the page this script runs on, e.g.
  // "/sites/TeamX" from "/sites/TeamX/SitePages/Home.aspx", or "" on the
  // tenant root site.
  const SITE = location.pathname.match(/^(\\/.*)\\/SitePages\\//i);
  const PREFIX = SITE ? SITE[1] : "";
  if (!/^\\/SitePages\\//i.test(location.pathname) && !SITE) {
    throw new Error("Run this from a modern page under .../SitePages/");
  }
  const API = (path) => PREFIX + "/_api/" + path.replace(/^\\/+/, "");
  async function getJson(url) {
    const res = await fetch(url, { headers: { Accept: VERBOSE } });
    if (!res.ok) throw new Error("GET " + url + " -> " + res.status);
    return res.json();
  }
  async function postJson(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { Accept: VERBOSE, "Content-Type": VERBOSE },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw new Error("POST " + url + " -> " + res.status);
    return res.json();
  }
  // The context digest must be POSTed — GET is refused with 405.
  async function getDigest() {
    return (await postJson(API("contextinfo"))).d
      .GetContextWebInformation.FormDigestValue;
  }
  // Pages are created through the sitepages API: Files/add refuses .aspx
  // (403), and a list-item POST into Site Pages is refused outright.
  async function createSitePage(title) {
    const digest = await getDigest();
    const res = await fetch(API("sitepages/pages"), {
      method: "POST",
      headers: { Accept: VERBOSE, "Content-Type": VERBOSE, "X-RequestDigest": digest },
      body: JSON.stringify({
        __metadata: { type: "SP.Publishing.SitePage" },
        PageLayoutType: "Home",
      }),
    });
    if (!res.ok) {
      throw new Error("page create -> " + res.status + " " + await res.text());
    }
    const page = (await res.json()).d;
    return {
      id: page.Id,
      url: page.Url,
      title: title,
      setFields: async (fields) => {
        const itemRes = await fetch(
          API("web/lists/getbytitle('Site Pages')/items(" + page.Id + ")"),
          { headers: { Accept: VERBOSE } }
        );
        if (!itemRes.ok) throw new Error("item read -> " + itemRes.status);
        const item = (await itemRes.json()).d;
        const mergeRes = await fetch(
          API("web/lists/getbytitle('Site Pages')/items(" + page.Id + ")"),
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
        if (!mergeRes.ok) {
          throw new Error("item update -> " + mergeRes.status + " " + await mergeRes.text());
        }
      },
    };
  }
"""

_EXTRACT_BODY = """
  const PAGE_PATH = location.pathname.match(/SitePages\\/[^/]+\\.aspx$/i)[0];

  const web = await getJson(API("web?$select=Id,Title,Url,ServerRelativeUrl"));
  const site = await getJson(API("site?$select=Id,Url"));
  const listId = (await getJson(
    API("web/lists/getbytitle('Site Pages')?$select=Id")
  )).d.Id;

  const fileName = PAGE_PATH.replace(/^SitePages\\//i, "");
  const pageRes = await fetch(
    API("web/lists/getbytitle('Site Pages')/items?$filter=") +
      encodeURIComponent("FileLeafRef eq '" + fileName + "'") +
      "&$select=Id,Title,Created,Modified,CanvasContent1,LayoutWebpartsContent," +
      "PageLayoutType,PromotedState,BannerImageUrl,Description,AuthorId,EditorId,FileLeafRef",
    { headers: { Accept: VERBOSE } }
  );
  if (!pageRes.ok) throw new Error("page query -> " + pageRes.status);
  const pages = (await pageRes.json()).d.results;
  if (pages.length !== 1) {
    throw new Error("expected 1 page for " + PAGE_PATH + ", got " + pages.length);
  }
  const page = pages[0];

  const webPath = web.d.ServerRelativeUrl === "/"
    ? "" : web.d.ServerRelativeUrl.replace(/\\/$/, "");
  const bundle = {
    schema: SCHEMA,
    extractedAt: new Date().toISOString(),
    source: {
      webUrl: location.origin + webPath,
      webPath: webPath || "/",
      pagePath: "SitePages/" + page.FileLeafRef,
      pageItemId: page.Id,
      listId: listId,
      webId: web.d.Id,
      siteId: site.d.Id,
    },
    meta: { webTitle: web.d.Title, formworkVersion: "__FWV__" },
    page: page,
    sections: [],
    webParts: [],
  };

  const blob = new Blob([JSON.stringify(bundle, null, 2)],
                        { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "formwork-bundle.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  console.log("[formwork] bundle downloaded:", page.FileLeafRef,
              "| canvas", (page.CanvasContent1 || "").length, "chars",
              "| site", PREFIX || "(root)");
})().catch(err => { console.error("[formwork] extract failed:", err); });
"""

_APPLY_BODY = """
  const PAGE_NAME = {name};
  const PAYLOAD = JSON.parse({payload});
  const PROMOTED_STATE = {state};

  // 1. Create the page through the sitepages API, then set item fields.
  const created = await createSitePage(PAGE_NAME);
  await created.setFields({{ PromotedState: PROMOTED_STATE }});

  // 2. Write the canvas with MERGE + etag concurrency control.
  const itemRes = await fetch(
    API("web/lists/getbytitle('Site Pages')/items(" + created.id + ")"),
    {{ headers: {{ Accept: VERBOSE }} }}
  );
  if (!itemRes.ok) throw new Error("read item -> " + itemRes.status);
  const etag = (await itemRes.json()).d.__metadata.etag;

  const mergeRes = await fetch(
    API("web/lists/getbytitle('Site Pages')/items(" + created.id + ")"),
    {{
      method: "POST",
      headers: {{
        Accept: VERBOSE,
        "Content-Type": "application/json;odata=verbose",
        "X-RequestDigest": await getDigest(),
        "X-HTTP-Method": "MERGE",
        "If-Match": etag,
      }},
      body: JSON.stringify({{
        __metadata: {{ type: "SP.Data.SitePagesItem" }},
        CanvasContent1: PAYLOAD.canvas,
        Title: PAYLOAD.title,
      }}),
    }}
  );
  if (!mergeRes.ok) {{
    throw new Error("canvas write -> " + mergeRes.status + " " + await mergeRes.text());
  }}

  // 4. Verify: read back what SharePoint actually stored.
  const verifyRes = await fetch(
    API("web/lists/getbytitle('Site Pages')/items(" + created.id + ")") +
      "?$select=CanvasContent1,Title",
    {{ headers: {{ Accept: VERBOSE }} }}
  );
  const stored = (await verifyRes.json()).d;
  const storedLen = (stored.CanvasContent1 || "").length;
  const byteExact = stored.CanvasContent1 === PAYLOAD.canvas;
  console.log("[formwork] page created:",
    location.origin + created.url,
    "| canvas stored:", storedLen, "chars",
    "| byte-exact:", byteExact);
  if (!byteExact) {{
    throw new Error("canvas mismatch: sent " + PAYLOAD.canvas.length + ", stored " + storedLen);
  }}
  console.log("[formwork] verify OK — reload the new page to inspect it.");
}})().catch(err => {{ console.error("[formwork] apply failed:", err); }});
"""


def generate_extract_script() -> str:
    """Console script: extract the current page as a formwork bundle."""
    header = f"// formwork extract v{__version__} — run from the source page itself.\n"
    return header + _JS_PRELUDE + _EXTRACT_BODY.replace("__FWV__", __version__)


_DISCOVER_BODY = """
  // 1. Enumerate every placeable component on this site.
  const partsRes = await fetch(API("web/GetClientSideWebParts"), {
    headers: { Accept: "application/json;odata=nometadata" },
  });
  if (!partsRes.ok) throw new Error("GetClientSideWebParts -> " + partsRes.status);
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
  canvas += "</div>";

  // 3b. Create the scratch page, then write the discovery canvas onto it.
  const scratch = await createSitePage(SCRATCH);
  const scratchId = scratch.id;
  await scratch.setFields({ Title: SCRATCH });

  const itemRes = await fetch(
    API("web/lists/getbytitle('Site Pages')/items(" + scratchId + ")"),
    { headers: { Accept: VERBOSE } }
  );
  const etag = (await itemRes.json()).d.__metadata.etag;
  const saveRes = await fetch(
    API("web/lists/getbytitle('Site Pages')/items(" + scratchId + ")"),
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
  if (!saveRes.ok) {
    throw new Error("scratch save -> " + saveRes.status + " " + await saveRes.text());
  }

  // 4. Read back the persisted canvas.
  const readRes = await fetch(
    API("web/lists/getbytitle('Site Pages')/items(" + scratchId + ")?$select=CanvasContent1"),
    { headers: { Accept: VERBOSE } }
  );
  const stored = (await readRes.json()).d.CanvasContent1 || "";

  // 5. Recycle the scratch page (undo the write; evidence is downloaded).
  const recycleRes = await fetch(
    API("web/lists/getbytitle('Site Pages')/items(" + scratchId + ")/recycle"),
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
      placedCount: controls.length,
      requestedCanvasChars: canvas.length,
      storedCanvasChars: stored.length,
      storedControlCount: (stored.match(/data-sp-canvascontrol/g) || []).length,
      scratchPageId: scratchId,
      recycled: recycleRes.ok,
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
    "scratch recycled:", recycleRes.ok);
})().catch(err => { console.error("[formwork] discover failed:", err); });
"""


def generate_discover_script() -> str:
    """Console script: discover placeable components on the current site."""
    header = (
        f"// formwork discover v{__version__} — run from any page of the site.\n"
        "// Creates a scratch page, places components, reads back, recycles,\n"
        "// and downloads formwork-discovery.json.\n"
    )
    return header + _JS_PRELUDE + _DISCOVER_BODY


def generate_apply_script(
    page_name: str = "Formwork copy",
    canvas_payload: str = "{}",
    promoted_state: int = 0,
) -> str:
    """Console script: create the page on the target site and set its canvas.

    ``canvas_payload`` is the processed JSON document produced by
    ``formwork process``; it is embedded as a JSON string literal and parsed
    at runtime.
    """
    header = (
        f"// formwork apply v{__version__} — run from any page of the TARGET site.\n"
        '// Creates the page, writes the embedded canvas via REST, verifies.\n'
    )
    body = _APPLY_BODY.format(
        name=json.dumps(page_name),
        payload=json.dumps(canvas_payload),
        state=str(int(promoted_state)),
    )
    return header + _JS_PRELUDE + body
