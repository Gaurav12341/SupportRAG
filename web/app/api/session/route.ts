import { NextResponse } from "next/server";
import { csrfOk } from "@/lib/csrf";
import { BACKEND, COOKIE, getSession } from "@/lib/server";

const cookieOptions = (maxAge: number) => ({
  httpOnly: true, // page scripts can never read the token
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
  maxAge,
});

export async function GET() {
  const { session, expired } = await getSession();
  return NextResponse.json({ ...session, expired });
}

/** Sign in: the password goes to the backend once; only the token comes back, into an httpOnly cookie. */
export async function POST(req: Request) {
  if (!csrfOk(req)) return NextResponse.json({ detail: "Request refused." }, { status: 403 });
  const { user, password } = (await req.json().catch(() => ({}))) as { user?: string; password?: string };
  if (!user || !password) return NextResponse.json({ detail: "Enter your user name and password." }, { status: 400 });
  let res: Response;
  try {
    res = await fetch(`${BACKEND}/login`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username: user, password }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "The server is not reachable. Is the API running?" }, { status: 503 });
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) return NextResponse.json({ detail: body.detail ?? "Sign in failed." }, { status: res.status === 401 ? 401 : 503 });
  const out = NextResponse.json({ user: body.user, role: body.role, licenses: body.licenses });
  out.cookies.set(COOKIE, body.access_token, cookieOptions(body.expires_in ?? 3600));
  return out;
}

export async function DELETE(req: Request) {
  if (!csrfOk(req)) return NextResponse.json({ detail: "Request refused." }, { status: 403 });
  const out = NextResponse.json({ ok: true });
  out.cookies.set(COOKIE, "", cookieOptions(0));
  return out;
}
