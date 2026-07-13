import type { NextConfig } from "next";

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "connect-src 'self' https://*.supabase.co wss://*.supabase.co",
  "font-src 'self' data:",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "img-src 'self' data: blob:",
  "manifest-src 'self'",
  "media-src 'self' blob:",
  "object-src 'none'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "worker-src 'self' blob:",
].join("; ");

export const applicationSecurityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(), payment=(), usb=()" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  ...(process.env.NODE_ENV === "production"
    ? [{ key: "Strict-Transport-Security", value: "max-age=31536000" }]
    : []),
];

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    serverActions: {
      bodySizeLimit: "7mb",
    },
  },
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
  async headers() {
    return [{ source: "/(.*)", headers: applicationSecurityHeaders }];
  },
};

export default nextConfig;
