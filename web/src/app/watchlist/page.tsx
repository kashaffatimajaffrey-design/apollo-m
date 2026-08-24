import { Suspense } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { removeFromWatchlist } from "../auth/actions";
import { ALERT_STYLE, type Alert } from "@/lib/types";

/**
 * The private route. Two independent things keep it private:
 *
 *  1. middleware.ts redirects a signed-out visitor to /login before this
 *     renders — a user-experience guard.
 *  2. The row-level security policy on public.watchlist scopes every select to
 *     auth.uid() — the actual security guard. Even if the redirect were removed
 *     tomorrow, this query would return an empty set rather than someone
 *     else's rows.
 */

type Joined = {
  id: string;
  subreddit: string;
  created_at: string;
  community_health_index: number | null;
  alert: Alert | null;
};

/**
 * Everything on this route depends on who is asking, so all of it is
 * request-bound — but the heading and frame are not, and there is no reason to
 * hold those back while Postgres answers.
 *
 * Cache Components rejects `dynamic = "force-dynamic"`, and rightly: it was a
 * blunt instrument that marked the whole route dynamic rather than saying which
 * part actually was. A Suspense boundary says the same thing precisely, and
 * gets the shell to the browser first as a side effect.
 */
export default function WatchlistPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Your watchlist
        </h1>
        <p className="mt-2 text-sm text-white/60">
          These rows are yours alone — the database refuses to return anyone
          else&apos;s, whatever this page asks for.
        </p>
      </div>
      <Suspense
        fallback={
          <p className="rounded-lg bg-white/5 p-6 text-sm text-white/40 ring-1 ring-white/10">
            Loading your watchlist…
          </p>
        }
      >
        <WatchlistBody />
      </Suspense>
    </div>
  );
}

async function WatchlistBody() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { data, error } = await supabase
    // watchlist_detail is declared security_invoker, so the RLS policy on the
    // underlying table still applies and this returns only the caller's rows.
    .from("watchlist_detail")
    .select("id, subreddit, created_at, community_health_index, alert")
    .order("created_at", { ascending: false })
    .returns<Joined[]>();

  return (
    <div className="space-y-6">
      <p className="text-sm text-white/40">Signed in as {user?.email}.</p>

      {error && (
        <p className="rounded-lg bg-amber-500/10 p-4 text-sm text-amber-200 ring-1 ring-amber-500/30">
          {error.message}
        </p>
      )}

      {!error && !data?.length && (
        <p className="rounded-lg bg-white/5 p-6 text-sm text-white/60 ring-1 ring-white/10">
          Nothing here yet.{" "}
          <Link href="/" className="text-emerald-400 hover:underline">
            Pick a community
          </Link>{" "}
          to start watching.
        </p>
      )}

      <ul className="space-y-2">
        {data?.map((row) => (
          <li
            key={row.id}
            className="flex items-center gap-4 rounded-lg bg-white/5 px-4 py-3 ring-1 ring-white/10"
          >
            <span className="font-medium">{row.subreddit}</span>
            {row.alert && (
              <>
                <span className="tabular-nums text-sm text-white/60">
                  {Number(row.community_health_index).toFixed(1)}
                </span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${ALERT_STYLE[row.alert]}`}
                >
                  {row.alert}
                </span>
              </>
            )}
            <form action={removeFromWatchlist} className="ml-auto">
              <input type="hidden" name="id" value={row.id} />
              <button className="text-xs text-white/40 hover:text-rose-300">
                Remove
              </button>
            </form>
          </li>
        ))}
      </ul>
    </div>
  );
}
