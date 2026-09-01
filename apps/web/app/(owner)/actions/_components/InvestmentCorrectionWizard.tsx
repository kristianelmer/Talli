"use client";

import { useState } from "react";

import { correctInvestmentAction } from "../../../actions";
import { Banner, SubmitButton } from "../../../components/ui";
import {
  InvestmentEvidenceFields,
  investmentEvidenceComplete,
  type InvestmentEvidenceOption,
  type InvestmentEvidenceState,
} from "./InvestmentEvidenceFields";
import { CheckboxField, SelectField, TextField } from "./fields";

type ActivityKind =
  | "share_purchase"
  | "share_sale"
  | "dividend_received"
  | "fund_distribution_received";

export type CorrectableInvestmentActivity = {
  id: string;
  kind: ActivityKind;
  label: string;
  actionDate: string;
  positionId: string;
  investmentName: string;
  investmentKey: string;
  investmentKind: "norwegian_private_company" | "norwegian_listed_share" | "norwegian_equity_fund";
  accountingClassification: "subsidiary" | "associate" | "other_long_term" | "current_listed_share" | "current_fund";
  orgNumber: string | null;
  shareCount: string | null;
  grossAmount: number;
  transactionCosts: number;
  declaredDate: string | null;
  fundEquityRatioBasisPoints: number | null;
  fundTaxStatementReference: string | null;
  groupExceptionClaimed: boolean;
  yearEndOwnershipBasisPoints: number | null;
  yearEndVotingBasisPoints: number | null;
  groupEvidenceReference: string | null;
};

function CorrectionFields({ activity }: { activity: CorrectableInvestmentActivity }) {
  const [actionDate, setActionDate] = useState(activity.actionDate);
  const [investmentName, setInvestmentName] = useState(activity.investmentName);
  const [shareCount, setShareCount] = useState(activity.shareCount ?? "");
  const [grossAmount, setGrossAmount] = useState(String(activity.grossAmount));
  const [transactionCosts, setTransactionCosts] = useState(
    String(activity.transactionCosts),
  );
  const [declaredDate, setDeclaredDate] = useState(activity.declaredDate ?? "");
  const [fundRatio, setFundRatio] = useState(
    String(activity.fundEquityRatioBasisPoints ?? ""),
  );
  const [fundStatement, setFundStatement] = useState(
    activity.fundTaxStatementReference ?? "",
  );
  const [groupException, setGroupException] = useState(
    activity.groupExceptionClaimed,
  );
  const [ownership, setOwnership] = useState(
    String(activity.yearEndOwnershipBasisPoints ?? ""),
  );
  const [voting, setVoting] = useState(
    String(activity.yearEndVotingBasisPoints ?? ""),
  );
  const [groupEvidence, setGroupEvidence] = useState(
    activity.groupEvidenceReference ?? "",
  );
  const [lawfulDividendConfirmed, setLawfulDividendConfirmed] = useState(false);

  return (
    <>
      <input type="hidden" name="positionId" value={activity.positionId} />
      <input type="hidden" name="investmentKey" value={activity.investmentKey} />
      <input type="hidden" name="investmentKind" value={activity.investmentKind} />
      <input
        type="hidden"
        name="accountingClassification"
        value={activity.accountingClassification}
      />
      <input type="hidden" name="orgNumber" value={activity.orgNumber ?? ""} />
      {activity.kind === "share_purchase"
        || activity.kind === "share_sale" ? (
        <TextField
          label={activity.kind === "share_purchase" ? "Hendelsesdato" : "Salgsdato"}
          name="actionDate"
          value={actionDate}
          onChange={setActionDate}
          required
        />
      ) : (
        <TextField
          label={activity.kind === "dividend_received" ? "Vedtaksdato" : "Rettighetsdato"}
          name="declaredDate"
          value={declaredDate}
          onChange={setDeclaredDate}
          helper="Kontantoppgjørsdato korrigeres separat nedenfor."
          required
        />
      )}
      {(activity.kind === "share_purchase"
        || activity.kind === "dividend_received"
        || activity.kind === "fund_distribution_received") ? (
        <TextField
          label={activity.kind === "share_purchase" ? "Investeringsnavn" : "Utbetaler/fond"}
          name="investmentName"
          value={investmentName}
          onChange={setInvestmentName}
          required
          readOnly={activity.kind === "share_purchase"}
          helper={activity.kind === "share_purchase"
            ? "Identiteten beholdes. Opprett en ny investering hvis instrumentet var feil."
            : undefined}
        />
      ) : (
        <input type="hidden" name="investmentName" value={investmentName} />
      )}
      {activity.kind === "share_purchase" || activity.kind === "share_sale" ? (
        <TextField
          label={activity.kind === "share_purchase" ? "Antall" : "Antall solgt"}
          name="shareCount"
          value={shareCount}
          onChange={setShareCount}
          inputMode="decimal"
          required
        />
      ) : null}
      <div className="fieldRow">
        <TextField
          label={activity.kind === "share_purchase" ? "Kjøpsbeløp (kr)" : "Bruttobeløp (kr)"}
          name="grossAmount"
          value={grossAmount}
          onChange={setGrossAmount}
          inputMode="decimal"
          required
        />
        {activity.kind === "share_purchase" || activity.kind === "share_sale" ? (
          <TextField
            label="Transaksjonskostnader (kr)"
            name="transactionCosts"
            value={transactionCosts}
            onChange={setTransactionCosts}
            inputMode="decimal"
            required
          />
        ) : null}
      </div>
      {activity.investmentKind === "norwegian_equity_fund" ? (
        <div className="fieldRow">
          <TextField
            label="Aksjeandel (basispoeng)"
            name="fundEquityRatioBasisPoints"
            value={fundRatio}
            onChange={setFundRatio}
            inputMode="numeric"
            required
          />
          <TextField
            label="Referanse til fondets skatteoppgave"
            name="fundTaxStatementReference"
            value={fundStatement}
            onChange={setFundStatement}
            required
          />
        </div>
      ) : null}
      {activity.kind === "dividend_received"
        && activity.investmentKind === "norwegian_private_company" ? (
        <>
          <SelectField
            label="Konsernunntak fra 3 %-regelen"
            name="groupExceptionClaimed"
            value={groupException ? "true" : "false"}
            onChange={(value) => setGroupException(value === "true")}
            required
          >
            <option value="false">Nei</option>
            <option value="true">Ja</option>
          </SelectField>
          {groupException ? (
            <>
              <div className="fieldRow">
                <TextField
                  label="Eierandel (basispoeng)"
                  name="yearEndOwnershipBasisPoints"
                  value={ownership}
                  onChange={setOwnership}
                  inputMode="numeric"
                  required
                />
                <TextField
                  label="Stemmeandel (basispoeng)"
                  name="yearEndVotingBasisPoints"
                  value={voting}
                  onChange={setVoting}
                  inputMode="numeric"
                  required
                />
              </div>
              <TextField
                label="Referanse til konserndokumentasjon"
                name="groupEvidenceReference"
                value={groupEvidence}
                onChange={setGroupEvidence}
                required
              />
            </>
          ) : null}
        </>
      ) : activity.kind === "dividend_received" ? (
        <input type="hidden" name="groupExceptionClaimed" value="false" />
      ) : null}
      {activity.kind === "dividend_received" ? (
        <CheckboxField
          label="Jeg bekrefter at erstatningsfaktaene gjelder et lovlig vedtatt kontantutbytte."
          name="lawfulDividendConfirmed"
          checked={lawfulDividendConfirmed}
          onChange={setLawfulDividendConfirmed}
          required
        />
      ) : null}
    </>
  );
}

