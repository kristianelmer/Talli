"use client";

import { useState } from "react";

import { correctInvestmentSettlementAction } from "../../../actions";
import { Banner, SubmitButton } from "../../../components/ui";
import {
  InvestmentEvidenceFields,
  investmentEvidenceComplete,
  type InvestmentEvidenceOption,
  type InvestmentEvidenceState,
} from "./InvestmentEvidenceFields";
import { SelectField, TextField } from "./fields";

type ActivityKind =
  | "share_purchase"
  | "share_sale"
  | "dividend_received"
  | "fund_distribution_received";

export type CorrectableInvestmentSettlement = {
  settlementId: string;
  eventId: string;
  activityKind: ActivityKind;
  label: string;
  expectedAmount: number;
};

export function InvestmentSettlementCorrectionWizard({
  companyId,
  incomeYear,
  settlements,
  bankTransactions,
  documents,
  operationId: initialOperationId,
  replacementSettlementId: initialReplacementSettlementId,
}: {
  companyId: string;
  incomeYear: number;
  settlements: CorrectableInvestmentSettlement[];
  bankTransactions: InvestmentEvidenceOption[];
  documents: InvestmentEvidenceOption[];
  operationId?: string;
  replacementSettlementId?: string;
}) {
  const [operationId] = useState(
    () => initialOperationId ?? crypto.randomUUID(),
  );
  const [replacementSettlementId] = useState(
    () => initialReplacementSettlementId ?? crypto.randomUUID(),
  );
  const [selectedId, setSelectedId] = useState("");
  const [correctionDate, setCorrectionDate] = useState("");
  const [replacementSettlementDate, setReplacementSettlementDate] = useState("");
  const [reason, setReason] = useState("");
  const [replacementBankTransactionId, setReplacementBankTransactionId] = useState("");
  const [replacementEvidenceReference, setReplacementEvidenceReference] = useState("");
  const [evidence, setEvidence] = useState<InvestmentEvidenceState>({
    mode: "manual_fallback",
    bankTransactionId: "",
    documentId: "",
    reference: "",
    ownerAttested: false,
  });
  const selected = settlements.find((item) => item.settlementId === selectedId);
  const ready = Boolean(
    selected
      && correctionDate
      && replacementSettlementDate
      && reason.trim()
      && replacementBankTransactionId
      && replacementEvidenceReference.trim()
      && investmentEvidenceComplete(evidence),
  );

  if (settlements.length === 0) {
    return (
      <Banner variant="info">
        Det finnes ingen ukorrigerte kontantoppgjør.
      </Banner>
    );
  }

  return (
    <form action={correctInvestmentSettlementAction} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
      <input type="hidden" name="replacementSettlementId" value={replacementSettlementId} />
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />
      <SelectField
        label="Kontantoppgjør som skal korrigeres"
        name="originalSettlementId"
        value={selectedId}
        onChange={setSelectedId}
        required
      >
        <option value="" disabled>Velg kontantoppgjør</option>
        {settlements.map((settlement) => (
          <option key={settlement.settlementId} value={settlement.settlementId}>
            {settlement.label} · {settlement.expectedAmount} kr
          </option>
        ))}
      </SelectField>
      {selected ? (
        <>
          <input type="hidden" name="eventId" value={selected.eventId} />
          <input type="hidden" name="originalActivityKind" value={selected.activityKind} />
          <input type="hidden" name="expectedAmount" value={selected.expectedAmount} />
        </>
      ) : null}
      <div className="fieldRow">
        <TextField
          label="Korrigeringsdato"
          name="correctionDate"
          value={correctionDate}
          onChange={setCorrectionDate}
          required
        />
        <TextField
          label="Ny oppgjørsdato"
          name="replacementSettlementDate"
          value={replacementSettlementDate}
          onChange={setReplacementSettlementDate}
          required
        />
      </div>
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
      <SelectField
        label="Ny bankbevegelse"
        name="replacementBankTransactionId"
        value={replacementBankTransactionId}
        onChange={setReplacementBankTransactionId}
        required
      >
        <option value="" disabled>Velg bankbevegelse</option>
        {bankTransactions.map((transaction) => (
          <option key={transaction.id} value={transaction.id}>
            {transaction.label}
          </option>
        ))}
      </SelectField>
      <TextField
        label="Ny bank- eller oppgjørsreferanse"
        name="replacementEvidenceReference"
        value={replacementEvidenceReference}
        onChange={setReplacementEvidenceReference}
        required
      />
      <Banner variant="warning">
        Talli reverserer bare det opprinnelige kontantoppgjøret og bokfører et
        nytt. Den økonomiske investeringshendelsen og dens beløp endres ikke.
      </Banner>
      <SubmitButton disabled={!ready} pendingLabel="Korrigerer oppgjør …">
        Reverser og erstatt kontantoppgjør
      </SubmitButton>
    </form>
  );
}
