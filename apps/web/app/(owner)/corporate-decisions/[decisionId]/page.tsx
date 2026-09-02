import { randomUUID } from "node:crypto";
import { notFound, redirect } from "next/navigation";

import {
  approveCorporateDecisionFacts,
  finalizeCorporateDecision,
  recordCorporateSigningRequested,
  rejectCorporateDecision,
} from "../../../actions";
import { Banner, StatusBadge, SubmitButton } from "../../../components/ui";
import type { CorporateArtifactKind } from "../../../../features/corporate-governance";
import { loadAcceptedMembershipCompany } from "../../../lib/company-access-context";
import { createSupabaseServerClient } from "../../../lib/supabase/server";
import { SignedArtifactUpload } from "./SignedArtifactUpload";
import {
  readCorporateDecisionLifecycle,
  readCorporateDecisionReadiness,
} from "../../../../features/corporate-governance";
import { getCurrentSessionAccessToken } from "../../../lib/supabase/auth-session";

export const dynamic = "force-dynamic";

type Props = {
  params: Promise<{ decisionId: string }>;
  searchParams?: Promise<{ error?: string; finalizeDecisionOperationId?: string }>;
};

const KIND_LABELS: Record<CorporateArtifactKind, string> = {
  dividend_board_proposal: "Styrets utbytteforslag",
  dividend_general_meeting_minutes: "Generalforsamlingsprotokoll for utbytte",
  annual_board_minutes: "Styrets årsprotokoll",
  annual_general_meeting_minutes: "Generalforsamlingsprotokoll for årsoppgjør",
};

function LifecycleFields({ decisionId, setId, decisionHash }: {
  decisionId: string;
  setId: string;
  decisionHash: string;
}) {
  return (
    <>
      <input type="hidden" name="decisionId" value={decisionId} />
      <input type="hidden" name="documentSetId" value={setId} />
      <input type="hidden" name="decisionHash" value={decisionHash} />
    </>
  );
}

