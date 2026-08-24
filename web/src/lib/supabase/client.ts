"use client";

import { createBrowserClient } from "@supabase/ssr";

/**
 * Supabase client for Client Components.
 *
 * Almost everything in this app reads on the server, so this exists for the two
 * things that genuinely cannot: signing out from a button, and reacting to auth
 * state changes without a round trip.
 */
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
