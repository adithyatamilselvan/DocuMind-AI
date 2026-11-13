import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE = "documind_session";
const AUTH_PAGES = ["/login", "/register", "/forgot-password"];

/**
 * Optimistic redirect only (cookie presence). The backend is the real authorization
 * boundary and rejects invalid/expired sessions on every API call.
 * `/api` is excluded from the matcher so large uploads stream straight to FastAPI
 * instead of being buffered (and truncated at 10MB) by the proxy layer.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.has(SESSION_COOKIE);
  const isAuthPage = AUTH_PAGES.some((p) => pathname === p);
  const isPublic = isAuthPage || pathname === "/reset-password" || pathname === "/verify-email";

  if (!hasSession && !isPublic) {
    const url = new URL("/login", request.url);
    if (pathname !== "/") url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  if (hasSession && isAuthPage && request.nextUrl.searchParams.has("expired")) {
    // The API rejected this session; drop the stale HttpOnly cookie to avoid a redirect loop.
    const res = NextResponse.next();
    res.cookies.delete(SESSION_COOKIE);
    res.cookies.delete("documind_csrf");
    return res;
  }
  if (hasSession && isAuthPage) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
