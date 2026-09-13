"use client";

import { useEffect, useState } from "react";

import { recordTaxSettlement, previewTaxSettlementAction } from "../../../actions";
import { SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import { ActionPreview, type LedgerLine } from "./ActionPreview";
import { DocStatusSelect, SelectField, TextField } from "./fields";

type Props = { companyId: string; incomeYear: number; operationId?: string };

export function TaxSettlementWizard({
  companyId,
  incomeYear,
  operationId: initialOperationId,
}: Props) {
  const a = ownerCopy.actions;
  const c = a.taxSettlement;

  const [settlementType, setSettlementType] = useState("payable");
  const [settlementDate, setSettlementDate] = useState("");
  const [amount, setAmount] = useState("");
  const [documentStatus, setDocumentStatus] = useState("attached");
  const [operationId] = useState(() => initialOperationId ?? crypto.randomUUID());

  const ready = settlementDate.trim() !== "" && amount.trim() !== "";

  const inputKey = JSON.stringify([settlementDate, amount, settlementType, documentStatus]);
  const [result, setResult] = useState<{ key: string; block: string | null; lines: LedgerLine[] | null } | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!ready) return;
    let active = true;
    const timer = setTimeout(() => {
      void previewTaxSettlementAction({
        settlementDate, amount: Number(amount), settlementType, documentStatus,
      }).then((response) => {
        if (active) setResult({ key: inputKey, block: response.ok ? null : response.error, lines: response.ok ? response.preview.lines : null });
      }).catch(() => {
        if (active) setResult({ key: inputKey, block: "Forhåndsvisningen kunne ikke hentes. Prøv igjen.", lines: null });
      });
    }, 200);
    return () => { active = false; clearTimeout(timer); };
  }, [ready, inputKey, settlementDate, amount, settlementType, documentStatus, retry]);
  const preview = ready && result?.key === inputKey ? result : { block: null, lines: null };
  const pending = ready && result?.key !== inputKey;

  return (
    <form action={recordTaxSettlement} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
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

      {pending ? <p className="fieldHelper" role="status">Henter forhåndsvisning…</p> : <ActionPreview block={preview.block} lines={preview.lines} />}
      {preview.block ? <button type="button" onClick={() => { setResult(null); setRetry((value) => value + 1); }}>Prøv forhåndsvisning igjen</button> : null}

      <SubmitButton disabled={preview.lines === null} pendingLabel={a.pending}>
        {a.confirmCta}
      </SubmitButton>
    </form>
  );
}
