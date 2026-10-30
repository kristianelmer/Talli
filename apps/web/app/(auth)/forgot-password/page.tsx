import Link from "next/link";

import { Banner, SubmitButton } from "../../components/ui";
import { hasAuthRecoveryEnv } from "../../lib/auth-recovery-context";
import { authRecoveryMessage, recoveryError, recoveryReturn } from "../../lib/auth-recovery-presentation";
import { getCurrentUser } from "../../lib/supabase/server";
import { leaveAccountForRecovery } from "../recovery-actions";
import { RequestRecoveryForm } from "./RequestRecoveryForm";

export const dynamic = "force-dynamic";

export default async function ForgotPasswordPage({ searchParams }: {
  searchParams?: Promise<{ next?: string; error?: string }>;
}) {
  const params = await searchParams;
  const next = recoveryReturn(params?.next);
  const error = recoveryError(params?.error);
  const enabled = hasAuthRecoveryEnv();
  let user = null;
  try { user = await getCurrentUser(); } catch { /* Show an unavailable request, not account details. */ }
  return (
    <div className="authCard">
      <div className="appBrand"><span className="appBrandMark" aria-hidden="true" /><span>Talli</span></div>
      <h1 className="authTitle">Tilbakestill passord</h1>
      {error ? <Banner variant="danger">{authRecoveryMessage[error]}</Banner> : null}
      {!enabled ? <Banner variant="danger">{authRecoveryMessage.unavailable}</Banner> : null}
      {user ? (
        <>
          <p className="authEmail">Du er innlogget som <strong>{user.email}</strong>.</p>
          <form action={leaveAccountForRecovery} className="authForm">
            <input name="next" type="hidden" value={next} />
            <SubmitButton block pendingLabel="Logger ut …">Logg ut og tilbakestill passord</SubmitButton>
          </form>
        </>
      ) : <RequestRecoveryForm next={next} enabled={enabled} />}
      <p className="authAlt"><Link href={`/login?${new URLSearchParams({ reauth: "1", next })}`}>Tilbake til innlogging</Link></p>
    </div>
  );
}
