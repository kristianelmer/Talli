import { NextResponse } from "next/server.js";

import {
  SYSTEM_USER_COOKIE,
  callbackStateForResult,
  createProductionSystemUserFlowDependencies,
  reconcileSystemUserRequest,
  systemUserRequestRecordFromRow,
  type SystemUserFlowResult,
} from "../../../lib/system-user-flow.ts";
type CallbackSupabaseClient = any;
type CallbackCookieStore = {
  get(name: string): { value: string } | undefined;
  delete(options: { name: string; path: string }): void;
};

type SystemUserCallbackDependencies = {
  siteOrigin: string;
  createSupabaseClient(): Promise<CallbackSupabaseClient>;
  getCookieStore(): Promise<CallbackCookieStore>;
  reconcileRequest(input: {
    supabase: CallbackSupabaseClient;
    request: Record<string, unknown>;
    orgNumber: string;
  }): Promise<SystemUserFlowResult>;
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

async function defaultReconcileRequest(input: {
  supabase: CallbackSupabaseClient;
  request: Record<string, unknown>;
  orgNumber: string;
}): Promise<SystemUserFlowResult> {
  const { createSupabaseServiceRoleClient } = await import("../../../lib/supabase/server.ts");
  const service = createSupabaseServiceRoleClient();
  const request = systemUserRequestRecordFromRow(input.request, input.orgNumber);
  const dependencies = createProductionSystemUserFlowDependencies({
    ownerClient: input.supabase as any,
    serviceClient: service as any,
    orgNumber: input.orgNumber,
  });
  return reconcileSystemUserRequest(dependencies, request);
}

export function createSystemUserCallbackHandler(
  dependencies: SystemUserCallbackDependencies,
) {
  return async function systemUserCallback(_request: Request): Promise<NextResponse> {
    let cookieStore: CallbackCookieStore | null = null;
    try {
      cookieStore = await dependencies.getCookieStore();
      const cookie = cookieStore.get(SYSTEM_USER_COOKIE.name);
      if (!cookie || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(cookie.value)) {
        return manualRedirect(dependencies.siteOrigin);
      }

      const supabase = await dependencies.createSupabaseClient();
      const { data: { user }, error: userError } = await supabase.auth.getUser();
      if (userError || !user) return manualRedirect(dependencies.siteOrigin);

      const { data: request, error: requestError } = await supabase
        .from("system_user_requests")
        .select("id,company_id,initiating_owner_user_id,obligation,external_ref,altinn_request_id,status,confirm_url,preflight_verified_at,failure_code")
        .eq("id", cookie.value)
        .eq("initiating_owner_user_id", user.id)
        .maybeSingle();
      if (
        requestError
        || !request
        || request.id !== cookie.value
        || request.initiating_owner_user_id !== user.id
      ) {
        return manualRedirect(dependencies.siteOrigin);
      }

      const { data: company, error: companyError } = await supabase
        .from("companies")
        .select("id,org_number")
        .eq("id", request.company_id)
        .maybeSingle();
      if (companyError || !company || company.id !== request.company_id) {
        return manualRedirect(dependencies.siteOrigin);
      }

      const result = await dependencies.reconcileRequest({
        supabase,
        request,
        orgNumber: company.org_number,
      });
      if (result.companyId !== request.company_id || result.requestId !== request.id) {
        return manualRedirect(dependencies.siteOrigin);
      }
      const destination = new URL("/connections", dependencies.siteOrigin);
      destination.searchParams.set("company", result.companyId);
      destination.searchParams.set("systembruker", callbackStateForResult(result));
      return NextResponse.redirect(destination);
    } catch {
      return manualRedirect(dependencies.siteOrigin);
    } finally {
      cookieStore?.delete({
        name: SYSTEM_USER_COOKIE.name,
        path: SYSTEM_USER_COOKIE.options.path,
      });
    }
  };
}

export async function GET(request: Request) {
  const callbackHandler = createSystemUserCallbackHandler({
    siteOrigin: systemUserSiteOrigin(),
    async createSupabaseClient() {
      const { createSupabaseServerClient } = await import("../../../lib/supabase/server.ts");
      return createSupabaseServerClient();
    },
    async getCookieStore() {
      const { cookies } = await import("next/headers.js");
      return cookies();
    },
    reconcileRequest: defaultReconcileRequest,
  });
  return callbackHandler(request);
}
