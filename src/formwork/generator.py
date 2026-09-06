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

# Shared prelude: same-origin fetch helper with verbose OData headers.
_JS_PRELUDE = """(async () => {
  const SCHEMA = "formwork.bundle/v1";
  const VERBOSE = "application/json;odata=verbose";
  async function getJson(url) {
    const res = await fetch(url, { headers: { Accept: VERBOSE } });
    if (!res.ok) throw new Error("GET " + url + " -> " + res.status);
    return res.json();
  }
"""

_EXTRACT_BODY = """
  const PAGE_PATH = await (async () => {
    // The path this script was run from names the page to extract.
    const m = location.pathname.match(/SitePages\\/[^/]+\\.aspx$/i);
    if (!m) throw new Error("Run this from a modern page under .../SitePages/");
    return m[0];
  })();

  const web = await getJson("/_api/web?$select=Id,Title,Url");
  const site = await getJson("/_api/site?$select=Id,Url");
  const listId = (await getJson(
    "/_api/web/lists/getbytitle('Site Pages')?$select=Id"
  )).d.Id;

  const fileName = PAGE_PATH.replace(/^SitePages\\//i, "");
  const pageRes = await fetch(
    "/_api/web/lists/getbytitle('Site Pages')/items?$filter=" +
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

  const webPath = new URL(web.d.Url).pathname.replace(/\\/$/, "");
  const bundle = {
    schema: SCHEMA,
    extractedAt: new Date().toISOString(),
    source: {
      webUrl: web.d.Url,
      webPath: webPath,
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
              "| canvas", (page.CanvasContent1 || "").length, "chars");
})().catch(err => { console.error("[formwork] extract failed:", err); });
"""

_APPLY_BODY = """
  const PAGE_NAME = {name};
  const PAYLOAD = JSON.parse({payload});
  const PROMOTED_STATE = {state};

  // 1. Form digest (the one POST that needs no digest).
  const digest = (await getJson("/_api/contextinfo").then(j => j.d))
    .GetContextWebInformation.FormDigestValue;

  // 2. Create the page item in Site Pages (Home layout: full-width sections).
  const createRes = await fetch(
    "/_api/web/lists/getbytitle('Site Pages')/items",
    {{
      method: "POST",
      headers: {{
        Accept: VERBOSE,
        "Content-Type": "application/json;odata=verbose",
        "X-RequestDigest": digest,
      }},
      body: JSON.stringify({{
        __metadata: {{ type: "SP.Data.SitePagesItem" }},
        Title: PAGE_NAME,
        PageLayoutType: "Home",
        PromotedState: PROMOTED_STATE,
      }}),
    }}
  );
  if (!createRes.ok) {{
    throw new Error("create page -> " + createRes.status + " " + await createRes.text());
  }}
  const created = (await createRes.json()).d;

  // 3. Write the canvas with MERGE + etag concurrency control.
  const etagRes = await fetch(
    "/_api/web/lists/getbytitle('Site Pages')/items(" + created.Id + ")",
    {{ headers: {{ Accept: VERBOSE }} }}
  );
  if (!etagRes.ok) throw new Error("read item -> " + etagRes.status);
  const etag = (await etagRes.json()).d.__metadata.etag;

  const mergeRes = await fetch(
    "/_api/web/lists/getbytitle('Site Pages')/items(" + created.Id + ")",
    {{
      method: "POST",
      headers: {{
        Accept: VERBOSE,
        "Content-Type": "application/json;odata=verbose",
        "X-RequestDigest": digest,
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
  "/_api/web/lists/getbytitle('Site Pages')/items(" + created.Id + ")" +
    "?$select=CanvasContent1,Title",
    {{ headers: {{ Accept: VERBOSE }} }}
  );
  const stored = (await verifyRes.json()).d;
  const storedLen = (stored.CanvasContent1 || "").length;
  const byteExact = stored.CanvasContent1 === PAYLOAD.canvas;
  console.log("[formwork] page created:",
    location.origin + location.pathname.replace(/\\/[^/]*$/, "/") + PAGE_NAME,
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
