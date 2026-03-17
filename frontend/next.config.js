/** @type {import('next').NextConfig} */
const nextConfig = {
  /**
   * Rewrite /api/* → backend URL so the frontend can call relative /api/*
   * paths without CORS issues in production.
   *
   * Set NEXT_PUBLIC_API_URL (and BACKEND_URL for server-side rewrites) in your
   * environment or .env.local.
   */
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },

  // Transpile maplibre-gl for Next.js
  transpilePackages: ["maplibre-gl"],

  // Empty turbopack config silences the webpack/turbopack mismatch warning.
  // Node.js module stubs (fs/net/tls) are not needed under Turbopack.
  turbopack: {},
};

module.exports = nextConfig;
