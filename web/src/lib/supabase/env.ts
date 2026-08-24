/**
 * Supabase connection details, resolved once and shared by the browser, server
 * and proxy clients.
 *
 * Two key formats are in circulation. Supabase is moving from the legacy `anon`
 * JWT to publishable keys (`sb_publishable_...`), and the dashboard now
 * recommends the latter, so that is preferred here with the JWT as a fallback —
 * a project created before the change keeps working, and one created after it
 * does not need a legacy key issued just to run this app.
 *
 * Either is safe to ship to a browser. The authorisation boundary is row-level
 * security in the database, not secrecy of the key.
 */

export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";

export const SUPABASE_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??
  "";

/**
 * Whether the app has enough to talk to Supabase at all.
 *
 * Checked before constructing a client rather than letting it throw, so a clone
 * with no credentials renders and explains itself instead of returning a 500.
 * That is also what CI exercises, since the runner has no secrets.
 */
export const isConfigured = Boolean(SUPABASE_URL && SUPABASE_KEY);
