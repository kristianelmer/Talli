import { createSupabaseServerClient, hasSupabaseEnv } from "./server";

export async function getCurrentSessionAccessToken() {
  if (!hasSupabaseEnv()) return null;
  const supabase = await createSupabaseServerClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}
