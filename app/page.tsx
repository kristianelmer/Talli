import { redirect } from "next/navigation";

import { getCurrentUser } from "./lib/supabase/server";

type HomeProps = {
  searchParams?: Promise<{ error?: string }>;
};

export default async function Home({ searchParams }: HomeProps) {
  const params = await searchParams;
  const user = await getCurrentUser();
  const errorQs = params?.error
    ? `?error=${encodeURIComponent(params.error)}`
    : "";
  if (!user) {
    redirect(`/login${errorQs}`);
  }
  redirect(`/dashboard${errorQs}`);
}
