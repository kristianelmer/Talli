import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingIncludes: {
    "/*": [
      "holding_cli/*.py",
      "holding_core/*.py",
      "docs/filing/aksjonaerregisteroppgaveHovedskjema.xsd",
      "docs/filing/aksjonaerregisteroppgaveUnderskjema.xsd",
    ],
  },
  outputFileTracingExcludes: {
    "/*": [
      "**/__pycache__/**",
      "**/*.pyc",
      ".env*",
      "CONTEXT.md",
      "PLAN.md",
      "docs/**/*.md",
      "docs/**/*.json",
      "tests/**",
      "supabase/**",
      "next.config.ts",
      "pyproject.toml",
      "uv.lock",
    ],
  },
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
