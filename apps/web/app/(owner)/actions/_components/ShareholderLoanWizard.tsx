"use client";

import { useState } from "react";

import {
  shareholderLoanFormPresentation,
  type ShareholderLoanFormDirection,
} from "../../../../features/corporate-governance";
import { recordShareholderLoan } from "../../../actions";
import { Banner, SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import {
  CheckboxField,
  DocStatusSelect,
  SelectField,
  TextField,
} from "./fields";

type Props = { companyId: string; incomeYear: number; operationId?: string };

export function ShareholderLoanWizard({
  companyId,
  incomeYear,
  operationId: initialOperationId,
}: Props) {
  const a = ownerCopy.actions;
  const c = a.shareholderLoan;

  const [direction, setDirection] = useState<ShareholderLoanFormDirection>("shareholder_to_company");
  const [loanDate, setLoanDate] = useState("");
  const [amount, setAmount] = useState("");
  const [counterpartyName, setCounterpartyName] = useState("");
  const [interestModelled, setInterestModelled] = useState(false);
  const [relatedPartySecurity, setRelatedPartySecurity] = useState(false);
  const [documentStatus, setDocumentStatus] = useState("attached");
  const [operationId] = useState(() => initialOperationId ?? crypto.randomUUID());

  const ready =
    loanDate.trim() !== "" &&
    amount.trim() !== "" &&
    counterpartyName.trim() !== "";
  const presentation = shareholderLoanFormPresentation(direction, relatedPartySecurity);

  return (
    <form action={recordShareholderLoan} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />

      <SelectField
        label={c.directionLabel}
        name="direction"
        value={direction}
        onChange={(value) => setDirection(value as ShareholderLoanFormDirection)}
        required
      >
        <option value="shareholder_to_company">{c.dirToCompany}</option>
        <option value="company_to_corporate_shareholder">
          {c.dirToCorporate}
        </option>
        <option value="company_to_personal_shareholder">
          {c.dirToPersonal}
        </option>
      </SelectField>
      <TextField
        label={c.counterpartyLabel}
        name="counterpartyName"
        value={counterpartyName}
        onChange={setCounterpartyName}
        required
      />
      <div className="fieldRow">
        <TextField
          label={c.dateLabel}
          name="loanDate"
          value={loanDate}
          onChange={setLoanDate}
          placeholder="2025-03-01"
          helper={a.dateHelp}
          required
        />
        <TextField
          label={c.amountLabel}
          name="amount"
          value={amount}
          onChange={setAmount}
          inputMode="decimal"
          required
        />
      </div>
      <DocStatusSelect value={documentStatus} onChange={setDocumentStatus} />
      <CheckboxField
        label={c.interestLabel}
        name="interestModelled"
        checked={interestModelled}
        onChange={setInterestModelled}
      />
      <CheckboxField
        label={c.securityLabel}
        name="relatedPartySecurity"
        checked={relatedPartySecurity}
        onChange={setRelatedPartySecurity}
      />

      <Banner variant={presentation.block ? "danger" : "info"} title={presentation.title}>
        {presentation.block ?? presentation.treatment}
      </Banner>

      <SubmitButton disabled={!ready || presentation.block !== null} pendingLabel={a.pending}>
        {a.confirmCta}
      </SubmitButton>
    </form>
  );
}
