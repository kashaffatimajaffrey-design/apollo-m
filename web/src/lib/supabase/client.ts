"use client";

import { createBrowserClient } from "@supabase/ssr";
import { SUPABASE_KEY, SUPABASE_URL } from "./env";

/**
 * Supabase client for Client Components.
 *
 * Almost everything in this app reads on the server, so this exists for the two
 * things that genuinely cannot: signing out from a button, and reacting to auth
 * state changes without a round trip.
 */
export function createClient() {
  return createBrowserClient(SUPABASE_URL, SUPABASE_KEY);
}
