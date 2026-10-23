// Text written by the model or taken from the docs is DATA. It is shown as plain text, inline `code`, bold and fenced code only:
// no images (the browser would fetch them), no links (a poisoned passage could point anywhere), no HTML. React escapes every string it renders.
export type Piece = { kind: "text" | "code" | "bold"; text: string };
export type Block = { kind: "paragraph"; pieces: Piece[] } | { kind: "code"; text: string };

const IMG = /!\[[^\]]*\]\([^)]*\)/g;
const LINK = /\[([^\]]*)\]\([^)]*\)/g;
const TAG = /<[^>]{1,200}>/g;

const NAMED: Record<string, string> = { quot: '"', amp: "&", lt: "<", gt: ">", apos: "'", nbsp: " " };

/** Some imported titles still carry HTML entities (`&quot;`). Decode them AFTER tags are stripped; React escapes the result on render. */
function decode(text: string): string {
  return text.replace(/&(#\d{1,6}|#x[0-9a-f]{1,5}|[a-z]{2,6});/gi, (whole, body: string) => {
    if (body[0] !== "#") return NAMED[body.toLowerCase()] ?? whole;
    const code = body[1].toLowerCase() === "x" ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
    return code > 31 && code < 0x110000 ? String.fromCodePoint(code) : whole;
  });
}

export function clean(text: string): string {
  return decode((text ?? "").replace(IMG, "").replace(LINK, "$1").replace(TAG, ""));
}

function inline(line: string): Piece[] {
  const out: Piece[] = [];
  for (const part of line.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g)) {
    if (!part) continue;
    if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) out.push({ kind: "code", text: part.slice(1, -1) });
    else if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) out.push({ kind: "bold", text: part.slice(2, -2) });
    else out.push({ kind: "text", text: part });
  }
  return out;
}

/** Split text into paragraphs and fenced code. Fences are found first, so a tag-like string inside code is kept as code text. */
export function parse(text: string): Block[] {
  const blocks: Block[] = [];
  (text ?? "").split(/```[^\n`]*\n?/).forEach((chunk, i) => {
    if (i % 2 === 1) {
      if (chunk.trim()) blocks.push({ kind: "code", text: chunk.replace(/\n$/, "") });
      return;
    }
    for (const para of clean(chunk).split(/\n{2,}/)) if (para.trim()) blocks.push({ kind: "paragraph", pieces: inline(para.trim()) });
  });
  return blocks;
}

/** A documentation URL is shown as a link only if it is plain https. */
export function safeUrl(url: string): string | null {
  try {
    const u = new URL(url);
    return u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}
