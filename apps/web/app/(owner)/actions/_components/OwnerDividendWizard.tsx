"use client";

import { useState } from "react";

import { createOwnerDividendDecisionDraft } from "../../../actions";
import { Banner, SubmitButton } from "../../../components/ui";
import type {
  CorporateAnnualBasisWire,
  CorporateReviewedFactsWire,
} from "../../../../features/corporate-governance";

export type DividendShareholder = {
  id: string;
  name: string;
  share_count: number;
};

export type OwnerDividendDraftIds = {
  decisionId: string;
  documentSetId: string;
  dividendBoardArtifactId: string;
  dividendBoardDocumentId: string;
  dividendGeneralMeetingArtifactId: string;
  dividendGeneralMeetingDocumentId: string;
};

type Props = {
  companyId: string;
  incomeYear: number;
  shareholders: DividendShareholder[];
  annualBasis: CorporateAnnualBasisWire | null;
  reviewedFacts: CorporateReviewedFactsWire | null;
  draftIds: OwnerDividendDraftIds;
  featureEnabled: boolean;
  basisBlocker?: string | null;
};

type BoardParticipantDraft = {
  key: string;
  participantId: string;
  name: string;
  role: "chair" | "member";
};

export function OwnerDividendWizard({
  companyId,
  incomeYear,
  shareholders,
  annualBasis,
  reviewedFacts,
  draftIds,
  featureEnabled,
  basisBlocker,
}: Props) {
  const [dividendAmountNok, setDividendAmountNok] = useState("");
  const [boardParticipants, setBoardParticipants] = useState<BoardParticipantDraft[]>([
    { key: "board-row-1", participantId: "board-1", name: "", role: "chair" },
  ]);
  const [shareholderVotes, setShareholderVotes] = useState<Record<string, "for" | "against" | "abstain">>(
    Object.fromEntries(shareholders.map((shareholder) => [shareholder.id, "for"])),
  );
  const [confirmations, setConfirmations] = useState<Record<string, boolean>>({});
  const dividendAmountOre = Number.isFinite(Number(dividendAmountNok))
    ? Math.round(Number(dividendAmountNok) * 100)
    : 0;
  const requiredConfirmationNames = [
    "oneShareClassConfirmed",
    "fullBoardParticipationConfirmed",
    "unanimousBoardConfirmed",
    "supportedDividendBasisConfirmed",
    "prudentEquityAndLiquidityConfirmed",
  ];
  const ready = featureEnabled
    && Boolean(annualBasis && reviewedFacts)
    && dividendAmountOre > 0
    && boardParticipants.length > 0
    && boardParticipants.every((participant) => participant.name.trim())
    && Object.values(shareholderVotes).every((vote) => vote === "for")
    && requiredConfirmationNames.every((name) => confirmations[name]);

  function updateParticipant(index: number, patch: Partial<BoardParticipantDraft>) {
    setBoardParticipants((current) => current.map((participant, row) =>
      row === index ? { ...participant, ...patch } : participant));
  }

  function addParticipant() {
    setBoardParticipants((current) => [
      ...current,
      {
        key: `board-row-${current.length + 1}`,
        participantId: `board-${current.length + 1}`,
        name: "",
        role: "member",
      },
    ]);
  }

  if (!featureEnabled) {
    return (
      <Banner variant="info">
        Beslutningsdokumenter er deaktivert til malene og bokføringspolicyen har navngitt juridisk og
        regnskapsfaglig godkjenning. Det gamle posteringsskjemaet er ikke tilgjengelig.
      </Banner>
    );
  }
  if (!annualBasis || !reviewedFacts || shareholders.length === 0) {
    return (
      <Banner variant="danger">
        {basisBlocker ?? "Godkjent årsregnskap og et komplett aksjonærgrunnlag må finnes før utkast kan opprettes."}
      </Banner>
    );
  }

  return (
    <form action={createOwnerDividendDecisionDraft} className="wizardForm">
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />
      {Object.entries(draftIds).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      <input type="hidden" name="dividendAmountOre" value={dividendAmountOre} />
      <input type="hidden" name="reviewedOrganizationNumber" value={reviewedFacts.organizationNumber} />
      <input type="hidden" name="reviewedLegalName" value={reviewedFacts.legalName} />
      <input type="hidden" name="reviewedTotalCompanyShares" value={reviewedFacts.totalCompanyShares} />
      <input type="hidden" name="reviewedAvailableDistributionOre" value={reviewedFacts.availableDistributionOre} />
      <input type="hidden" name="reviewedAnnualDataHash" value={reviewedFacts.annualDataSha256} />
      <input type="hidden" name="reviewedAnnualAccountsPayloadHash" value={reviewedFacts.annualAccountsPayloadSha256} />
      {reviewedFacts.shareholders.map((shareholder) => (
        <span key={`reviewed-${shareholder.shareholderId}`} hidden>
          <input type="hidden" name="reviewedShareholderId" value={shareholder.shareholderId} />
          <input type="hidden" name="reviewedShareholderName" value={shareholder.name} />
          <input type="hidden" name="reviewedShareholderShareCount" value={shareholder.shareCount} />
        </span>
      ))}

      <section className="dataPanel">
        <p className="eyebrow">Gjennomgått grunnlag</p>
        <h2>Utkast til eierutbytte</h2>
        <p>
          {reviewedFacts.legalName} · org.nr. {reviewedFacts.organizationNumber} · årsgrunnlag {annualBasis.incomeYear}
        </p>
        <p>
          Fri egenkapital: {(annualBasis.availableDistributionOre / 100).toLocaleString("nb-NO")} kr · bank:
          {" "}{(annualBasis.cashOre / 100).toLocaleString("nb-NO")} kr
        </p>
        <p>
          Utkastet er ikke signert eller bokført. Etter faktagjennomgang kan det bli godkjent for signering.
        </p>
      </section>

      <label>
        Totalutbytte i kroner
        <input
          name="dividendAmountNok"
          inputMode="decimal"
          value={dividendAmountNok}
          onChange={(event) => setDividendAmountNok(event.target.value)}
          required
        />
      </label>
      <label>
        Betalingsdato
        <input name="paymentDate" type="date" required />
      </label>

      <fieldset>
        <legend>Styremøte</legend>
        <div className="fieldRow">
          <label>
            Dato
            <input name="boardMeetingDate" type="date" required />
          </label>
          <label>
            Tid
            <input name="boardMeetingTime" type="time" step="1" required />
          </label>
        </div>
        <label>
          Sted
          <input name="boardMeetingPlace" required />
        </label>
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
                onChange={(event) => updateParticipant(index, { role: event.target.value as "chair" | "member" })}
              >
                <option value="chair">Styreleder</option>
                <option value="member">Styremedlem</option>
              </select>
            </label>
          </div>
        ))}
        <button className="secondaryButton" type="button" onClick={addParticipant}>
          Legg til styredeltaker
        </button>
      </fieldset>

      <fieldset>
        <legend>Generalforsamling</legend>
        <div className="fieldRow">
          <label>
            Dato
            <input name="generalMeetingDate" type="date" required />
          </label>
          <label>
            Tid
            <input name="generalMeetingTime" type="time" step="1" required />
          </label>
        </div>
        <label>
          Sted
          <input name="generalMeetingPlace" required />
        </label>
        <label>
          Møteform
          <select name="generalMeetingForm" defaultValue="physical" required>
            <option value="physical">Fysisk møte</option>
            <option value="video">Videomøte</option>
          </select>
        </label>
        <div className="fieldRow">
          <label>
            Møteleder
            <input name="generalMeetingChairName" required />
          </label>
          <label>
            Medundertegner
            <input name="generalMeetingCoSignerName" required />
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Alle aksjonærer og proporsjonal fordeling</legend>
        {shareholders.map((shareholder) => {
          return (
            <div className="readinessItem" key={shareholder.id}>
              <input type="hidden" name="shareholderVoteId" value={shareholder.id} />
              <input type="hidden" name="shareholderRepresentedShareCount" value={shareholder.share_count} />
              <strong>{shareholder.name}</strong>
              <p>
                {shareholder.share_count} aksjer · nøyaktig proporsjonal andel beregnes av utbyttetjenesten
              </p>
              <label>
                Stemme
                <select
                  name="shareholderVote"
                  value={shareholderVotes[shareholder.id]}
                  onChange={(event) => setShareholderVotes((current) => ({
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
          );
        })}
      </fieldset>

      <fieldset>
        <legend>Bekreft støttet beslutningsløype</legend>
        <label>
          <input
            name="oneShareClassConfirmed"
            type="checkbox"
            required
            onChange={(event) => setConfirmations((current) => ({
              ...current,
              oneShareClassConfirmed: event.target.checked,
            }))}
          />
          Selskapet har én aksjeklasse.
        </label>
        <label>
          <input
            name="fullBoardParticipationConfirmed"
            type="checkbox"
            required
            onChange={(event) => setConfirmations((current) => ({
              ...current,
              fullBoardParticipationConfirmed: event.target.checked,
            }))}
          />
          Alle styremedlemmer deltar.
        </label>
        <label>
          <input
            name="unanimousBoardConfirmed"
            type="checkbox"
            required
            onChange={(event) => setConfirmations((current) => ({
              ...current,
              unanimousBoardConfirmed: event.target.checked,
            }))}
          />
          Styret er enstemmig.
        </label>
        <label>
          <input
            name="supportedDividendBasisConfirmed"
            type="checkbox"
            required
            onChange={(event) => setConfirmations((current) => ({
              ...current,
              supportedDividendBasisConfirmed: event.target.checked,
            }))}
          />
          Utbyttet bygger på siste godkjente årsregnskap.
        </label>
        <label>
          <input
            name="prudentEquityAndLiquidityConfirmed"
            type="checkbox"
            required
            onChange={(event) => setConfirmations((current) => ({
              ...current,
              prudentEquityAndLiquidityConfirmed: event.target.checked,
            }))}
          />
          Egenkapital og likviditet er forsvarlige etter utdelingen.
        </label>
      </fieldset>

      <SubmitButton disabled={!ready} pendingLabel="Lager PDF-utkast …">
        Opprett dokumentutkast
      </SubmitButton>
    </form>
  );
}
