export type Alert = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

/**
 * One row of `public.community_latest`.
 *
 * These fields must match the view's select list exactly. An earlier version
 * declared a `toxicity_trend` column that the view does not return — and,
 * because the type asserted it existed, the compiler was happy while every row
 * rendered `NaN`. A hand-written type that over-promises is worse than no type,
 * so the safest change here is to keep it in step with
 * `web/supabase/schema.sql` whenever that view changes.
 *
 * Nullable where the pipeline may not have produced a value: a community can be
 * scored before the graph model or the instability pass has run for it.
 */
export type Community = {
  subreddit: string;
  community_health_index: number;
  toxicity_rate: number;
  instability_score: number | null;
  gnn_risk: number | null;
  total_comments: number;
  recommended_action: string;
  alert: Alert;
  updated_at: string;
};

export type WatchlistRow = {
  id: string;
  subreddit: string;
  note: string | null;
  created_at: string;
};

/** Tailwind classes per alert band. Kept beside the type so a new band cannot
 *  be added without the compiler pointing here. */
export const ALERT_STYLE: Record<Alert, string> = {
  LOW: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  MEDIUM: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
  HIGH: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  CRITICAL: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
};
