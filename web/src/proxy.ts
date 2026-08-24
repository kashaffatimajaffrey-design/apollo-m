import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { SUPABASE_KEY, SUPABASE_URL, isConfigured } from "@/lib/supabase/env";

/**
 * Refresh the Supabase session on every request, and gate the private routes.
 *
 * Access tokens are short-lived. Server Components can read cookies but cannot
 * write them, so without this the refreshed token would never reach the browser
 * and a user would be signed out mid-session. This runs before the render and
 * can write, which makes it the only correct place to do it.
 *
 * Named `proxy` in a `proxy.ts` file: the `middleware.ts` convention is
 * deprecated as of Next.js 16 and renamed to `proxy`. Behaviour is unchanged.
 */

const PROTECTED = ["/watchlist"];

export async function proxy(request: NextRequest) {
  // Nothing to refresh and nothing to gate before the project is configured.
  if (!isConfigured) {
    return NextResponse.next({ request });
  }

  // The response has to be built before the Supabase client, then handed back
  // unchanged: refreshed auth cookies are written onto it as a side effect, and
  // creating a fresh NextResponse afterwards would silently discard them.
  let response = NextResponse.next({ request });

  const supabase = createServerClient(SUPABASE_URL, SUPABASE_KEY, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) =>
          request.cookies.set(name, value),
        );
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options),
        );
      },
    },
  });

  // getUser(), not getSession(): getSession only decodes the cookie, which the
  // client controls. getUser revalidates it against the auth server, so this
  // gate cannot be walked past with a forged cookie.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;
  if (!user && PROTECTED.some((p) => pathname.startsWith(p))) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  return response;
}

export const config = {
  matcher: [
    // Everything except static assets and images — those never carry a session
    // and matching them would run an auth round trip per file.
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
