export type Alert = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type Community = {
  subreddit: string;
  community_health_index: number;
  toxicity_rate: number;
  toxicity_trend: number;
  instability_score: number;
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
