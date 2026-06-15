import type { NextConfig } from "next";

// Static export so the entire SPA can be served by FastAPI in a single
// container. The app is a pure client that talks to the backend over
// same-origin /api and /ws, so no Next server runtime is required.
const nextConfig: NextConfig = {
  output: "export",
  reactStrictMode: true,
  images: { unoptimized: true },
  trailingSlash: false,
};

export default nextConfig;
