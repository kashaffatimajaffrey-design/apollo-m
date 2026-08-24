import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { SUPABASE_KEY, SUPABASE_URL, isConfigured } from "./env";

/**
 * Supabase client for Server Components, Server Actions and Route Handlers.
 *
 * A new client is created per request rather than shared at module scope: it
 * closes over that request's cookies, so a cached instance would serve one
 * user's session to whoever arrived next.
 *
 * Server Components cannot set cookies — only Server Actions and Route Handlers
 * can — so the setAll path is allowed to fail silently there. Session refresh is
 * handled once per request in middleware.ts, which can write, so nothing is lost.
 */
/**
 * Whether the project is wired to a Supabase instance yet. A fresh clone has no
 * .env.local, and a blank page with a stack trace is a poor first run — callers
 * check this and render setup instructions instead.
 */
export function hasSupabaseEnv() {
  return Boolean(isConfigured);
}

export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(SUPABASE_URL, SUPABASE_KEY, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options),
          );
        } catch {
          // Called from a Server Component. Middleware already refreshed the
          // session for this request, so there is nothing to recover from.
        }
      },
    },
  });
}
