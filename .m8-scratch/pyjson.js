// Emulates Python json.dumps (default separators, ensure_ascii) for the flat
// payload the apply-payload golden embeds, then the outer json.dumps of that
// string, so the golden's PAYLOAD line can be hand-applied byte for byte.
// Proves the emulation first: the OLD payload must reproduce the golden's
// current line exactly.
const fs = require("fs");
const py = (v) => {
  if (typeof v === "string") {
    return JSON.stringify(v).replace(/[-￿]/g,
      (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  }
  if (typeof v === "number") return String(v);
  if (Array.isArray(v)) return "[" + v.map(py).join(", ") + "]";
  return "{" + Object.entries(v).map(([k, x]) => py(k) + ": " + py(x)).join(", ") + "}";
};
const canvas = '<div>{"k": 1} \\ </script> ü</div>';
const old = { title: "Bob's <page>", canvas };
const stamped = {
  title: "Bob's <page>",
  canvas,
  provenance: {
    formwork: "0.5.0",
    discoverySha256: "931ef951f66f5f610dcd6ce06bb3eea0a57770fd30c5dbe89df8d80b4cb94e1d",
    discoveryWebId: "20c3b672-36ff-4738-9518-192017e92eea",
    discoveryWebUrl: "https://shauntestazure.sharepoint.com/sites/TestSampleTeam",
    discoveredAt: "2026-09-06T22:15:54.234Z",
    spec: "home.yaml",
    compiledAt: "2026-09-07T00:00:00Z",
  },
};
const line = (p) => "  const PAYLOAD = JSON.parse(" + JSON.stringify(py(p)) + ");";
const golden = fs.readFileSync("tests/fixtures/expected/apply-payload.js", "utf8").split("\n");
const current = golden.filter((l) => l.startsWith("  const PAYLOAD = JSON.parse("));
console.log("golden PAYLOAD lines:", current.length);
console.log("OLD reproduces golden:", current[0] === line(old));
console.log("NEW " + line(stamped));
// Round trip: the NEW literal parses back to the stamped payload.
const literal = line(stamped).slice("  const PAYLOAD = JSON.parse(".length, -2);
console.log("NEW round-trips:", JSON.stringify(JSON.parse(JSON.parse(literal))) === JSON.stringify(stamped));
