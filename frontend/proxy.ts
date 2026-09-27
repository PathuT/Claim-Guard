/** Console route guard (Next.js Proxy, Node.js runtime). Every page needs a
 * valid signed session; each role may open only its own pages
 * (lib/auth/roles.ts). The check reads only the signed cookie — no network
 * call — as the Next.js docs recommend for Proxy. Pages re-check the
 * session on the server as well (app/(console)/layout.tsx). */

import { type NextRequest, NextResponse } from "next/server";
import { HOME_FOR_ROLE, canAccess } from "@/lib/auth/roles";
import { SESSION_COOKIE, verifySession } from "@/lib/auth/token";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const session = verifySession(request.cookies.get(SESSION_COOKIE)?.value);

  if (pathname === "/login") {
    return session ? NextResponse.redirect(new URL(HOME_FOR_ROLE[session.role], request.url)) : NextResponse.next();
  }

  if (!session) {
    const url = new URL("/login", request.url);
    if (pathname !== "/") url.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(url);
  }

  if (!canAccess(session.role, pathname)) {
    const url = new URL(HOME_FOR_ROLE[session.role], request.url);
    url.searchParams.set("denied", pathname);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  // Everything except Next.js internals and static files.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
