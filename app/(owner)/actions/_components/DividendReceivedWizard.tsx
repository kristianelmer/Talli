"use client";

import { useMemo, useState, type ReactNode } from "react";

import { recordDividendReceived } from "../../../actions";
import { Banner, SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import {
  dividendReceivedLedgerLines,
  validateDividendReceived,
} from "../../../lib/dividend-received";
import { ActionPreview, type LedgerLine } from "./ActionPreview";
import { DocStatusSelect, SelectField, TextField } from "./fields";

export type DividendInvestment = { investment_key: string; name: string };

type Props = {
  companyId: string;
  incomeYear: number;
  investments: DividendInvestment[];
};

export function DividendReceivedWizard({
  companyId,
  incomeYear,
  investments,
}: Props) {
  const a = ownerCopy.actions;
  const c = a.dividendReceived;

  const [linkedInvestmentId, setLinkedInvestmentId] = useState("");
  const [payingCompanyName, setPayingCompanyName] = useState("");
  const [declaredDate, setDeclaredDate] = useState("");
  const [paidDate, setPaidDate] = useState("");
  const [grossAmount, setGrossAmount] = useState("");
  const [treatment, setTreatment] = useState("fritaksmetoden");
  const [documentStatus, setDocumentStatus] = useState("attached");

  const ready =
    linkedInvestmentId.trim() !== "" &&
    payingCompanyName.trim() !== "" &&
    declaredDate.trim() !== "" &&
    paidDate.trim() !== "" &&
    grossAmount.trim() !== "";

  const preview = useMemo<{
    block: string | null;
    lines: LedgerLine[] | null;
    summary: ReactNode;
  }>(() => {
    if (!ready) return { block: null, lines: null, summary: null };
    try {
      const payload = validateDividendReceived({
        payingCompanyName,
        declaredDate,
        paidDate,
        grossAmount: Number(grossAmount),
        linkedInvestmentId,
        taxTreatment: treatment as
          | "fritaksmetoden"
          | "outside_fritaksmetoden"
          | "needs_accountant",
        documentStatus: documentStatus as
          | "attached"
          | "missing_accepted_warning"
          | "not_required",
      });
      return {
        block: null,
        lines: dividendReceivedLedgerLines(payload),
        summary: c.addBackNote(payload.taxable_add_back),
      };
    } catch (error) {
      return {
        block:
          error instanceof Error ? error.message : "Ugyldig mottatt utbytte",
        lines: null,
        summary: null,
      };
    }
  }, [
    ready,
    payingCompanyName,
    declaredDate,
    paidDate,
    grossAmount,
    linkedInvestmentId,
    treatment,
    documentStatus,
    c,
  ]);

  if (investments.length === 0) {
    return <Banner variant="info">{c.noInvestments}</Banner>;
  }

  return (
    <form action={recordDividendReceived} className="wizardForm">
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />

      <SelectField
        label={c.investmentLabel}
        name="linkedInvestmentId"
        value={linkedInvestmentId}
        onChange={setLinkedInvestmentId}
        required
      >
        <option value="" disabled>
          {c.investmentPlaceholder}
        </option>
        {investments.map((investment) => (
          <option key={investment.investment_key} value={investment.investment_key}>
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
      <div className="fieldRow">
        <TextField
          label={c.amountLabel}
          name="grossAmount"
          value={grossAmount}
          onChange={setGrossAmount}
          inputMode="decimal"
          required
        />
        <SelectField
          label={a.taxTreatment.label}
          name="taxTreatment"
          value={treatment}
          onChange={setTreatment}
          required
        >
          <option value="fritaksmetoden">{a.taxTreatment.fritak}</option>
          <option value="outside_fritaksmetoden">{a.taxTreatment.outside}</option>
          <option value="needs_accountant">{a.taxTreatment.needsAccountant}</option>
        </SelectField>
      </div>
      <DocStatusSelect value={documentStatus} onChange={setDocumentStatus} />

      <ActionPreview
        block={preview.block}
        lines={preview.lines}
        summary={preview.summary}
      />

      <SubmitButton disabled={preview.lines === null} pendingLabel={a.pending}>
        {a.confirmCta}
      </SubmitButton>
    </form>
  );
}
