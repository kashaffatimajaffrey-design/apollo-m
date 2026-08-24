import { createClient as createSupabaseClient } from "@supabase/supabase-js";

import { SUPABASE_KEY, SUPABASE_URL } from "./env";

/**
 * A Supabase client for public reference data, with no session attached.
 *
 * `community_latest` is world-readable — the pipeline's output, the same rows
 * the Streamlit dashboard and the REST API serve. Reading it through the
 * cookie-bound server client tied that read to the request's session for no
 * reason, and it had a real cost: anything touching cookies is request-scoped,
 * so the whole route had to be rendered dynamically per visitor even though
 * this data only changes when the pipeline runs.
 *
 * Separating the two clients is what lets each read be treated correctly —
 * public data cached across visitors, per-user data never cached. The privilege
 * boundary is unchanged either way: this key can only see what row-level
 * security already allows anonymous callers to see.
 *
 * Safe at module scope, unlike the server client, precisely because it closes
 * over no request state.
 */
export const publicClient = createSupabaseClient(SUPABASE_URL, SUPABASE_KEY, {
  auth: { persistSession: false, autoRefreshToken: false },
});
