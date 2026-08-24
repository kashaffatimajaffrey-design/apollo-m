-- APOLLO-M web surface — Supabase schema.
--
-- Run once, AFTER `python database/db_setup.py` has been pointed at this same
-- Supabase instance:
--
--   DATABASE_URL="postgresql://postgres:...@db.<ref>.supabase.co:5432/postgres" \
--     python database/db_setup.py
--
-- That creates the `apollo` schema and loads it with the pipeline's real
-- outputs. Nothing here duplicates that data. This file adds only what the web
-- surface needs on top of it:
--
--   * a read model in `public`, because Supabase's REST layer exposes the
--     `public` schema and the pipeline writes to `apollo`;
--   * a per-user watchlist, which is the one thing the web app owns.
--
-- The Streamlit dashboard, the FastAPI service and this app therefore read the
-- same rows from the same database. There is no copy to fall out of date.

-- ── Read model over the pipeline's output ────────────────────────────────────
-- `apollo.community_health` is append-only: db_setup.py inserts a fresh row per
-- community on every pipeline run, so a plain select returns history as well as
-- current state. DISTINCT ON collapses that to the newest row per community,
-- which is what a dashboard wants.
create or replace view public.community_latest
with (security_invoker = on) as
select distinct on (subreddit)
  subreddit,
  community_health_index,
  toxicity_rate,
  instability_score,
  gnn_risk,
  total_comments,
  recommended_action,
  -- Banded here, not in TypeScript, so every reader — this app, psql, the
  -- Streamlit dashboard — bands a score identically. Thresholds match
  -- apollo-m/dashboard/app.py.
  case
    when community_health_index >= 85 then 'LOW'
    when community_health_index >= 75 then 'MEDIUM'
    when community_health_index >= 65 then 'HIGH'
    else 'CRITICAL'
  end as alert,
  timestamp as updated_at
from apollo.community_health
order by subreddit, timestamp desc;

-- Reference data: readable by anyone, signed in or not. A view is not writable
-- here, so read access is the only access.
grant usage on schema apollo to anon, authenticated;
grant select on apollo.community_health to anon, authenticated;
grant select on public.community_latest to anon, authenticated;

-- ── Private per-user data ────────────────────────────────────────────────────
-- No foreign key to community_latest: it is a view, and a view cannot be
-- referenced. Integrity is not lost — a subreddit that leaves the pipeline
-- simply stops joining, which is the correct behaviour for a bookmark.
create table if not exists public.watchlist (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users (id) on delete cascade,
  subreddit  text not null,
  note       text,
  created_at timestamptz not null default now(),
  unique (user_id, subreddit)
);

alter table public.watchlist enable row level security;

-- One policy per verb, all keyed on auth.uid(). The with-check clause on insert
-- is what stops a user writing a row that claims to belong to someone else.
drop policy if exists "read own watchlist" on public.watchlist;
create policy "read own watchlist"
  on public.watchlist for select
  using (auth.uid() = user_id);

drop policy if exists "add to own watchlist" on public.watchlist;
create policy "add to own watchlist"
  on public.watchlist for insert
  with check (auth.uid() = user_id);

drop policy if exists "update own watchlist" on public.watchlist;
create policy "update own watchlist"
  on public.watchlist for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "remove from own watchlist" on public.watchlist;
create policy "remove from own watchlist"
  on public.watchlist for delete
  using (auth.uid() = user_id);

-- Every watchlist read is "my rows", so user_id leading the index is what makes
-- the RLS predicate an index lookup rather than a scan.
create index if not exists watchlist_user_idx on public.watchlist (user_id, created_at desc);

-- ── Joined read model for the watchlist page ─────────────────────────────────
-- security_invoker = on is the important part: without it the view would run
-- with its owner's rights and hand every user the whole table. With it, the RLS
-- policy above still applies, so this returns only the caller's rows.
create or replace view public.watchlist_detail
with (security_invoker = on) as
select
  w.id,
  w.subreddit,
  w.note,
  w.created_at,
  c.community_health_index,
  c.alert
from public.watchlist w
left join public.community_latest c on c.subreddit = w.subreddit;

grant select on public.watchlist_detail to authenticated;
