"use client";

import { useState } from "react";

import { recordShareSale } from "../../../actions";
import { Banner, SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import {
  formatInvestmentUnits,
  hasPositiveInvestmentUnits,
} from "../../../../features/investments";
import {
  InvestmentEvidenceFields,
  investmentEvidenceComplete,
  type InvestmentEvidenceOption,
  type InvestmentEvidenceState,
} from "./InvestmentEvidenceFields";
import { SelectField, TextField } from "./fields";

export type SalePosition = {
  id: string;
  name: string;
  share_count: string;
  lot_history_status: "complete" | "needs_reconstruction";
  kind: "norwegian_private_company" | "norwegian_listed_share" | "norwegian_equity_fund";
};

type Props = {
  companyId: string;
  incomeYear: number;
  positions: SalePosition[];
  operationId?: string;
  bankTransactions: InvestmentEvidenceOption[];
  documents: InvestmentEvidenceOption[];
};

export function ShareSaleWizard({
  companyId,
  incomeYear,
  positions,
  operationId: initialOperationId,
  bankTransactions,
  documents,
}: Props) {
  const a = ownerCopy.actions;
  const c = a.shareSale;
  const sellable = positions.filter(
    (position) => hasPositiveInvestmentUnits(position.share_count)
      && position.lot_history_status === "complete",
  );

  const [positionId, setPositionId] = useState("");
  const [saleDate, setSaleDate] = useState("");
  const [soldShareCount, setSoldShareCount] = useState("");
  const [proceeds, setProceeds] = useState("");
  const [transactionCosts, setTransactionCosts] = useState("0");
  const [fundEquityRatio, setFundEquityRatio] = useState("");
  const [fundStatement, setFundStatement] = useState("");
  const [evidence, setEvidence] = useState<InvestmentEvidenceState>({
    mode: "manual_fallback",
    bankTransactionId: "",
    documentId: "",
    reference: "",
    ownerAttested: false,
  });
  const [operationId] = useState(() => initialOperationId ?? crypto.randomUUID());

  const selected = sellable.find((position) => position.id === positionId);
  const ready =
    Boolean(selected) &&
    saleDate.trim() !== "" &&
    soldShareCount.trim() !== "" &&
    proceeds.trim() !== "" &&
    investmentEvidenceComplete(evidence) &&
    (selected?.kind !== "norwegian_equity_fund"
      || (fundEquityRatio.trim() !== "" && fundStatement.trim() !== ""));

  if (sellable.length === 0) {
    return <Banner variant="info">{c.noPositions}</Banner>;
  }

  return (
    <form action={recordShareSale} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />
      <input type="hidden" name="documentStatus" value="not_required" />

      <SelectField
        label={c.positionLabel}
        name="positionId"
        value={positionId}
        onChange={setPositionId}
        required
      >
        <option value="" disabled>
          {c.positionPlaceholder}
        </option>
        {sellable.map((position) => (
          <option key={position.id} value={position.id}>
            {position.name} — {c.ofShares(formatInvestmentUnits(position.share_count))}
          </option>
        ))}
      </SelectField>
      <div className="fieldRow">
        <TextField
          label={c.dateLabel}
          name="saleDate"
          value={saleDate}
          onChange={setSaleDate}
          placeholder="2025-08-01"
          helper={a.dateHelp}
          required
        />
        <TextField
          label={c.sharesLabel}
          name="soldShareCount"
          value={soldShareCount}
          onChange={setSoldShareCount}
          inputMode="decimal"
          required
        />
      </div>
      <TextField
        label={c.proceedsLabel}
        name="proceeds"
        value={proceeds}
        onChange={setProceeds}
        inputMode="decimal"
        required
      />
      <div className="fieldRow">
        <TextField
          label="Transaksjonskostnader (kr)"
          name="transactionCosts"
          value={transactionCosts}
          onChange={setTransactionCosts}
          inputMode="decimal"
          required
        />
      </div>

      {selected?.kind === "norwegian_equity_fund" ? (
        <div className="fieldRow">
          <TextField
            label="Aksjeandel ved salg (basispoeng)"
            name="saleYearFundEquityRatioBasisPoints"
            value={fundEquityRatio}
            onChange={setFundEquityRatio}
            inputMode="numeric"
            required
          />
          <TextField
            label="Referanse til fondets skatteoppgave"
            name="fundTaxStatementReference"
            value={fundStatement}
            onChange={setFundStatement}
            required
          />
        </div>
      ) : null}

      <Banner variant="info">{c.fifoNote}</Banner>

      <InvestmentEvidenceFields
        bankTransactions={bankTransactions}
        documents={documents}
        state={evidence}
        onChange={setEvidence}
      />

      <SubmitButton disabled={!ready} pendingLabel={a.pending}>
        {a.confirmCta}
      </SubmitButton>
    </form>
  );
}