export function InvestmentCorrectionWizard({
  companyId,
  incomeYear,
  activities,
  operationId: initialOperationId,
  replacementActionId: initialReplacementActionId,
  bankTransactions,
  documents,
}: {
  companyId: string;
  incomeYear: number;
  activities: CorrectableInvestmentActivity[];
  operationId?: string;
  replacementActionId?: string;
  bankTransactions: InvestmentEvidenceOption[];
  documents: InvestmentEvidenceOption[];
}) {
  const [operationId] = useState(() => initialOperationId ?? crypto.randomUUID());
  const [replacementActionId] = useState(
    () => initialReplacementActionId ?? crypto.randomUUID(),
  );
  const [activityId, setActivityId] = useState("");
  const [correctionDate, setCorrectionDate] = useState("");
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState<InvestmentEvidenceState>({
    mode: "manual_fallback",
    bankTransactionId: "",
    documentId: "",
    reference: "",
    ownerAttested: false,
  });
  const [replacementEvidence, setReplacementEvidence] = useState<InvestmentEvidenceState>({
    mode: "manual_fallback",
    bankTransactionId: "",
    documentId: "",
    reference: "",
    ownerAttested: false,
  });
  const selected = activities.find((activity) => activity.id === activityId);
  const ready = Boolean(selected && correctionDate && reason.trim()
    && investmentEvidenceComplete(evidence)
    && investmentEvidenceComplete(replacementEvidence));

  if (activities.length === 0) {
    return <Banner variant="info">Det finnes ingen ukorrigerte investeringshendelser.</Banner>;
  }

  return (
    <form action={correctInvestmentAction} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
      <input type="hidden" name="replacementActionId" value={replacementActionId} />
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />
      <SelectField
        label="Hendelse som skal korrigeres"
        name="originalActionId"
        value={activityId}
        onChange={setActivityId}
        required
      >
        <option value="" disabled>Velg hendelse</option>
        {activities.map((activity) => (
          <option key={activity.id} value={activity.id}>{activity.label}</option>
        ))}
      </SelectField>
      {selected ? (
        <>
          <input
            type="hidden"
            name="originalActivityKind"
            value={selected.kind}
          />
          <CorrectionFields key={selected.id} activity={selected} />
        </>
      ) : null}
      <TextField
        label="Korrigeringsdato"
        name="correctionDate"
        value={correctionDate}
        onChange={setCorrectionDate}
        required
      />
      <TextField
        label="Begrunnelse"
        name="reason"
        value={reason}
        onChange={setReason}
        required
      />
      <InvestmentEvidenceFields
        documents={documents}
        state={evidence}
        onChange={setEvidence}
      />
      <InvestmentEvidenceFields
        documents={documents}
        state={replacementEvidence}
        onChange={setReplacementEvidence}
        fieldPrefix="replacement"
      />
      <Banner variant="warning">
        Originalposteringen slettes ikke. Talli lager en full reversering og en ny
        postering, og binder alle tre til samme uforanderlige kontrollspor.
      </Banner>
      <SubmitButton disabled={!ready} pendingLabel="Korrigerer …">
        Reverser og erstatt
      </SubmitButton>
    </form>
  );
}
