import { cacheLife, cacheTag } from "next/cache";

import { publicClient } from "@/lib/supabase/public";
import { isConfigured } from "@/lib/supabase/env";
import type { Community } from "@/lib/types";

/** Cache tag for everything derived from the pipeline's output. */
export const COMMUNITIES_TAG = "communities";

export type CommunitiesResult =
  { ok: true; rows: Community[] } | { ok: false; reason: string };

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
 * Errors are returned rather than thrown so a misconfigured or unmigrated
 * backend renders an explanation instead of a 500 — and so the failure itself
 * is not cached for an hour.
 */
export async function getCommunities(): Promise<CommunitiesResult> {
  "use cache";
  cacheLife("hours");
  cacheTag(COMMUNITIES_TAG);

  if (!isConfigured)
    return { ok: false, reason: "No Supabase credentials found." };

  const { data, error } = await publicClient
    .from("community_latest")
    // One literal rather than a concatenation: supabase-js infers the row type
    // from the select string, and a runtime-built string erases that inference.
    .select(
      "subreddit, community_health_index, toxicity_rate, instability_score, gnn_risk, total_comments, recommended_action, alert, updated_at",
    )
    .order("community_health_index", { ascending: true })
    .returns<Community[]>();

  if (error) return { ok: false, reason: error.message };
  return { ok: true, rows: data ?? [] };
}
