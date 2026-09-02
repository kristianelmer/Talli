"use client";

import { useState } from "react";

import { settleInvestmentCashAction } from "../../../actions";
import { Banner, SubmitButton } from "../../../components/ui";
import { SelectField, TextField } from "./fields";
import type { InvestmentEvidenceOption } from "./InvestmentEvidenceFields";

export type PendingInvestmentSettlement = {
  eventId: string;
  label: string;
  expectedAmount: number;
};

export function InvestmentSettlementWizard({
  companyId,
  incomeYear,
  events,
  bankTransactions,
  operationId: initialOperationId,
}: {
  companyId: string;
  incomeYear: number;
  events: PendingInvestmentSettlement[];
  bankTransactions: InvestmentEvidenceOption[];
  operationId?: string;
}) {
  const [operationId] = useState(
    () => initialOperationId ?? crypto.randomUUID(),
  );
  const [eventId, setEventId] = useState("");
  const [settlementDate, setSettlementDate] = useState("");
  const [bankTransactionId, setBankTransactionId] = useState("");
  const [evidenceReference, setEvidenceReference] = useState("");
  const selected = events.find((event) => event.eventId === eventId);
  const ready = Boolean(
    selected
      && settlementDate
      && bankTransactionId
      && evidenceReference.trim(),
  );

  if (events.length === 0) {
    return (
      <Banner variant="info">
        Det finnes ingen investeringshendelser som venter på kontantoppgjør.
      </Banner>
    );
  }

  return (
    <form action={settleInvestmentCashAction} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />
      <SelectField
        label="Hendelse som skal avstemmes"
        name="eventId"
        value={eventId}
        onChange={setEventId}
        required
      >
        <option value="" disabled>Velg hendelse</option>
        {events.map((event) => (
          <option key={event.eventId} value={event.eventId}>
            {event.label} · {event.expectedAmount} kr
          </option>
        ))}
      </SelectField>
      <TextField
        label="Oppgjørsdato"
        name="settlementDate"
        value={settlementDate}
        onChange={setSettlementDate}
        placeholder={`${incomeYear}-05-15`}
        required
      />
      <SelectField
        label="Bankbevegelse"
        name="bankTransactionId"
        value={bankTransactionId}
        onChange={setBankTransactionId}
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
        label="Bank- eller oppgjørsreferanse"
        name="evidenceReference"
        value={evidenceReference}
        onChange={setEvidenceReference}
        helper="Referansen skal identifisere kontantoppgjøret. Talli binder den valgte bankbevegelsens kildehash på serveren."
        required
      />
      <Banner variant="info">
        Investeringshendelsen er allerede regnskapsført. Denne handlingen
        avstemmer bare det separate kontantoppgjøret mot banken.
      </Banner>
      <SubmitButton disabled={!ready} pendingLabel="Avstemmer …">
        Avstem kontantoppgjør
      </SubmitButton>
    </form>
  );
}
