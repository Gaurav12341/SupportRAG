import { NextResponse } from "next/server";
import { COOKIE } from "@/lib/server";

/** A page found its token refused (expired, or the user was removed): drop the cookie and go to sign in. */
export async function GET(req: Request) {
  const out = NextResponse.redirect(new URL("/login?expired=1", req.url));
  out.cookies.set(COOKIE, "", { httpOnly: true, sameSite: "lax", path: "/", maxAge: 0 });
  return out;
}
