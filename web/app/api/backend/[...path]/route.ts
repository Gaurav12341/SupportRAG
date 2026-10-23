import { NextResponse } from "next/server";
import { csrfOk } from "@/lib/csrf";
import { backend, COOKIE } from "@/lib/server";

// Only these backend routes are reachable from the browser. /login goes through app/api/session instead.
const ALLOWED = new Set(["ask", "documents", "metrics", "me", "admin"]);

async function forward(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  if (!ALLOWED.has(path[0])) return NextResponse.json({ detail: "Not found." }, { status: 404 });
  if (req.method !== "GET" && !csrfOk(req)) return NextResponse.json({ detail: "Request refused." }, { status: 403 });
  const url = new URL(req.url);
  const target = `/${path.map(encodeURIComponent).join("/")}${url.search}`;
  const hasBody = req.method !== "GET" && req.method !== "DELETE";
  let res: Response;
  try {
    res = await backend(target, {
      method: req.method,
      headers: hasBody ? { "content-type": "application/json" } : {},
      body: hasBody ? await req.text() : undefined,
    });
  } catch {
    return NextResponse.json({ detail: "The server is not reachable. Is the API running?" }, { status: 503 });
  }
  const out = new NextResponse(await res.text(), { status: res.status, headers: { "content-type": res.headers.get("content-type") ?? "application/json" } });
  if (res.status === 401) out.cookies.set(COOKIE, "", { httpOnly: true, sameSite: "lax", path: "/", maxAge: 0 });
  return out;
}

export { forward as GET, forward as POST, forward as PUT, forward as DELETE };
