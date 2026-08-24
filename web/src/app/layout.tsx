import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { createClient } from "@/lib/supabase/server";
import { signOut } from "./auth/actions";

// Every route reads the session, so nothing here can be prerendered at build
// time. Declaring it on the layout also means `next build` succeeds on a clone
// with no Supabase credentials yet, instead of failing while prerendering.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "APOLLO Watch",
  description:
    "Community instability scores from the APOLLO-M pipeline, served from Supabase Postgres.",
};

/** Server Component: the session is read on the server, so the header is
 *  correct in the first byte of HTML rather than flickering from signed-out to
 *  signed-in once client JavaScript hydrates. */
async function Nav() {
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

  return (
    <header className="border-b border-white/10">
      <nav className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-4">
        <Link href="/" className="font-semibold tracking-tight">
          APOLLO <span className="text-emerald-400">Watch</span>
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
          {user ? (
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
          )}
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
      <body className="min-h-screen bg-[#0b0f14] text-white antialiased">
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
