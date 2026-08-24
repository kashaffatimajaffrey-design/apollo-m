import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Cache Components. Without it, `use cache` in src/lib/data.ts is inert and
  // every visitor re-reads rows that only change when the pipeline runs.
  //
  // Turning it on is what forces the useful distinction in this app: a cached
  // scope cannot touch request state, so public reference data and per-user
  // data have to be fetched through different clients. That separation was
  // worth making regardless — it was previously reading world-readable rows
  // through the caller's session for no reason.
  cacheComponents: true,
};

export default nextConfig;
