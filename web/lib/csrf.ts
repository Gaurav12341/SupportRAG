// Cross-site request forgery guard for the routes that change something.
// A page on another site cannot set a custom header without our permission (we send no CORS headers), and the cookie is SameSite=Lax.
// We also refuse a request whose Origin is not this site.
export const CSRF_HEADER = "x-requested-with";
export const CSRF_VALUE = "supportrag";

export function csrfOk(req: Request): boolean {
  if (req.headers.get(CSRF_HEADER) !== CSRF_VALUE) return false;
  const origin = req.headers.get("origin");
  if (origin === null) return true;
  try {
    return new URL(origin).host === req.headers.get("host"); // the host the browser used, not the one the server believes it has
  } catch {
    return false;
  }
}
