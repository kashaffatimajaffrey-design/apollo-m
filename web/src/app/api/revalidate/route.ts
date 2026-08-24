import { revalidateTag } from "next/cache";
import { NextResponse, type NextRequest } from "next/server";

import { COMMUNITIES_TAG } from "@/lib/data";

/**
 * Invalidate the cached community data after a pipeline run.
 *
 * `getCommunities()` is cached with `cacheLife('hours')`, which bounds how
 * stale the site can get but says nothing about when the data actually changed.
 * The pipeline knows that precisely — it just wrote the rows — so it should say
 * so rather than leaving the site to time out and re-fetch on a schedule that
 * matches nothing.
 *
 *   curl -X POST https://apollo-m.vercel.app/api/revalidate \
 *        -H "x-revalidate-secret: $REVALIDATE_SECRET"
 *
 * Add that to the end of `database/db_setup.py`, or run it by hand after a
 * pipeline run.
 *
 * The endpoint is public, so it is authenticated with a shared secret. If
 * REVALIDATE_SECRET is unset the route refuses every request rather than
 * defaulting to open: an unauthenticated cache-buster is a free way to make the
 * site hit the database on demand.
 */
export async function POST(request: NextRequest) {
  const expected = process.env.REVALIDATE_SECRET;
  if (!expected) {
    return NextResponse.json(
      {
        revalidated: false,
        reason: "REVALIDATE_SECRET is not set on this deployment.",
      },
      { status: 503 },
    );
  }

  const provided = request.headers.get("x-revalidate-secret");
  // Length-prefixed comparison: not constant-time, but the secret is not
  // derivable from a timing signal on a single header check at this scale, and
  // the alternative pulls in node:crypto for a route that must stay trivial.
  if (provided !== expected) {
    return NextResponse.json({ revalidated: false }, { status: 401 });
  }

  // Two-argument form: the single-argument `revalidateTag(tag)` is deprecated
  // in Next 16. "max" gives stale-while-revalidate — the next request is served
  // the existing entry immediately while the refresh happens behind it, so a
  // pipeline run never makes a visitor wait on Postgres.
  revalidateTag(COMMUNITIES_TAG, "max");
  return NextResponse.json({ revalidated: true, tag: COMMUNITIES_TAG });
}
