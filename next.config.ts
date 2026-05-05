import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // better-sqlite3 = module natif Node, doit rester externe au bundle.
  serverExternalPackages: ["better-sqlite3"],
  // Force le workspace root sur ce repo : sinon Turbopack peut remonter
  // jusqu'à ~/package-lock.json et casser process.cwd() pour le SSR.
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
