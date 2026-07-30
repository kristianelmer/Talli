"use client";

import { useMemo, useState } from "react";

import { recordShareholderLoan } from "../../../actions";
import { SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import {
  shareholderLoanLedgerLines,
  validateShareholderLoan,
} from "../../../lib/shareholder-loan";
import { ActionPreview, type LedgerLine } from "./ActionPreview";
import {
  CheckboxField,
  DocStatusSelect,
  SelectField,
  TextField,
} from "./fields";

type Props = { companyId: string; incomeYear: number };

export function ShareholderLoanWizard({ companyId, incomeYear }: Props) {
  const a = ownerCopy.actions;
  const c = a.shareholderLoan;

  const [direction, setDirection] = useState("shareholder_to_company");
  const [loanDate, setLoanDate] = useState("");
  const [amount, setAmount] = useState("");
  const [counterpartyName, setCounterpartyName] = useState("");
  const [interestModelled, setInterestModelled] = useState(false);
  const [relatedPartySecurity, setRelatedPartySecurity] = useState(false);
  const [documentStatus, setDocumentStatus] = useState("attached");

  // These two "needs-accountant" branches are surfaced immediately, before the
  // rest of the form is complete, so the owner is not led down a dead end.
  const hardBlock =
    direction === "company_to_personal_shareholder"
      ? c.personalBlock
      : relatedPartySecurity
        ? c.securityBlock
        : null;

  const ready =
    loanDate.trim() !== "" &&
    amount.trim() !== "" &&
    counterpartyName.trim() !== "";

  const preview = useMemo<{ block: string | null; lines: LedgerLine[] | null }>(() => {
    if (hardBlock) return { block: hardBlock, lines: null };
    if (!ready) return { block: null, lines: null };
    try {
      const payload = validateShareholderLoan({
        loanDate,
        amount: Number(amount),
        direction: direction as
          | "shareholder_to_company"
          | "company_to_corporate_shareholder"
          | "company_to_personal_shareholder",
        counterpartyName,
        documentStatus: documentStatus as
          | "attached"
          | "missing_accepted_warning"
          | "not_required",
        interestModelled,
        relatedPartySecurity,
      });
      return { block: null, lines: shareholderLoanLedgerLines(payload) };
    } catch (error) {
      return {
        block: error instanceof Error ? error.message : "Ugyldig aksjonærlån",
        lines: null,
      };
    }
  }, [
    hardBlock,
    ready,
    loanDate,
    amount,
    direction,
    counterpartyName,
    documentStatus,
    interestModelled,
    relatedPartySecurity,
  ]);

  return (
    <form action={recordShareholderLoan} className="wizardForm">
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />

      <SelectField
        label={c.directionLabel}
        name="direction"
        value={direction}
        onChange={setDirection}
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

      <ActionPreview block={preview.block} lines={preview.lines} />

      <SubmitButton disabled={preview.lines === null} pendingLabel={a.pending}>
        {a.confirmCta}
      </SubmitButton>
    </form>
  );
}
