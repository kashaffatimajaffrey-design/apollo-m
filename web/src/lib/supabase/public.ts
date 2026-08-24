import { createClient as createSupabaseClient } from "@supabase/supabase-js";

import { SUPABASE_KEY, SUPABASE_URL } from "./env";

/**
 * A Supabase client for public reference data, with no session attached.
 *
 * `community_latest` is world-readable — the pipeline's output, the same rows
 * the Streamlit dashboard and the REST API serve. Reading it through the
 * cookie-bound server client tied that read to the request's session for no
 * reason, and it had a real cost: anything touching cookies is request-scoped,
 * so the whole route had to be rendered per visitor even though this data only
 * changes when the pipeline runs.
 *
 * Separating the two clients is what lets each read be treated correctly —
 * public data cached across visitors, per-user data never cached. The privilege
 * boundary is unchanged either way: this key can only see what row-level
 * security already allows anonymous callers to see.
 *
 * Built on first use rather than at module scope. `createClient("", "")` throws
 * "supabaseUrl is required", and with Cache Components the build prerenders
 * these routes — so a module-scope client turned a missing environment variable
 * into a failed build rather than the degraded page the app is designed to
 * show. CI has no Supabase credentials by design, which is exactly the case
 * that has to keep working.
 *
 * Memoised because it closes over no request state, so one instance is correct
 * for every caller.
 */
let cached: ReturnType<typeof createSupabaseClient> | null = null;

export function getPublicClient() {
  if (!cached) {
    cached = createSupabaseClient(SUPABASE_URL, SUPABASE_KEY, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
  }
  return cached;
}
