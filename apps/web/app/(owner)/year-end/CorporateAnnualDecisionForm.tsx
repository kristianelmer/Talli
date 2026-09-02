"use client";

import { useState } from "react";

import { createAnnualCorporateDecisionDraft } from "../../actions";
import { Banner, SubmitButton } from "../../components/ui";
import type {
  CorporateAnnualBasisWire,
  CorporateReviewedFactsWire,
} from "../../../features/corporate-governance";

type AnnualDecisionShareholder = {
  id: string;
  name: string;
  shareCount: number;
};

export type AnnualDecisionDraftIds = {
  decisionId: string;
  documentSetId: string;
  annualBoardArtifactId: string;
  annualBoardDocumentId: string;
  annualGeneralMeetingArtifactId: string;
  annualGeneralMeetingDocumentId: string;
};

export type AnnualDecisionLifecycleSummary = {
  decisionId: string;
  state: string;
  decisionHash: string;
  sourceHash: string;
  templateVersion: string;
  stale: boolean;
} | null;

type Props = {
  companyId: string;
  incomeYear: number;
  shareholders: AnnualDecisionShareholder[];
  annualBasis: CorporateAnnualBasisWire | null;
  reviewedFacts: CorporateReviewedFactsWire | null;
  sourceHash: string | null;
  draftIds: AnnualDecisionDraftIds;
  lifecycle: AnnualDecisionLifecycleSummary;
  featureEnabled: boolean;
  blocker?: string | null;
};

type BoardParticipantDraft = {
  key: string;
  participantId: string;
  name: string;
  role: "chair" | "member";
};

const TEMPLATE_VERSION = "corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1";

