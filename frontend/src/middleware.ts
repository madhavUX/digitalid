import { NextRequest, NextResponse } from "next/server";

const SITE_ROOT = (process.env.BOOKANYTHING_SITE_DOMAIN || "bookanything.in").toLowerCase();
const SUBDOMAIN_RE = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;
const RESERVED = new Set(["www", "app", "api", "admin", "owner", "book", "cdn", "static"]);

/** Pure helper for tests and Host hardening. */
export function resolveSiteSubdomainRewrite(
  hostHeader: string,
  pathname: string,
  siteRoot = SITE_ROOT,
): string | null {
  const host = hostHeader.split(":")[0]?.toLowerCase() || "";
  if (!host.endsWith(`.${siteRoot}`)) {
    return null;
  }

  const sub = host.slice(0, -(siteRoot.length + 1));
  if (!sub || RESERVED.has(sub) || !SUBDOMAIN_RE.test(sub) || sub.includes(".")) {
    return null;
  }

  if (
    pathname.startsWith("/site/") ||
    pathname.startsWith("/book/") ||
    pathname.startsWith("/q/") ||
    pathname.startsWith("/owner/") ||
    pathname.startsWith("/backend/") ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/_next/") ||
    pathname.startsWith("/favicon")
  ) {
    return null;
  }

  if (pathname === "/" || pathname === "") {
    return `/site/${sub}`;
  }

  return null;
}

export function middleware(request: NextRequest) {
  const hostHeader = request.headers.get("host") || "";
  const rewritePath = resolveSiteSubdomainRewrite(hostHeader, request.nextUrl.pathname);
  if (!rewritePath) {
    return NextResponse.next();
  }

  const url = request.nextUrl.clone();
  url.pathname = rewritePath;
  return NextResponse.rewrite(url);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
