import Link from "next/link";
import { randomUUID } from "node:crypto";

import { acceptWorkspaceInvitation } from "../../actions";
import { lookupCompanyInvitation } from "../../../features/company-access";
import { getCurrentSessionAccessToken } from "../../lib/supabase/auth-session";

type InvitationAcceptancePageProps = {
  searchParams?: Promise<{ token?: string }>;
};

export default async function InvitationAcceptancePage({
  searchParams,
}: InvitationAcceptancePageProps) {
  const token = (await searchParams)?.token ?? "";
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    return (
      <main className="legalShell">
        <h1>Logg inn for å se invitasjonen</h1>
        <p>Invitasjonen kan bare åpnes av mottakeren med samme e-postadresse.</p>
        <Link href={`/login?next=${encodeURIComponent(`/invite/accept?token=${token}`)}`}>Logg inn</Link>
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
      </main>
    );
  }
}
