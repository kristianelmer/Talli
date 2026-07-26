import { randomUUID } from "node:crypto";
import { notFound, redirect } from "next/navigation";

import {
  approveCorporateDecisionFacts,
  finalizeCorporateDecision,
  recordCorporateSigningRequested,
  rejectCorporateDecision,
} from "../../../actions";
import { Banner, StatusBadge, SubmitButton } from "../../../components/ui";
import type { CorporateArtifactKind, CorporateDecisionInput } from "../../../lib/corporate-documents";
import { requiredCorporateArtifactSigners } from "../../../lib/corporate-signed-artifacts";
import { createSupabaseServerClient } from "../../../lib/supabase/server";
import { SignedArtifactUpload } from "./SignedArtifactUpload";

export const dynamic = "force-dynamic";

type Props = {
  params: Promise<{ decisionId: string }>;
  searchParams?: Promise<{ error?: string }>;
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

  const decisionResult = await supabase
    .from("corporate_decisions")
    .select("id, company_id, income_year, decision_kind, annual_close_source_id, source_hash, canonical_input, decision_hash, created_at")
    .eq("id", decisionId)
    .maybeSingle();
  if (decisionResult.error || !decisionResult.data) notFound();
  const decision = decisionResult.data;
  const membershipResult = await supabase
    .from("company_memberships")
    .select("company_id")
    .eq("company_id", decision.company_id)
    .eq("user_id", user.id)
    .eq("role", "owner")
    .not("accepted_at", "is", null)
    .maybeSingle();
  if (membershipResult.error || !membershipResult.data) notFound();

  const [setResult, eventsResult, finalizationResult] = await Promise.all([
    supabase
      .from("corporate_document_sets")
      .select("id, decision_id, template_family, template_version, decision_hash, created_at")
      .eq("decision_id", decision.id)
      .maybeSingle(),
    supabase
      .from("corporate_document_events")
      .select("id, event_kind, occurred_at, decision_hash, content_sha256, metadata, artifact_id")
      .eq("decision_id", decision.id)
      .order("occurred_at", { ascending: true }),
    supabase
      .from("corporate_decision_finalizations")
      .select("id, finalization_kind, decision_hash, signed_artifact_hashes, accounting_policy_version, created_at")
      .eq("decision_id", decision.id)
      .maybeSingle(),
  ]);
  if (setResult.error || !setResult.data || eventsResult.error || finalizationResult.error) notFound();
  const documentSet = setResult.data;
  const artifactsResult = await supabase
    .from("corporate_document_artifacts")
    .select("id, artifact_kind, variant, document_id, content_sha256, byte_length, supersedes_artifact_id, created_at")
    .eq("set_id", documentSet.id)
    .order("created_at", { ascending: true });
  if (artifactsResult.error) notFound();

  const events = eventsResult.data ?? [];
  const artifacts = artifactsResult.data ?? [];
  const canonicalInput = decision.canonical_input as unknown as CorporateDecisionInput;
  const unsignedArtifacts = artifacts.filter((artifact) => artifact.variant === "unsigned");
  const signedArtifacts = artifacts.filter((artifact) => artifact.variant === "signed_owner_attested");
  const finalized = Boolean(finalizationResult.data);
  const rejected = events.some((event) => event.event_kind === "rejected");
  const factsApproved = events.some((event) => event.event_kind === "facts_approved");
  const signingRequested = events.some((event) => event.event_kind === "signing_requested");
  const allSigned = unsignedArtifacts.length === 2 && unsignedArtifacts.every((unsigned) =>
    signedArtifacts.some((signed) => signed.supersedes_artifact_id === unsigned.id));
  const lifecycleState = finalized
    ? "Sluttført"
    : rejected
      ? "Avvist"
      : allSigned
        ? "Signerte kopier bekreftet"
        : signingRequested
          ? "Venter på signerte kopier"
          : factsApproved
            ? "Fakta godkjent"
            : "Utkast";
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
            const signers = requiredCorporateArtifactSigners(artifactKind, canonicalInput);
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
