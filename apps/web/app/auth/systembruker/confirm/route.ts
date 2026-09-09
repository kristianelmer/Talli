import { NextResponse } from "next/server.js";
import type { SystemUserResultWire } from "@talli/talli-api-client";
import { SYSTEM_USER_COOKIE, callbackStateForResult } from "../../../lib/system-user-presentation.ts";
import { systemUserCallbackProof } from "../../../lib/authority-callback-transport.ts";

type CallbackCookieStore = {
  get(name: string): { value: string } | undefined;
  delete(options: { name: string; path: string }): void;
};
type SystemUserCallbackDependencies = {
  siteOrigin: string;
  getAccessToken(): Promise<string | null>;
  getCookieStore(): Promise<CallbackCookieStore>;
  createProof(requestId: string, accessToken: string): string;
  reconcileRequest(accessToken: string, requestId: string, proof: string): Promise<SystemUserResultWire>;
};

export function systemUserSiteOrigin(
  environment: Record<string, string | undefined> = process.env,
): string {
  const configured = environment.SITE_URL ?? environment.NEXT_PUBLIC_SITE_URL;
  const candidate = configured ?? (environment.NODE_ENV === "production" ? "" : "http://localhost:3000");
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error("site_origin_invalid");
  }
  const baseIsExact = parsed.username === ""
    && parsed.password === ""
    && parsed.pathname === "/"
    && parsed.search === ""
    && parsed.hash === "";
  const isProductionOrigin = parsed.origin === "https://talli.no";
  const isLocalDevelopmentOrigin = environment.NODE_ENV !== "production"
    && parsed.hostname === "localhost"
    && (parsed.protocol === "http:" || parsed.protocol === "https:");
  if (!baseIsExact || (!isProductionOrigin && !isLocalDevelopmentOrigin)) {
    throw new Error("site_origin_invalid");
  }
  return parsed.origin;
}


function manualRedirect(siteOrigin: string): NextResponse {
  return NextResponse.redirect(new URL("/connections?systembruker=manual", siteOrigin));
}

export function createSystemUserCallbackHandler(dependencies: SystemUserCallbackDependencies) {
  return async function systemUserCallback(_request: Request): Promise<NextResponse> {
    let cookieStore: CallbackCookieStore | null = null;
    try {
      cookieStore = await dependencies.getCookieStore();
      const cookie = cookieStore.get(SYSTEM_USER_COOKIE.name);
      if (!cookie || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(cookie.value)) {
        return manualRedirect(dependencies.siteOrigin);
      }
      const accessToken = await dependencies.getAccessToken();
      if (!accessToken) return manualRedirect(dependencies.siteOrigin);
      const requestId = cookie.value.toLowerCase();
      const proof = dependencies.createProof(requestId, accessToken);
      const result = await dependencies.reconcileRequest(accessToken, requestId, proof);
      if (result.requestId !== requestId || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(result.companyId)) {
        return manualRedirect(dependencies.siteOrigin);
      }
      const destination = new URL("/connections", dependencies.siteOrigin);
      destination.searchParams.set("company", result.companyId);
      destination.searchParams.set("systembruker", callbackStateForResult(result));
      return NextResponse.redirect(destination);
    } catch {
      return manualRedirect(dependencies.siteOrigin);
    } finally {
      cookieStore?.delete({ name: SYSTEM_USER_COOKIE.name, path: SYSTEM_USER_COOKIE.options.path });
    }
  };
}

export async function GET(request: Request) {
  const handler = createSystemUserCallbackHandler({
    siteOrigin: systemUserSiteOrigin(),
    async getAccessToken() {
      const { createSupabaseServerClient } = await import("../../../lib/supabase/server.ts");
      const supabase = await createSupabaseServerClient();
      const { data: { user }, error } = await supabase.auth.getUser();
      if (error || !user) return null;
      const { data: { session } } = await supabase.auth.getSession();
      return session?.access_token ?? null;
    },
    async getCookieStore() {
      const { cookies } = await import("next/headers.js");
      return cookies();
    },
    createProof: systemUserCallbackProof,
    async reconcileRequest(accessToken, requestId, proof) {
      const { reconcileOwnerSystemUserCallback } = await import("../../../../features/authority-connections/index.ts");
      return reconcileOwnerSystemUserCallback(accessToken, requestId, proof);
    },
  });
  return handler(request);
}
