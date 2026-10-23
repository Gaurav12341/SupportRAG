// Server-only helpers: talk to the FastAPI backend with the login token that lives in an httpOnly cookie.
import { cookies } from "next/headers";
import { cache } from "react";
import type { Session } from "./types";

export const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
export const COOKIE = "sr_token";
export const PUBLIC: Session = { user: null, role: "public", licenses: [] };

export async function backend(path: string, init: RequestInit = {}): Promise<Response> {
  const token = (await cookies()).get(COOKIE)?.value;
  const headers = new Headers(init.headers);
  if (token) headers.set("authorization", `Bearer ${token}`);
  return fetch(`${BACKEND}${path}`, { ...init, headers, cache: "no-store" });
}

/** Who is asking. `expired`: a token was sent and the backend refused it. `down`: the backend could not be reached. */
export const getSession = cache(async (): Promise<{ session: Session; expired: boolean; down: boolean }> => {
  const token = (await cookies()).get(COOKIE)?.value;
  if (!token) return { session: PUBLIC, expired: false, down: false };
  try {
    const res = await backend("/me");
    if (res.status === 401) return { session: PUBLIC, expired: true, down: false };
    if (!res.ok) return { session: PUBLIC, expired: false, down: true };
    return { session: (await res.json()) as Session, expired: false, down: false };
  } catch {
    return { session: PUBLIC, expired: false, down: true };
  }
});

/** JSON from the backend for a server component, or null if it failed (the page then shows its error state). */
export async function load<T>(path: string): Promise<T | null> {
  try {
    const res = await backend(path);
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}
