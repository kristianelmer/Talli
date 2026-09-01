"use client";

import { useState } from "react";

import { recordInvestmentYearEndMeasurementAction } from "../../../actions";
import { SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import {
  InvestmentEvidenceFields,
  investmentEvidenceComplete,
  type InvestmentEvidenceOption,
  type InvestmentEvidenceState,
} from "./InvestmentEvidenceFields";
import { SelectField, TextField } from "./fields";

type Position = {
  id: string;
  name: string;
  classification: string;
  bookValue: number;
  taxBasis: number;
};

type Props = {
  companyId: string;
  documents: InvestmentEvidenceOption[];
  incomeYear: number;
  operationId?: string;
  positions: Position[];
};

export function InvestmentMeasurementWizard({
  companyId,
  documents,
  incomeYear,
  operationId: initialOperationId,
  positions,
}: Props) {
  const copy = ownerCopy.actions.investmentMeasurement;
  const [positionId, setPositionId] = useState(positions[0]?.id ?? "");
  const selected = positions.find((position) => position.id === positionId);
  const [observedValue, setObservedValue] = useState("");
  const [taxValue, setTaxValue] = useState("");
  const [evidence, setEvidence] = useState<InvestmentEvidenceState>({
    mode: "manual_fallback",
    bankTransactionId: "",
    documentId: "",
    reference: "",
    ownerAttested: false,
  });
  const [operationId] = useState(
    () => initialOperationId ?? crypto.randomUUID(),
  );
  const ready = Boolean(
    positionId
      && observedValue.trim()
      && taxValue.trim()
      && Number(observedValue) >= 0
      && Number(taxValue) >= 0
      && investmentEvidenceComplete(evidence),
  );

  return (
    <form action={recordInvestmentYearEndMeasurementAction} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />

      <SelectField
        label={copy.positionLabel}
        name="positionId"
        value={positionId}
        onChange={setPositionId}
        required
      >
        <option value="" disabled>{copy.positionPlaceholder}</option>
        {positions.map((position) => (
          <option key={position.id} value={position.id}>
            {position.name} · bokført {position.bookValue} kr
          </option>
        ))}
      </SelectField>
      {selected ? (
        <p className="cardNote">
          Bokført verdi {selected.bookValue} kr · skattemessig kostpris {selected.taxBasis} kr · {selected.classification}
        </p>
      ) : null}
      <div className="fieldRow">
        <TextField
          label={copy.observedValueLabel}
          name="observedOrRecoverableValue"
          value={observedValue}
          onChange={setObservedValue}
          inputMode="decimal"
          helper={copy.observedValueHelp}
          required
        />
        <TextField
          label={copy.taxValueLabel}
          name="taxValue"
          value={taxValue}
          onChange={setTaxValue}
          inputMode="decimal"
          helper={copy.taxValueHelp}
          required
        />
      </div>
      <InvestmentEvidenceFields
        documents={documents}
        state={evidence}
        onChange={setEvidence}
      />
      <p className="cardNote">{copy.policyNote}</p>
      <SubmitButton disabled={!ready} pendingLabel={ownerCopy.actions.pending}>
        {ownerCopy.actions.confirmCta}
      </SubmitButton>
    </form>
  );
}
