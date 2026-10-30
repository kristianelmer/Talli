import Link from "next/link";

import { Banner, SubmitButton } from "../../components/ui";
import { passwordRecoveryContext } from "../../lib/auth-recovery-context";
import { authRecoveryMessage, recoveryReturn } from "../../lib/auth-recovery-presentation";
import { leaveAccountForRecovery } from "../recovery-actions";
import { ResetPasswordForm } from "./ResetPasswordForm";

export const dynamic = "force-dynamic";

export default async function ResetPasswordPage({ searchParams }: {
  searchParams?: Promise<{ next?: string; error?: string }>;
}) {
  const params = await searchParams;
  // Cookie deletion rerenders this page; retain the uncertain-write outcome
  // without restoring a grant or offering another password submission.
  const context = params?.error === "password-unknown"
    ? { kind: "password-unknown" as const, next: recoveryReturn(params.next) }
    : await passwordRecoveryContext();
  const next = ("next" in context && typeof context.next === "string") ? context.next : recoveryReturn(params?.next);
  return (
    <div className="authCard">
      <div className="appBrand"><span className="appBrandMark" aria-hidden="true" /><span>Talli</span></div>
      <h1 className="authTitle">{context.kind === "ready" ? "Velg nytt passord" : "Tilbakestill passord"}</h1>
      {context.kind === "ready" ? (
        <>
          <p className="authEmail">Konto: {context.user.email}</p>
          <ResetPasswordForm userId={context.user.id} next={next} />
        </>
      ) : (
        <>
          <Banner variant={context.kind === "mfa" ? "info" : "danger"}>{authRecoveryMessage[context.kind]}</Banner>
          {context.kind === "password-unknown" ? (
            <>
              <Link className="btn btn--primary" href={`/login?${new URLSearchParams({ reauth: "1", next })}`}>Prøv å logge inn</Link>
              <Link href={`/forgot-password?${new URLSearchParams({ next })}`}>Be om en ny lenke</Link>
            </>
          ) : context.kind === "mfa" ? (
            <Link className="btn btn--primary" href={`/mfa?${new URLSearchParams({ fresh: "1", next: `/reset-password?${new URLSearchParams({ next })}` })}`}>Bekreft med autentiseringsappen</Link>
          ) : context.kind === "wrong-account" ? (
            <form action={leaveAccountForRecovery}>
              <input name="next" type="hidden" value={next} />
              <SubmitButton block pendingLabel="Logger ut …">Logg ut og be om en ny lenke</SubmitButton>
            </form>
          ) : <Link className="btn btn--primary" href={`/forgot-password?${new URLSearchParams({ next })}`}>Be om en ny lenke</Link>}
        </>
      )}
      {context.kind !== "password-unknown" ? <p className="authAlt"><Link href={`/login?${new URLSearchParams({ reauth: "1", next })}`}>Tilbake til innlogging</Link></p> : null}
    </div>
  );
}
