import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { createClient } from "@/lib/supabase/server";
import { signOut } from "./auth/actions";

export const metadata: Metadata = {
  title: "APOLLO-M — Community Instability",
  description:
    "Community instability scores from the APOLLO-M pipeline, served from Supabase Postgres.",
};

/**
 * The only part of the chrome that depends on who is asking.
 *
 * Reading the session touches cookies, which makes this scope request-bound.
 * Isolating it is what lets everything around it — the whole nav frame, the
 * page shell, the footer — be prerendered once and reused, while this streams
 * in per visitor. Before Cache Components the layout carried
 * `dynamic = "force-dynamic"`, which pinned every route to per-request
 * rendering for the sake of these two elements.
 *
 * Still a Server Component: the session is resolved on the server, so the
 * header arrives correct rather than flickering signed-out to signed-in on
 * hydration.
 */
async function SessionControls() {
  // A missing or wrong Supabase config should degrade to the signed-out header,
  // not a 500 on every route. The page body reports the real problem.
  let user = null;
  try {
    const supabase = await createClient();
    ({
      data: { user },
    } = await supabase.auth.getUser());
  } catch {
    user = null;
  }

  return user ? (
    <>
      <span className="text-white/40">{user.email}</span>
      <form action={signOut}>
        <button className="rounded-md px-3 py-1.5 ring-1 ring-white/15 hover:bg-white/5">
          Sign out
        </button>
      </form>
    </>
  ) : (
    <Link
      href="/login"
      className="rounded-md bg-emerald-500 px-3 py-1.5 font-medium text-black hover:bg-emerald-400"
    >
      Sign in
    </Link>
  );
}

function Nav() {
  return (
    <header className="border-b border-white/10">
      <nav className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-4">
        <Link href="/" className="font-semibold tracking-tight">
          APOLLO<span className="text-emerald-400">-M</span>
        </Link>
        <Link href="/" className="text-sm text-white/60 hover:text-white">
          Communities
        </Link>
        <Link
          href="/watchlist"
          className="text-sm text-white/60 hover:text-white"
        >
          Watchlist
        </Link>
        <div className="ml-auto flex items-center gap-3 text-sm">
          {/* Reserves the button's height so the nav does not shift when the
              session resolves. */}
          <Suspense
            fallback={
              <span
                className="h-[34px] w-20 rounded-md bg-white/5"
                aria-hidden="true"
              />
            }
          >
            <SessionControls />
          </Suspense>
        </div>
      </nav>
    </header>
  );
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      {/* Background and text colour come from globals.css, which owns the
          palette — setting them here as well gave two sources of truth, and the
          stylesheet silently won. */}
      <body className="min-h-screen antialiased">
        <Nav />
        <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
        <footer className="mx-auto max-w-5xl px-6 pb-10 text-xs text-white/30">
          <p>
            One of three surfaces on the same APOLLO-M database. This one is
            Next.js App Router with React Server Components, reading Supabase
            Postgres through row-level security.
          </p>
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            <a
              className="hover:text-white/60"
              href="https://apollo-m.streamlit.app"
              target="_blank"
              rel="noreferrer"
            >
              Analyst dashboard (Streamlit) ↗
            </a>
            <a
              className="hover:text-white/60"
              href="https://apollo-api-tllm.onrender.com/docs"
              target="_blank"
              rel="noreferrer"
            >
              REST API ↗
            </a>
            <a
              className="hover:text-white/60"
              href="https://cerebro-sandy-beta.vercel.app"
              target="_blank"
              rel="noreferrer"
            >
              CEREBRO ↗
            </a>
            <a
              className="hover:text-white/60"
              href="https://github.com/kashaffatimajaffrey-design/apollo-m"
              target="_blank"
              rel="noreferrer"
            >
              Source ↗
            </a>
          </p>
        </footer>
      </body>
    </html>
  );
}