export default async function CorporateDecisionPage({ params, searchParams }: Props) {
  const [{ decisionId }, query] = await Promise.all([params, searchParams]);
  if (!/^[0-9a-f-]{36}$/i.test(decisionId)) notFound();
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/login");
  let lifecycle;
  try {
    lifecycle = await readCorporateDecisionLifecycle(accessToken, decisionId);
  } catch {
    notFound();
  }
  const decision = lifecycle.corporateDecisions[0];
  const documentSet = lifecycle.corporateDocumentSets[0];
  if (!decision || !documentSet || documentSet.decision_id !== decision.id) notFound();
  const company = await loadAcceptedMembershipCompany(decision.company_id);
  if (!company || company.role !== "owner") notFound();
  const readiness = await readCorporateDecisionReadiness(accessToken, {
    companyId: decision.company_id,
    incomeYear: decision.income_year,
    decisionKind: decision.decision_kind,
  });

  const events = lifecycle.corporateDocumentEvents;
  const artifacts = lifecycle.corporateDocumentArtifacts;
  const canonicalInput = decision.canonical_input;
  const unsignedArtifacts = artifacts.filter((artifact) => artifact.variant === "unsigned");
  const signedArtifacts = artifacts.filter((artifact) => artifact.variant === "signed_owner_attested");
  const finalized = readiness.finalized;
  const rejected = readiness.state === "rejected";
  const factsApproved = [
    "facts_approved",
    "signing_requested",
    "signed_owner_attested",
    "finalized",
    "partially_paid",
    "paid",
  ].includes(readiness.state ?? "");
  const signingRequested = [
    "signing_requested",
    "signed_owner_attested",
    "finalized",
    "partially_paid",
    "paid",
  ].includes(readiness.state ?? "");
  const allSigned = Object.keys(readiness.signedArtifactHashes).length === 2;
  const lifecycleState = {
    proposed: "Utkast",
    documents_registered: "Utkast",
    facts_approved: "Fakta godkjent",
    signing_requested: "Venter på signerte kopier",
    signed_owner_attested: "Signerte kopier bekreftet",
    finalized: "Sluttført",
    partially_paid: "Delvis utbetalt",
    paid: "Utbetalt",
    rejected: "Avvist",
  }[readiness.state ?? "proposed"];
  const mutationsEnabled = process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED === "true" && !finalized && !rejected;

  return (
    <div>
      <div className="pageHead">
        <p className="eyebrow">Selskapsbeslutning · {decision.income_year}</p>
        <h1 className="pageTitle">
          {decision.decision_kind === "owner_dividend" ? "Utbyttebeslutning" : "Årsbeslutning"}
        </h1>
        <p className="pageLede">
          Gjennomgå lagrede fakta, behold originalutkastene og bekreft separat signerte kopier før sluttføring.
        </p>
      </div>
      {query?.error ? <Banner variant="danger">{query.error}</Banner> : null}
      {process.env.TALLI_CORPORATE_DOCUMENTS_ENABLED !== "true" ? (
        <Banner variant="warning">Arbeidsflyten er deaktivert til navngitte faglige godkjenninger foreligger.</Banner>
      ) : null}

      <section className="docSection">
        <div className="dataPanel">
          <StatusBadge variant={finalized ? "success" : rejected ? "warning" : "info"} label={lifecycleState} />
          <p><strong>Beslutningshash (decisionHash)</strong><code>{decision.decision_hash}</code></p>
          <p><strong>Kildehash</strong><code>{decision.source_hash}</code></p>
          <p><strong>Malversjon</strong><code>{documentSet.template_version}</code></p>
        </div>
      </section>

      <section className="docSection">
        <h2 className="sectionTitle">Lagrede fakta</h2>
        <p className="cardNote">Dette er det uforanderlige grunnlaget PDF-ene og beslutningshashen er laget fra.</p>
        <div className="dataPanel">
          <pre>{JSON.stringify(canonicalInput, null, 2)}</pre>
        </div>
      </section>

      <section className="docSection">
        <h2 className="sectionTitle">Dokumenter og signatarer</h2>
        <p className="cardNote">
          Talli kontrollerer filtype, innholdshash og eierens attestasjon. Talli utfører ikke kryptografisk
          signaturkontroll.
        </p>
        <div className="docList">
          {unsignedArtifacts.map((unsigned) => {
            const artifactKind = unsigned.artifact_kind as CorporateArtifactKind;
            const signers = readiness.requiredSigners[artifactKind] ?? [];
            const signed = signedArtifacts.find((candidate) => candidate.supersedes_artifact_id === unsigned.id);
            return (
              <article className="docRow" key={unsigned.id}>
                <div className="docRowMain">
                  <h3 className="docRowName">{KIND_LABELS[artifactKind]}</h3>
                  <span className="docRowType">Påkrevde signatarer: {signers.join(", ")}</span>
                  <span className="docRowType">Innholdshash: <code>{unsigned.content_sha256}</code></span>
                  <a className="docDownload" href={`/documents/${unsigned.document_id}/preview`} target="_blank">
                    Forhåndsvis original PDF
                  </a>
                  {signed ? (
                    <>
                      <StatusBadge variant="success" label="Signert kopi bekreftet av eier" icon="check" />
                      <span className="docRowType">Signert innholdshash: <code>{signed.content_sha256}</code></span>
                      <a className="docDownload" href={`/documents/${signed.document_id}/preview`} target="_blank">
                        Forhåndsvis bekreftet kopi
                      </a>
                    </>
                  ) : factsApproved && mutationsEnabled ? (
                    <SignedArtifactUpload
                      decisionId={decision.id}
                      documentSetId={documentSet.id}
                      decisionHash={decision.decision_hash}
                      unsignedArtifactId={unsigned.id}
                      signedArtifactId={randomUUID()}
                      signedDocumentId={randomUUID()}
                      signers={signers}
                    />
                  ) : (
                    <StatusBadge variant="warning" label="Signert kopi mangler" />
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      {mutationsEnabled ? (
        <section className="docSection">
          <h2 className="sectionTitle">Neste steg</h2>
          {!factsApproved ? (
            <form action={approveCorporateDecisionFacts} className="wizardForm">
              <LifecycleFields decisionId={decision.id} setId={documentSet.id} decisionHash={decision.decision_hash} />
              <p>Jeg har gjennomgått de lagrede faktaene og begge originalutkastene.</p>
              <SubmitButton>Godkjenn fakta</SubmitButton>
            </form>
          ) : !signingRequested ? (
            <form action={recordCorporateSigningRequested} className="wizardForm">
              <LifecycleFields decisionId={decision.id} setId={documentSet.id} decisionHash={decision.decision_hash} />
              <SubmitButton>Registrer sendt til ekstern signering</SubmitButton>
            </form>
          ) : null}
          {factsApproved && allSigned ? (
            <form action={finalizeCorporateDecision} className="wizardForm">
              <LifecycleFields decisionId={decision.id} setId={documentSet.id} decisionHash={decision.decision_hash} />
              <input type="hidden" name="operationId" value={query?.finalizeDecisionOperationId ?? randomUUID()} />
              <input type="hidden" name="finalizationId" value={randomUUID()} />
              {decision.decision_kind === "owner_dividend" ? (
                <>
                  <input type="hidden" name="holdingActionId" value={randomUUID()} />
                  <input type="hidden" name="ledgerEntryId" value={randomUUID()} />
                </>
              ) : null}
              <Banner variant="warning">
                Sluttføring er uforanderlig. For utbytte opprettes også deklarasjon og regnskapspost atomisk.
              </Banner>
              <SubmitButton>Sluttfør beslutningen</SubmitButton>
            </form>
          ) : null}
          <form action={rejectCorporateDecision} className="wizardForm">
            <LifecycleFields decisionId={decision.id} setId={documentSet.id} decisionHash={decision.decision_hash} />
            <label>Årsak til avvisning<input name="reason" maxLength={1000} required /></label>
            <SubmitButton variant="destructive">Avvis utkastet</SubmitButton>
          </form>
        </section>
      ) : null}

      <section className="docSection">
        <h2 className="sectionTitle">Hendelseslogg</h2>
        <div className="docList">
          {events.map((event) => (
            <div className="docRow" key={event.id}>
              <span className="docRowName">{event.event_kind}</span>
              <span className="docRowType">{new Date(event.occurred_at).toLocaleString("nb-NO")}</span>
              <code>{event.content_sha256 ?? event.decision_hash}</code>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
