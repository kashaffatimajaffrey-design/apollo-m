import { Suspense } from "react";
import { createClient, hasSupabaseEnv } from "@/lib/supabase/server";
import { addToWatchlist } from "./auth/actions";
import { ALERT_STYLE, type Community } from "@/lib/types";

/**
 * The streaming route.
 *
 * The shell — heading, intro, section frames — is sent immediately. The two
 * data-dependent sections each sit behind their own Suspense boundary, so the
 * server flushes each one as its query finishes instead of holding the whole
 * document until the slowest is done. Two boundaries rather than one is the
 * deliberate part: the summary is a fast aggregate and the table is a larger
 * read, and the fast one should not wait for the slow one.
 *
 * Both fetches run on the server against Supabase Postgres. No data-fetching
 * JavaScript is shipped to the browser, and the anon key is never used to read
 * anything the RLS policies would not allow.
 */

export const dynamic = "force-dynamic";

function Pill({ alert }: { alert: Community["alert"] }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${ALERT_STYLE[alert]}`}
    >
      {alert}
    </span>
  );
}

async function Summary() {
  if (!hasSupabaseEnv())
    return <SetupHint message="No Supabase credentials found." />;
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("community_latest")
    .select("alert, total_comments");

  if (error) return <SetupHint message={error.message} />;

  const rows = data ?? [];
  const comments = rows.reduce((n, r) => n + (r.total_comments ?? 0), 0);
  const critical = rows.filter((r) => r.alert === "CRITICAL").length;
  const high = rows.filter((r) => r.alert === "HIGH").length;

  const cards = [
    { label: "communities", value: rows.length.toLocaleString() },
    { label: "comments scored", value: comments.toLocaleString() },
    { label: "critical", value: String(critical) },
    { label: "high", value: String(high) },
  ];

  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map((c) => (
        <div
          key={c.label}
          className="rounded-lg bg-white/5 p-4 ring-1 ring-white/10"
        >
          <dd className="text-2xl font-semibold tabular-nums">{c.value}</dd>
          <dt className="mt-1 text-xs text-white/50">{c.label}</dt>
        </div>
      ))}
    </dl>
  );
}

async function CommunityTable() {
  if (!hasSupabaseEnv())
    return <SetupHint message="No Supabase credentials found." />;
  const supabase = await createClient();
  const [{ data, error }, { data: watched }] = await Promise.all([
    supabase
      .from("community_latest")
      .select("*")
      .order("community_health_index", { ascending: true })
      .returns<Community[]>(),
    // Returns [] when signed out — the select policy scopes it to auth.uid(),
    // so no branch on the session is needed here.
    supabase.from("watchlist").select("subreddit"),
  ]);

  if (error) return <SetupHint message={error.message} />;
  if (!data?.length)
    return (
      <SetupHint message="No rows yet — point database/db_setup.py at this project." />
    );

  const onList = new Set((watched ?? []).map((w) => w.subreddit));

  return (
    <div className="overflow-x-auto rounded-lg ring-1 ring-white/10">
      <table className="w-full text-sm">
        <thead className="bg-white/5 text-left text-xs uppercase tracking-wide text-white/50">
          <tr>
            <th scope="col" className="px-4 py-3 font-medium">
              Community
            </th>
            <th scope="col" className="px-4 py-3 text-right font-medium">
              Health
            </th>
            <th scope="col" className="px-4 py-3 text-right font-medium">
              Toxicity
            </th>
            <th scope="col" className="px-4 py-3 text-right font-medium">
              Trend
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              Alert
            </th>
            <th scope="col" className="px-4 py-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {data.map((c) => (
            <tr key={c.subreddit} className="hover:bg-white/[0.03]">
              <td className="px-4 py-3 font-medium">{c.subreddit}</td>
              <td className="px-4 py-3 text-right tabular-nums">
                {Number(c.community_health_index).toFixed(1)}
              </td>
              <td className="px-4 py-3 text-right tabular-nums text-white/70">
                {(Number(c.toxicity_rate) * 100).toFixed(1)}%
              </td>
              <td className="px-4 py-3 text-right tabular-nums text-white/70">
                {Number(c.toxicity_trend) > 0 ? "▲" : "▼"}{" "}
                {Math.abs(Number(c.toxicity_trend)).toFixed(4)}
              </td>
              <td className="px-4 py-3">
                <Pill alert={c.alert} />
              </td>
              <td className="px-4 py-3 text-right">
                {onList.has(c.subreddit) ? (
                  <span className="text-xs text-white/30">watching</span>
                ) : (
                  <form action={addToWatchlist}>
                    <input type="hidden" name="subreddit" value={c.subreddit} />
                    <button className="text-xs text-emerald-400 hover:underline">
                      + watch
                    </button>
                  </form>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SetupHint({ message }: { message: string }) {
  return (
    <div className="rounded-lg bg-amber-500/10 p-4 text-sm text-amber-200 ring-1 ring-amber-500/30">
      <p className="font-medium">Supabase is not answering yet.</p>
      <p className="mt-1 text-amber-200/70">{message}</p>
      <p className="mt-2 text-amber-200/70">
        Point <code>database/db_setup.py</code> at this project, then apply{" "}
        <code>web/supabase/schema.sql</code>. See the README.
      </p>
    </div>
  );
}

function Skeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-10 animate-pulse rounded-md bg-white/5" />
      ))}
    </div>
  );
}

export default function Home() {
  return (
    <div className="space-y-10">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">
          Community instability
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-white/60">
          The same rows the Streamlit dashboard and the REST API serve — written
          to Supabase Postgres by the APOLLO-M pipeline, read here on the
          server. 24 real subreddits, worst first. Sign in to keep a watchlist;
          those rows are private, enforced by row-level security rather than by
          this app.
        </p>
      </section>

      {/* Each boundary streams independently: the summary lands as soon as its
          aggregate returns, without waiting for the full table read. */}
      <Suspense fallback={<Skeleton rows={2} />}>
        <Summary />
      </Suspense>

      <Suspense fallback={<Skeleton rows={8} />}>
        <CommunityTable />
      </Suspense>
    </div>
  );
}
