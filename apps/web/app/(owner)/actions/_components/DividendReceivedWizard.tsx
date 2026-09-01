"use client";

import { useState } from "react";

import { recordDividendReceived } from "../../../actions";
import { Banner, SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import { SelectField, TextField } from "./fields";

export type DividendInvestment = {
  id: string;
  name: string;
  kind: "norwegian_private_company" | "norwegian_listed_share" | "norwegian_equity_fund";
};

type Props = {
  companyId: string;
  incomeYear: number;
  investments: DividendInvestment[];
  operationId?: string;
};

export function DividendReceivedWizard({
  companyId,
  incomeYear,
  investments,
  operationId: initialOperationId,
}: Props) {
  const a = ownerCopy.actions;
  const c = a.dividendReceived;
  const [positionId, setPositionId] = useState("");
  const [payingCompanyName, setPayingCompanyName] = useState("");
  const [declaredDate, setDeclaredDate] = useState("");
  const [paidDate, setPaidDate] = useState("");
  const [grossAmount, setGrossAmount] = useState("");
  const [groupException, setGroupException] = useState(false);
  const [ownershipBasisPoints, setOwnershipBasisPoints] = useState("");
  const [votingBasisPoints, setVotingBasisPoints] = useState("");
  const [groupEvidence, setGroupEvidence] = useState("");
  const [evidenceReference, setEvidenceReference] = useState("");
  const [operationId] = useState(() => initialOperationId ?? crypto.randomUUID());
  const selectedInvestment = investments.find((investment) => investment.id === positionId);
  const groupExceptionAvailable = selectedInvestment?.kind === "norwegian_private_company";
  const ready =
    positionId.trim() !== "" &&
    payingCompanyName.trim() !== "" &&
    declaredDate.trim() !== "" &&
    paidDate.trim() !== "" &&
    grossAmount.trim() !== "" &&
    evidenceReference.trim() !== "" &&
    (!groupExceptionAvailable || !groupException || (
      ownershipBasisPoints.trim() !== "" && votingBasisPoints.trim() !== ""
      && groupEvidence.trim() !== ""
    ));

  if (investments.length === 0) {
    return <Banner variant="info">{c.noInvestments}</Banner>;
  }

  return (
    <form action={recordDividendReceived} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />
      <input type="hidden" name="taxTreatment" value="fritaksmetoden" />
      <input type="hidden" name="documentStatus" value="not_required" />

      <SelectField
        label={c.investmentLabel}
        name="positionId"
        value={positionId}
        onChange={(value) => {
          setPositionId(value);
          if (investments.find((investment) => investment.id === value)?.kind !== "norwegian_private_company") {
            setGroupException(false);
            setOwnershipBasisPoints("");
            setVotingBasisPoints("");
            setGroupEvidence("");
          }
        }}
        required
      >
        <option value="" disabled>
          {c.investmentPlaceholder}
        </option>
        {investments.map((investment) => (
          <option key={investment.id} value={investment.id}>
            {investment.name}
          </option>
        ))}
      </SelectField>
      <TextField
        label={c.payerLabel}
        name="payingCompanyName"
        value={payingCompanyName}
        onChange={setPayingCompanyName}
        required
      />
      <TextField
        label="Utbytte- eller bilagsreferanse"
        name="evidenceReference"
        value={evidenceReference}
        onChange={setEvidenceReference}
        required
      />
      {groupExceptionAvailable ? (
        <SelectField
          label="Konsernunntak fra 3 %-regelen"
          name="groupExceptionClaimed"
          value={groupException ? "true" : "false"}
          onChange={(value) => setGroupException(value === "true")}
          required
        >
          <option value="false">Nei</option>
          <option value="true">Ja, over 90 % av aksjer og stemmer</option>
        </SelectField>
      ) : (
        <input type="hidden" name="groupExceptionClaimed" value="false" />
      )}
      {groupExceptionAvailable && groupException ? (
        <>
          <div className="fieldRow">
            <TextField
              label="Eierandel ved årsslutt (basispoeng)"
              name="yearEndOwnershipBasisPoints"
              value={ownershipBasisPoints}
              onChange={setOwnershipBasisPoints}
              inputMode="numeric"
              required
            />
            <TextField
              label="Stemmeandel ved årsslutt (basispoeng)"
              name="yearEndVotingBasisPoints"
              value={votingBasisPoints}
              onChange={setVotingBasisPoints}
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
      <div className="fieldRow">
        <TextField
          label={c.declaredLabel}
          name="declaredDate"
          value={declaredDate}
          onChange={setDeclaredDate}
          placeholder="2025-04-01"
          helper={a.dateHelp}
          required
        />
        <TextField
          label={c.paidLabel}
          name="paidDate"
          value={paidDate}
          onChange={setPaidDate}
          placeholder="2025-04-15"
          helper={a.dateHelp}
          required
        />
      </div>
      <TextField
        label={c.amountLabel}
        name="grossAmount"
        value={grossAmount}
        onChange={setGrossAmount}
        inputMode="decimal"
        required
      />

      <Banner variant="info">{c.policyNote}</Banner>

      <SubmitButton disabled={!ready} pendingLabel={a.pending}>
        {a.confirmCta}
      </SubmitButton>
    </form>
  );
}
