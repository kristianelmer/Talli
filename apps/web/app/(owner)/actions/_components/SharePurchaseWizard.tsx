"use client";

import { useState } from "react";

import { recordSharePurchase } from "../../../actions";
import { SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import { SelectField, TextField } from "./fields";

type Props = { companyId: string; incomeYear: number; operationId?: string };

export function SharePurchaseWizard({
  companyId,
  incomeYear,
  operationId: initialOperationId,
}: Props) {
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
  const [operationId] = useState(() => initialOperationId ?? crypto.randomUUID());

  const ready =
    investmentName.trim() !== "" &&
    investmentKey.trim() !== "" &&
    acquisitionDate.trim() !== "" &&
    shareCount.trim() !== "" &&
    purchaseAmount.trim() !== "";

  return (
    <form action={recordSharePurchase} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
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
        </SelectField>
        <SelectField
          label={a.taxTreatment.label}
          name="taxTreatment"
          value={treatment}
          onChange={setTreatment}
          required
        >
          <option value="fritaksmetoden">{a.taxTreatment.fritak}</option>
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
        <input type="hidden" name="documentStatus" value="not_required" />
      </div>

      <SubmitButton disabled={!ready} pendingLabel={a.pending}>
        {a.confirmCta}
      </SubmitButton>
    </form>
  );
}
