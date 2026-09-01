"use client";

import { useState } from "react";

import { recordFundDistribution } from "../../../actions";
import { Banner, SubmitButton } from "../../../components/ui";
import { SelectField, TextField } from "./fields";

type FundInvestment = { id: string; name: string };

export function FundDistributionWizard({
  companyId,
  incomeYear,
  investments,
  operationId: initialOperationId,
}: {
  companyId: string;
  incomeYear: number;
  investments: FundInvestment[];
  operationId?: string;
}) {
  const [operationId] = useState(() => initialOperationId ?? crypto.randomUUID());
  const [positionId, setPositionId] = useState("");
  const [fundName, setFundName] = useState("");
  const [entitlementDate, setEntitlementDate] = useState("");
  const [paidDate, setPaidDate] = useState("");
  const [grossAmount, setGrossAmount] = useState("");
  const [equityRatio, setEquityRatio] = useState("");
  const [statementReference, setStatementReference] = useState("");
  const [evidenceReference, setEvidenceReference] = useState("");
  const ready = Boolean(positionId && fundName.trim() && entitlementDate && paidDate
    && grossAmount.trim() && equityRatio.trim() && statementReference.trim()
    && evidenceReference.trim());

  if (investments.length === 0) {
    return (
      <Banner variant="info">
        Registrer først en norsk fondsposisjon med komplett skatteoppgave.
      </Banner>
    );
  }

  return (
    <form action={recordFundDistribution} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />
      <SelectField
        label="Fondsposisjon"
        name="positionId"
        value={positionId}
        onChange={(value) => {
          setPositionId(value);
          setFundName(investments.find((item) => item.id === value)?.name ?? "");
        }}
        required
      >
        <option value="" disabled>Velg fond</option>
        {investments.map((investment) => (
          <option key={investment.id} value={investment.id}>{investment.name}</option>
        ))}
      </SelectField>
      <input type="hidden" name="fundName" value={fundName} />
      <div className="fieldRow">
        <TextField
          label="Rettighetsdato"
          name="entitlementDate"
          value={entitlementDate}
          onChange={setEntitlementDate}
          placeholder="2026-05-01"
          required
        />
        <TextField
          label="Utbetalingsdato"
          name="paidDate"
          value={paidDate}
          onChange={setPaidDate}
          placeholder="2026-05-15"
          required
        />
      </div>
      <TextField
        label="Brutto utdeling (kr)"
        name="grossAmount"
        value={grossAmount}
        onChange={setGrossAmount}
        inputMode="decimal"
        required
      />
      <div className="fieldRow">
        <TextField
          label="Aksjeandel ved årets start (basispoeng)"
          name="openingFundEquityRatioBasisPoints"
          value={equityRatio}
          onChange={setEquityRatio}
          inputMode="numeric"
          helper="0–10 000. Talli splitter utdelingen etter denne andelen."
          required
        />
        <TextField
          label="Referanse til fondets skatteoppgave"
          name="fundTaxStatementReference"
          value={statementReference}
          onChange={setStatementReference}
          required
        />
      </div>
      <TextField
        label="Utbetalings- eller bilagsreferanse"
        name="evidenceReference"
        value={evidenceReference}
        onChange={setEvidenceReference}
        required
      />
      <Banner variant="info">
        Aksjedelen behandles etter fritaksmetoden. Rentedelen inntektsføres fullt,
        og Talli viser begge beløpene før årsavslutning.
      </Banner>
      <SubmitButton disabled={!ready} pendingLabel="Poster …">
        Poster fondsutdeling
      </SubmitButton>
    </form>
  );
}