export function CorporateAnnualDecisionForm({
  companyId,
  incomeYear,
  shareholders,
  annualBasis,
  reviewedFacts,
  sourceHash,
  draftIds,
  lifecycle,
  featureEnabled,
  blocker,
}: Props) {
  const [boardParticipants, setBoardParticipants] = useState<BoardParticipantDraft[]>([
    { key: "annual-board-row-1", participantId: "annual-board-1", name: "", role: "chair" },
  ]);
  const [votes, setVotes] = useState<Record<string, "for" | "against" | "abstain">>(
    Object.fromEntries(shareholders.map((shareholder) => [shareholder.id, "for"])),
  );
  const [confirmations, setConfirmations] = useState<Record<string, boolean>>({});
  const requiredConfirmations = [
    "oneShareClassConfirmed",
    "fullBoardParticipationConfirmed",
    "unanimousBoardConfirmed",
    "supportedDividendBasisConfirmed",
    "prudentEquityAndLiquidityConfirmed",
  ];
  const ready = featureEnabled
    && Boolean(annualBasis && reviewedFacts && sourceHash)
    && shareholders.length > 0
    && boardParticipants.every(({ name }) => name.trim())
    && Object.values(votes).every((vote) => vote === "for")
    && requiredConfirmations.every((name) => confirmations[name]);

  function updateParticipant(index: number, patch: Partial<BoardParticipantDraft>) {
    setBoardParticipants((current) => current.map((participant, row) =>
      row === index ? { ...participant, ...patch } : participant));
  }

  function addParticipant() {
    setBoardParticipants((current) => [
      ...current,
      {
        key: `annual-board-row-${current.length + 1}`,
        participantId: `annual-board-${current.length + 1}`,
        name: "",
        role: "member",
      },
    ]);
  }

  if (!featureEnabled) {
    return (
      <Banner variant="info">
        Årsbeslutningsdokumenter er deaktivert til malene har navngitt juridisk godkjenning.
      </Banner>
    );
  }
  if (!annualBasis || !reviewedFacts || !sourceHash || shareholders.length === 0) {
    return (
      <Banner variant="danger">
        {blocker ?? "Fullført årsgrunnlag, årsregnskapspayload og aksjonærgrunnlag må være klare."}
      </Banner>
    );
  }

  return (
    <form action={createAnnualCorporateDecisionDraft} className="wizardForm">
      <input type="hidden" name="returnTo" value="/year-end" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />
      <input type="hidden" name="annualResultAllocationOre" value={annualBasis.resultAfterTaxOre} />
      {Object.entries(draftIds).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      <input type="hidden" name="reviewedOrganizationNumber" value={reviewedFacts.organizationNumber} />
      <input type="hidden" name="reviewedLegalName" value={reviewedFacts.legalName} />
      <input type="hidden" name="reviewedTotalCompanyShares" value={reviewedFacts.totalCompanyShares} />
      <input type="hidden" name="reviewedAvailableDistributionOre" value={reviewedFacts.availableDistributionOre} />
      <input type="hidden" name="reviewedAnnualDataHash" value={reviewedFacts.annualDataSha256} />
      <input type="hidden" name="reviewedAnnualAccountsPayloadHash" value={reviewedFacts.annualAccountsPayloadSha256} />
      {reviewedFacts.shareholders.map((shareholder) => (
        <span key={shareholder.shareholderId} hidden>
          <input type="hidden" name="reviewedShareholderId" value={shareholder.shareholderId} />
          <input type="hidden" name="reviewedShareholderName" value={shareholder.name} />
          <input type="hidden" name="reviewedShareholderShareCount" value={shareholder.shareCount} />
        </span>
      ))}

      <section className="dataPanel">
        <p className="eyebrow">Selskapsbeslutning for {incomeYear}</p>
        <h2>Styre- og generalforsamlingsprotokoller</h2>
        <p>
          Årsresultat: {(annualBasis.resultAfterTaxOre / 100).toLocaleString("nb-NO")} kr · egenkapital:
          {" "}{(annualBasis.equityOre / 100).toLocaleString("nb-NO")} kr
        </p>
        <p><strong>Kildehash:</strong> <code>{sourceHash}</code></p>
        <p><strong>Malversjon:</strong> <code>{TEMPLATE_VERSION}</code></p>
        <p>
          Årsregnskapet krever separat lovpålagt signatur. Disse PDF-ene dokumenterer styrets behandling og
          generalforsamlingens vedtak, og utkastet er verken signert eller sluttført.
        </p>
        {lifecycle ? (
          <p>
            Eksisterende beslutning: {lifecycle.state}. {lifecycle.stale
              ? "Grunnlaget er endret; beslutningen må erstattes (superseded)."
              : "Kildehashen er fortsatt gjeldende."}
          </p>
        ) : null}
      </section>

      <fieldset>
        <legend>Styrets behandling</legend>
        <div className="fieldRow">
          <label>Dato<input name="boardMeetingDate" type="date" required /></label>
          <label>Tid<input name="boardMeetingTime" type="time" step="1" required /></label>
        </div>
        <label>Sted<input name="boardMeetingPlace" required /></label>
        <label>
          Behandlingsmåte
          <select name="boardTreatmentMethod" defaultValue="physical" required>
            <option value="physical">Fysisk møte</option>
            <option value="video">Videomøte</option>
            <option value="written">Skriftlig behandling</option>
          </select>
        </label>
        {boardParticipants.map((participant, index) => (
          <div className="fieldRow" key={participant.key}>
            <input type="hidden" name="boardParticipantId" value={participant.participantId} />
            <input type="hidden" name="boardParticipantOrder" value={index} />
            <label>
              Styredeltaker {index + 1}
              <input
                name="boardParticipantName"
                value={participant.name}
                onChange={(event) => updateParticipant(index, { name: event.target.value })}
                required
              />
            </label>
            <label>
              Rolle
              <select
                name="boardParticipantRole"
                value={participant.role}
                onChange={(event) => updateParticipant(index, {
                  role: event.target.value as "chair" | "member",
                })}
              >
                <option value="chair">Styreleder</option>
                <option value="member">Styremedlem</option>
              </select>
            </label>
          </div>
        ))}
        <button type="button" className="secondaryButton" onClick={addParticipant}>Legg til styredeltaker</button>
      </fieldset>

      <fieldset>
        <legend>Generalforsamling</legend>
        <div className="fieldRow">
          <label>Dato<input name="generalMeetingDate" type="date" required /></label>
          <label>Tid<input name="generalMeetingTime" type="time" step="1" required /></label>
        </div>
        <label>Sted<input name="generalMeetingPlace" required /></label>
        <label>
          Møteform
          <select name="generalMeetingForm" defaultValue="physical" required>
            <option value="physical">Fysisk møte</option>
            <option value="video">Videomøte</option>
          </select>
        </label>
        <div className="fieldRow">
          <label>Møteleder<input name="generalMeetingChairName" required /></label>
          <label>Medundertegner<input name="generalMeetingCoSignerName" required /></label>
        </div>
        {shareholders.map((shareholder) => (
          <div className="readinessItem" key={shareholder.id}>
            <input type="hidden" name="shareholderVoteId" value={shareholder.id} />
            <input type="hidden" name="shareholderRepresentedShareCount" value={shareholder.shareCount} />
            <strong>{shareholder.name}</strong>
            <p>{shareholder.shareCount} aksjer representert</p>
            <label>
              Stemme
              <select
                name="shareholderVote"
                value={votes[shareholder.id]}
                onChange={(event) => setVotes((current) => ({
                  ...current,
                  [shareholder.id]: event.target.value as "for" | "against" | "abstain",
                }))}
              >
                <option value="for">For</option>
                <option value="against">Mot</option>
                <option value="abstain">Avstår</option>
              </select>
            </label>
          </div>
        ))}
      </fieldset>

      <fieldset>
        <legend>Bekreft støttet årsbeslutning</legend>
        <label>
          <input name="oneShareClassConfirmed" type="checkbox" required onChange={(event) =>
            setConfirmations((current) => ({ ...current, oneShareClassConfirmed: event.target.checked }))} />
          Selskapet har én aksjeklasse.
        </label>
        <label>
          <input name="fullBoardParticipationConfirmed" type="checkbox" required onChange={(event) =>
            setConfirmations((current) => ({ ...current, fullBoardParticipationConfirmed: event.target.checked }))} />
          Alle styremedlemmer deltar.
        </label>
        <label>
          <input name="unanimousBoardConfirmed" type="checkbox" required onChange={(event) =>
            setConfirmations((current) => ({ ...current, unanimousBoardConfirmed: event.target.checked }))} />
          Styret og aksjonærene er enstemmige.
        </label>
        <label>
          <input name="supportedDividendBasisConfirmed" type="checkbox" required onChange={(event) =>
            setConfirmations((current) => ({ ...current, supportedDividendBasisConfirmed: event.target.checked }))} />
          Årsgrunnlaget og resultatdisponeringen er gjennomgått.
        </label>
        <label>
          <input name="prudentEquityAndLiquidityConfirmed" type="checkbox" required onChange={(event) =>
            setConfirmations((current) => ({ ...current, prudentEquityAndLiquidityConfirmed: event.target.checked }))} />
          Egenkapital- og likviditetstallene i grunnlaget er gjennomgått.
        </label>
      </fieldset>

      <SubmitButton disabled={!ready} pendingLabel="Lager årsprotokoller …">
        Opprett dokumentutkast
      </SubmitButton>
    </form>
  );
}
