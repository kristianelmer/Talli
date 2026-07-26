import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@talli/talli-api-client"],
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
