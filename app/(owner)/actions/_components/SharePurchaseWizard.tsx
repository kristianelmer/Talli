"use client";

import { useMemo, useState } from "react";

import { recordSharePurchase } from "../../../actions";
import { SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import {
  sharePurchaseLedgerLines,
  validateSharePurchase,
} from "../../../lib/share-purchase";
import { ActionPreview, type LedgerLine } from "./ActionPreview";
import { DocStatusSelect, SelectField, TextField } from "./fields";

type Props = { companyId: string; incomeYear: number };

export function SharePurchaseWizard({ companyId, incomeYear }: Props) {
  const a = ownerCopy.actions;
  const c = a.sharePurchase;
  const [investmentName, setInvestmentName] = useState("");
  const [investmentKey, setInvestmentKey] = useState("");
  const [orgNumber, setOrgNumber] = useState("");
  const [kind, setKind] = useState("norwegian_private_company");
  const [treatment, setTreatment] = useState("fritaksmetoden");
  const [acquisitionDate, setAcquisitionDate] = useState("");
  const [shareCount, setShareCount] = useState("");
  const [purchaseAmount, setPurchaseAmount] = useState("");
  const [documentStatus, setDocumentStatus] = useState("attached");

  const ready =
    investmentName.trim() !== "" &&
    investmentKey.trim() !== "" &&
    acquisitionDate.trim() !== "" &&
    shareCount.trim() !== "" &&
    purchaseAmount.trim() !== "";

  const preview = useMemo<{ block: string | null; lines: LedgerLine[] | null }>(() => {
    if (!ready) return { block: null, lines: null };
    try {
      const payload = validateSharePurchase({
        investmentKey,
        investmentName,
        investmentKind: kind as
          | "norwegian_private_company"
          | "simple_listed_security",
        taxTreatment: treatment as
          | "fritaksmetoden"
          | "outside_fritaksmetoden"
          | "needs_accountant",
        acquisitionDate,
        shareCount: Number(shareCount),
        purchaseAmount: Number(purchaseAmount),
        orgNumber: orgNumber || null,
        documentStatus: documentStatus as
          | "attached"
          | "missing_accepted_warning"
          | "not_required",
      });
      return { block: null, lines: sharePurchaseLedgerLines(payload) };
    } catch (error) {
      return {
        block: error instanceof Error ? error.message : "Ugyldig aksjekjøp",
        lines: null,
      };
    }
  }, [
    ready,
    investmentKey,
    investmentName,
    kind,
    treatment,
    acquisitionDate,
    shareCount,
    purchaseAmount,
    orgNumber,
    documentStatus,
  ]);

  return (
    <form action={recordSharePurchase} className="wizardForm">
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />

      <TextField
        label={c.nameLabel}
        name="investmentName"
        value={investmentName}
        onChange={setInvestmentName}
        required
      />
      <div className="fieldRow">
        <TextField
          label={c.keyLabel}
          name="investmentKey"
          value={investmentKey}
          onChange={setInvestmentKey}
          helper={c.keyHelp}
          required
        />
        <TextField
          label={c.orgLabel}
          name="orgNumber"
          value={orgNumber}
          onChange={setOrgNumber}
          inputMode="numeric"
        />
      </div>
      <div className="fieldRow">
        <SelectField
          label={a.investmentKind.label}
          name="investmentKind"
          value={kind}
          onChange={setKind}
          required
        >
          <option value="norwegian_private_company">
            {a.investmentKind.norwegianPrivate}
          </option>
          <option value="simple_listed_security">
            {a.investmentKind.listed}
          </option>
        </SelectField>
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
      <div className="fieldRow">
        <TextField
          label={c.dateLabel}
          name="acquisitionDate"
          value={acquisitionDate}
          onChange={setAcquisitionDate}
          placeholder="2025-01-01"
          helper={a.dateHelp}
          required
        />
        <TextField
          label={c.sharesLabel}
          name="shareCount"
          value={shareCount}
          onChange={setShareCount}
          inputMode="decimal"
          required
        />
      </div>
      <div className="fieldRow">
        <TextField
          label={c.amountLabel}
          name="purchaseAmount"
          value={purchaseAmount}
          onChange={setPurchaseAmount}
          inputMode="decimal"
          required
        />
        <DocStatusSelect value={documentStatus} onChange={setDocumentStatus} />
      </div>

      <ActionPreview block={preview.block} lines={preview.lines} />

      <SubmitButton disabled={preview.lines === null} pendingLabel={a.pending}>
        {a.confirmCta}
      </SubmitButton>
    </form>
  );
}
