import { cacheLife, cacheTag } from "next/cache";

import { getPublicClient } from "@/lib/supabase/public";
import { SUPABASE_URL, isConfigured } from "@/lib/supabase/env";
import type { Community } from "@/lib/types";

/** Cache tag for everything derived from the pipeline's output. */
export const COMMUNITIES_TAG = "communities";

export type CommunitiesResult =
  { ok: true; rows: Community[] } | { ok: false; reason: string; hint: string };

/**
 * Turn a driver error into the one remedy that actually applies.
 *
 * These failures do not have a common fix, and showing the wrong one is worse
 * than showing none: a transport error rendered under "apply schema.sql" sends
 * you to the SQL editor to fix a database that was never the problem. That
 * happened, and it cost an afternoon. The message the driver gives is the only
 * evidence available here, so match on it and say what it actually implies.
 */
function describeFailure(message: string): { reason: string; hint: string } {
  const m = message.toLowerCase();

  // supabase-js reports every transport failure this way. A URL that is
  // malformed throws in the client constructor instead, so reaching here means
  // the URL parsed and its host did not answer — a wrong project ref, or a
  // paused or deleted project.
  if (
    m.includes("fetch failed") ||
    m.includes("enotfound") ||
    m.includes("econnrefused") ||
    m.includes("getaddrinfo")
  )
    return {
      reason: `Could not reach ${SUPABASE_URL || "the Supabase host"}.`,
      hint:
        "That host did not answer. Check NEXT_PUBLIC_SUPABASE_URL against the " +
        "project ref in the Supabase dashboard, and confirm the project is not " +
        "paused. NEXT_PUBLIC_ values are baked in at build time, so redeploy " +
        "after changing one — editing it alone changes nothing.",
    };

  if (m.includes("pgrst205") || m.includes("could not find the table"))
    return {
      reason: message,
      hint:
        "The project answered but has no community_latest. Apply " +
        "web/supabase/schema.sql, then run database/db_setup.py against it.",
    };

  if (m.includes("invalid api key") || m.includes("jwt"))
    return {
      reason: message,
      hint:
        "The host answered and rejected the key. Copy the publishable key from " +
        "the dashboard into NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY and redeploy.",
    };

  return { reason: message, hint: "See the README for setup." };
}

/**
 * The pipeline's current view of every community.
 *
 * `use cache` because this data is wrong to fetch per request: it changes when
 * `database/db_setup.py` runs, which is a handful of times a day at most, and
 * it is identical for every visitor. Without it, each visitor paid a round trip
 * to Postgres to receive bytes the previous visitor had already received.
 *
 * `cacheLife('hours')` matches how the data actually behaves — stale for at
 * most an hour if nothing invalidates it sooner. `cacheTag` is what makes that
 * ceiling a backstop rather than the mechanism: a pipeline run can call
 * `revalidateTag(COMMUNITIES_TAG)` through /api/revalidate and the next request
 * sees fresh rows immediately. Time-based expiry alone would mean either
 * serving stale data or re-fetching constantly.
 *
 * Note it reads through `publicClient`, which carries no cookies. A cached
 * scope cannot touch request state, and this data does not need any — it is the
 * same rows for a signed-out visitor as for a signed-in one. The watchlist,
 * which genuinely is per-user, deliberately does not come through here.
 *
 * Failures are returned, not thrown. Throwing would avoid writing the failure
 * into the cache, which sounds like the better design and is not: a rejection
 * inside a `use cache` scope is reported as a prerender error even when the
 * caller catches it, so any build that could not reach the database would fail
 * instead of deploying. That was measured, not assumed. CI has no credentials
 * by design, so builds have to survive an unreachable backend.
 *
 * The cost is that a failure is cached like any other value, bounded by
 * `cacheLife('hours')`. POST /api/revalidate clears it immediately once the
 * backend is fixed, which is the escape hatch for exactly this case — a
 * redeploy also does it, and after an env-var change a redeploy is required
 * anyway, since NEXT_PUBLIC_ values are inlined at build time.
 */
export async function getCommunities(): Promise<CommunitiesResult> {
  "use cache";
  cacheLife("hours");
  cacheTag(COMMUNITIES_TAG);

  if (!isConfigured)
    return {
      ok: false,
      reason: "No Supabase credentials found.",
      hint: "Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY.",
    };

  const { data, error } = await getPublicClient()
    .from("community_latest")
    // One literal rather than a concatenation: supabase-js infers the row type
    // from the select string, and a runtime-built string erases that inference.
    .select(
      "subreddit, community_health_index, toxicity_rate, instability_score, gnn_risk, total_comments, recommended_action, alert, updated_at",
    )
    .order("community_health_index", { ascending: true })
    .returns<Community[]>();

  if (error) return { ok: false, ...describeFailure(error.message) };
  return { ok: true, rows: data ?? [] };
}
