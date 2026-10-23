"use client";
// Browser-side calls. They go to this site's /api/backend proxy, never to the FastAPI server directly.
import { CSRF_HEADER, CSRF_VALUE } from "./csrf";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function call<T>(url: string, method: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers: { [CSRF_HEADER]: CSRF_VALUE, ...(body === undefined ? {} : { "content-type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Could not reach the server. Check that it is running.", 0);
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && url.startsWith("/api/backend")) window.location.href = "/api/session/expired";
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : Array.isArray(data.detail) ? "Check the values and try again." : "Something went wrong.";
    throw new ApiError(detail, res.status);
  }
  return data as T;
}

export const api = <T,>(path: string, method = "GET", body?: unknown) => call<T>(`/api/backend/${path}`, method, body);
export const session = {
  signIn: (user: string, password: string) => call<{ user: string; role: string }>("/api/session", "POST", { user, password }),
  signOut: () => call<{ ok: boolean }>("/api/session", "DELETE"),
};
