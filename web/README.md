# APOLLO-M — web surface

The public web surface of [APOLLO-M](../README.md), built with the Next.js App Router
on Supabase.

**Live: [apollo-m.vercel.app](https://apollo-m.vercel.app)**

It is not a separate product and it does not hold its own copy of anything. The
pipeline writes community health scores to Postgres; the Streamlit analyst dashboard,
the FastAPI service and this app all read the same rows from the same database. This
app is the surface built for people who are not analysts — public, server-rendered,
and fast on a cold visit.

## Why this exists alongside the Streamlit dashboard

They answer different questions. Streamlit is an analyst tool: dense, stateful, behind
a login, and it needs a Python server per session. This is a public read surface —
server-rendered HTML with no data-fetching JavaScript, so it is indexable, works before
hydration, and costs nothing per idle visitor.

## What it demonstrates

**Server Components by default.** Every read runs on the server. The browser is sent no
data-fetching JavaScript and never holds a database client. The header knows whether you
are signed in before the first byte of HTML, so there is no signed-out flash while
hydration catches up.

**Streaming, in two independent boundaries.** `src/app/page.tsx` sends the page shell
immediately and puts the summary and the table behind separate `<Suspense>` boundaries,
so each flushes when its own query returns rather than the fast one waiting on the slow
one. Measured with a 1.5 s delay injected into the table query:

```
first byte: 0.050s    total: 1.573s
```

The initial HTML contains `<!--$?-->`, `<template id="B:0">` and the `$RC(` resolution
script — React's out-of-order Suspense machinery, not a spinner swapped in on the client.

**Auth as Server Actions.** Sign-in is a plain `<form>` posting to a Server Action, so it
works before any JavaScript loads and the session cookie is written by the server.
`useActionState` and `useFormStatus` only add pending state and inline errors on top of a
form that already worked. A Playwright test renders the page with JavaScript disabled to
keep that true.

**Session refresh in `proxy.ts`.** Access tokens are short-lived, and Server Components
can read cookies but not write them — so a refreshed token would never reach the browser
without something that runs before the render and can write. Note the filename:
`middleware.ts` is deprecated as of Next.js 16 and renamed to `proxy.ts`.

**A read model over the pipeline's write model.** `apollo.community_health` is
append-only — one row per community per pipeline run. `public.community_latest` is a
`DISTINCT ON` view that collapses it to current state and bands the alert level in SQL,
so this app, `psql` and the Streamlit dashboard all band a score identically.

**RLS is the security boundary, not the app.** The view is world-readable.
`public.watchlist` is scoped to `auth.uid()` by four policies, one per verb. The
watchlist route is also gated in `proxy.ts`, but that is a user-experience guard: delete
it and the query still returns an empty set rather than someone else's rows.
`watchlist_detail` is declared `security_invoker = on` — without that, the view would run
with its owner's rights and hand every user the whole table.

`supabase/schema.sql` validates against the real PostgreSQL grammar (`pglast`): 17
statements, 2 views, 5 policies.

## Running it

```bash
npm install
cp .env.example .env.local     # from Supabase → Settings → API
```

1. Create a project at [supabase.com](https://supabase.com).
2. Load the pipeline's output into it — this is the step that makes the data shared
   rather than copied:

   ```bash
   cd ..
   DATABASE_URL="postgresql://postgres.<ref>:PASSWORD@aws-1-<region>.pooler.supabase.com:5432/postgres" \
     python database/db_setup.py
   ```

   Copy that string from **Connect → Session pooler** in the Supabase dashboard.
   Which connection you pick matters:

   - The **direct** connection (`db.<ref>.supabase.co:5432`) resolves to IPv6 only.
     It works on a machine that has IPv6 and fails everywhere else, which makes it
     a poor default even though the dashboard shows it first.
   - The **session** pooler is the IPv4 drop-in, and it is what this step needs.
     `db_setup.py` sets `search_path` on the connection so the unqualified
     `CREATE TABLE`s in `database/schema.sql` land in the `apollo` schema, and that
     is session state.
   - The **transaction** pooler (port 6543) returns the connection to the pool after
     every transaction, so session state is not guaranteed to survive between them.
     It is the right choice for short-lived serverless queries, not for this.

3. Run `supabase/schema.sql` in the Supabase SQL editor. It adds the read model and the
   watchlist on top of what step 2 created.
4. `npm run dev`

Without credentials the app still boots and every route renders; the data sections
explain what is missing instead of throwing. That is what CI exercises.

## Checks

```bash
npm run format:check   # Prettier
npm run lint           # ESLint
npx tsc --noEmit       # type safety
npm run build          # production build
npm run test:e2e       # Playwright smoke, incl. a no-JavaScript render
```

All five run in GitHub Actions on every push that touches `web/`, with no secrets in the
runner.

## Stack

Next.js 16 (App Router, Turbopack) · React 19 · TypeScript · Tailwind CSS 4 · Supabase
(Postgres, Auth, RLS) · Playwright · Prettier
