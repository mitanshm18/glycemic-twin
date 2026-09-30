import { NextResponse, type NextRequest } from "next/server";

/**
 * Cheap gate: without a session cookie, app pages redirect to /login. The cookie itself is
 * validated by the API on every request (an expired one yields 401 and the client redirects).
 */
const COOKIE = process.env.TWIN_COOKIE_NAME ?? "twin_session";

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (!req.cookies.has(COOKIE)) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/", "/patients/:path*", "/model/:path*"],
};
