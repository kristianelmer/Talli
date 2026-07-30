import { headers } from "next/headers";

/**
 * Resolves the canonical base URL used for auth email links (confirmation,
 * password reset). Email links must point at the stable public origin, never
 * at the local dev server, so an explicit `SITE_URL` (e.g. https://talli.no)
 * takes precedence. Falls back to the Vercel production domain, then the
 * incoming request host, then localhost for dev.
 */
export async function getSiteUrl(): Promise<string> {
  const explicit = process.env.SITE_URL ?? process.env.NEXT_PUBLIC_SITE_URL;
  if (explicit) {
    return explicit.replace(/\/+$/, "");
  }
  const vercelProd = process.env.VERCEL_PROJECT_PRODUCTION_URL;
  if (vercelProd) {
    return `https://${vercelProd}`;
  }
  try {
    const headerStore = await headers();
    const host = headerStore.get("x-forwarded-host") ?? headerStore.get("host");
    if (host) {
      const proto = headerStore.get("x-forwarded-proto") ?? "https";
      return `${proto}://${host}`;
    }
  } catch {
    // headers() is unavailable outside a request scope — fall through.
  }
  return "http://localhost:3000";
}
