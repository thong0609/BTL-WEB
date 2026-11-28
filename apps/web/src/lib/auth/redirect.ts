// Chooses where to send the user after login. The target comes from the URL, so it is untrusted:
// only a path inside this site is allowed, anything else becomes the fallback.

const MAX_LENGTH = 2048;
// Used only to resolve the path the way a browser would. The host is never part of the result.
// A path starting with a single "/" always stays on this base, so no separate origin check.
const BASE = "http://redirect.invalid";
// Never send a user straight back to the login or register pages (redirect loop).
const AUTH_PAGES = ["/login", "/register"];

function isAuthPage(pathname: string): boolean {
  return AUTH_PAGES.some((page) => pathname === page || pathname.startsWith(`${page}/`));
}

export function safeRedirectPath(raw: string | null | undefined, fallback = "/"): string {
  if (typeof raw !== "string" || raw.length > MAX_LENGTH) return fallback;
  // Must start with a single "/". Backslashes and control characters are rejected outright:
  // browsers treat "\" like "/" and silently drop tabs and newlines, which can turn
  // "/\evil.com" or "/<tab>/evil.com" into "//evil.com".
  if (raw[0] !== "/" || raw[1] === "/" || raw.includes("\\")) return fallback;
  if (/[\u0000-\u001f\u007f]/.test(raw)) return fallback;

  let url: URL;
  try {
    url = new URL(raw, BASE);
  } catch {
    return fallback;
  }
  // Dot segments are resolved by the parser: "/..//evil.com" becomes "//evil.com", so check again.
  const target = `${url.pathname}${url.search}${url.hash}`;
  if (target.startsWith("//")) return fallback;
  if (isAuthPage(url.pathname)) return fallback;
  return target;
}
