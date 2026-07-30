"use client";

import { useMemo, useState } from "react";

import { recordTaxSettlement } from "../../../actions";
import { SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import {
  taxSettlementLedgerLines,
  validateTaxSettlement,
} from "../../../lib/tax-settlement";
import { ActionPreview, type LedgerLine } from "./ActionPreview";
import { DocStatusSelect, SelectField, TextField } from "./fields";

type Props = { companyId: string; incomeYear: number };

export function TaxSettlementWizard({ companyId, incomeYear }: Props) {
  const a = ownerCopy.actions;
  const c = a.taxSettlement;

  const [settlementType, setSettlementType] = useState("payable");
  const [settlementDate, setSettlementDate] = useState("");
  const [amount, setAmount] = useState("");
  const [documentStatus, setDocumentStatus] = useState("attached");

  const ready = settlementDate.trim() !== "" && amount.trim() !== "";

  const preview = useMemo<{ block: string | null; lines: LedgerLine[] | null }>(() => {
    if (!ready) return { block: null, lines: null };
    try {
      const payload = validateTaxSettlement({
        settlementDate,
        amount: Number(amount),
        settlementType: settlementType as "payable" | "payment" | "refund",
        documentStatus: documentStatus as
          | "attached"
          | "missing_accepted_warning"
          | "not_required",
      });
      return { block: null, lines: taxSettlementLedgerLines(payload) };
    } catch (error) {
      return {
        block: error instanceof Error ? error.message : "Ugyldig skatteoppgjør",
        lines: null,
      };
    }
  }, [ready, settlementDate, amount, settlementType, documentStatus]);

  return (
    <form action={recordTaxSettlement} className="wizardForm">
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />

      <SelectField
        label={c.typeLabel}
        name="settlementType"
        value={settlementType}
        onChange={setSettlementType}
        required
      >
        <option value="payable">{c.typePayable}</option>
        <option value="payment">{c.typePayment}</option>
        <option value="refund">{c.typeRefund}</option>
      </SelectField>
      <div className="fieldRow">
        <TextField
          label={c.dateLabel}
          name="settlementDate"
          value={settlementDate}
          onChange={setSettlementDate}
          placeholder="2025-09-01"
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

      <ActionPreview block={preview.block} lines={preview.lines} />

      <SubmitButton disabled={preview.lines === null} pendingLabel={a.pending}>
        {a.confirmCta}
      </SubmitButton>
    </form>
  );
}
