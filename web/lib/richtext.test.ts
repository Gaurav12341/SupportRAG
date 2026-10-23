import assert from "node:assert/strict";
import { test } from "node:test";
import { clean, parse, safeUrl } from "./richtext.ts";

test("images, links and html tags are removed before anything is shown", () => {
  const out = clean("Cause: ![x](http://evil/p.png?d=1) see [here](http://evil) <script>x</script>");
  assert.ok(!out.includes("evil") && !out.includes("<script>"));
  assert.ok(out.includes("see here"));
});

test("html entities in imported titles are decoded, and decoding cannot bring a tag back", () => {
  assert.equal(clean("&quot;No Such File&quot; &amp; more &#39;x&#39;"), `"No Such File" & more 'x'`);
  assert.equal(clean("&lt;script&gt; stays text"), "<script> stays text"); // React escapes it when rendered; it is never inserted as HTML
  assert.equal(clean("&unknown; &#0;"), "&unknown; &#0;");
});

test("inline code, bold and fenced code become pieces, never markup", () => {
  const blocks = parse("Run `VACUUM` and **wait**.\n\n```sql\nSELECT 1;\n```\n\nDone");
  assert.deepEqual(blocks[0], {
    kind: "paragraph",
    pieces: [
      { kind: "text", text: "Run " },
      { kind: "code", text: "VACUUM" },
      { kind: "text", text: " and " },
      { kind: "bold", text: "wait" },
      { kind: "text", text: "." },
    ],
  });
  assert.deepEqual(blocks[1], { kind: "code", text: "SELECT 1;" });
  assert.equal(blocks.length, 3);
});

test("a tag-like string inside a code fence stays code text", () => {
  assert.deepEqual(parse("```\n<b>not html</b>\n```"), [{ kind: "code", text: "<b>not html</b>" }]);
});

test("only https documentation urls become links", () => {
  assert.equal(safeUrl("https://kubernetes.io/docs/"), "https://kubernetes.io/docs/");
  for (const bad of ["javascript:alert(1)", "http://x.test", "data:text/html,hi", "not a url", ""]) assert.equal(safeUrl(bad), null);
});
