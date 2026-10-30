import { systemUserCallbackProof } from "../../../lib/authority-callback-transport.ts";
import { createSystemUserCallbackHandler, systemUserSiteOrigin } from "./handler.ts";

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
