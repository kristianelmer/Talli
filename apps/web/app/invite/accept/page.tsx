import Link from "next/link";
import { randomUUID } from "node:crypto";

import { acceptWorkspaceInvitation, recoverWorkspaceInvitationSideEffects } from "../../actions";
import { lookupCompanyInvitation } from "../../../features/company-access";
import { getCurrentSessionAccessToken } from "../../lib/supabase/auth-session";

type InvitationAcceptancePageProps = {
  searchParams?: Promise<{ token?: string; recovery?: string }>;
};

export default async function InvitationAcceptancePage({
  searchParams,
}: InvitationAcceptancePageProps) {
  const params = await searchParams;
  const token = params?.token ?? "";
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    return (
      <main className="legalShell">
        <h1>Logg inn for å se invitasjonen</h1>
        <p>Invitasjonen kan bare åpnes av mottakeren med samme e-postadresse.</p>
        <Link href={`/login?next=${encodeURIComponent(params?.recovery ? "/invite/accept?recovery=1" : `/invite/accept?token=${token}`)}`}>Logg inn</Link>
      </main>
    );
  }

  if (params?.recovery) {
    return (
      <main className="legalShell">
        <h1>Fullfør lagret invitasjonshandling</h1>
        <p>Handlingen er allerede lagret. Fullfør det manglende revisjonssporet eller varselet uten å bruke tokenet på nytt.</p>
        <form action={recoverWorkspaceInvitationSideEffects}>
          <button className="primaryButton" type="submit">Fullfør lagret handling</button>
        </form>
      </main>
    );
  }

  try {
    const invitation = await lookupCompanyInvitation(accessToken, token);
    return (
      <main className="legalShell">
        <h1>Invitasjon til {invitation.companyName}</h1>
        <p>Du er invitert som {invitation.role}.</p>
        <p>Invitasjonen utløper {new Date(invitation.expiresAt).toLocaleString("nb-NO")}.</p>
        <form action={acceptWorkspaceInvitation}>
          <input name="operationId" type="hidden" value={randomUUID()} />
          <input name="token" type="hidden" value={token} />
          <button className="primaryButton" type="submit">Godta tilgang</button>
        </form>
      </main>
    );
  } catch {
    return (
      <main className="legalShell">
        <h1>Invitasjonen er ikke tilgjengelig</h1>
        <p>Den kan være utløpt, tilbakekalt, allerede brukt eller sendt til en annen e-postadresse.</p>
        <form action={recoverWorkspaceInvitationSideEffects}>
          <button className="secondaryButton" type="submit">Fullfør en lagret handling</button>
        </form>
      </main>
    );
  }
}
