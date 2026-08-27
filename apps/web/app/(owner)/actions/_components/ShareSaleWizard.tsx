"use client";

import { useMemo, useState, type ReactNode } from "react";

import { recordShareSale } from "../../../actions";
import { Banner, SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import {
  shareSaleLedgerLines,
  validateShareSale,
} from "../../../lib/share-sale";
import type { ShareAcquisitionLot } from "../../../lib/share-lots";
import { ActionPreview, formatKr, type LedgerLine } from "./ActionPreview";
import { DocStatusSelect, SelectField, TextField } from "./fields";

export type SalePosition = {
  id: string;
  investment_key: string;
  name: string;
  share_count: number;
  cost_basis: number;
  lot_history_status: "complete" | "needs_reconstruction";
  acquisition_lots: ShareAcquisitionLot[];
};

type Props = {
  companyId: string;
  incomeYear: number;
  positions: SalePosition[];
  operationId?: string;
};

export function ShareSaleWizard({
  companyId,
  incomeYear,
  positions,
  operationId: initialOperationId,
}: Props) {
  const a = ownerCopy.actions;
  const c = a.shareSale;
  const sellable = positions.filter(
    (position) => position.share_count > 0 && position.lot_history_status === "complete",
  );

  const [positionId, setPositionId] = useState("");
  const [saleDate, setSaleDate] = useState("");
  const [soldShareCount, setSoldShareCount] = useState("");
  const [proceeds, setProceeds] = useState("");
  const [documentStatus, setDocumentStatus] = useState("attached");
  const [operationId] = useState(() => initialOperationId ?? crypto.randomUUID());

  const selected = sellable.find((position) => position.id === positionId);
  const ready =
    Boolean(selected) &&
    saleDate.trim() !== "" &&
    soldShareCount.trim() !== "" &&
    proceeds.trim() !== "";

  const preview = useMemo<{
    block: string | null;
    lines: LedgerLine[] | null;
    summary: ReactNode;
  }>(() => {
    if (!ready || !selected) return { block: null, lines: null, summary: null };
    try {
      const payload = validateShareSale({
        positionId: selected.id,
        investmentKey: selected.investment_key,
        investmentName: selected.name,
        currentShareCount: selected.share_count,
        currentCostBasis: selected.cost_basis,
        acquisitionLots: selected.acquisition_lots,
        saleDate,
        soldShareCount: Number(soldShareCount),
        proceeds: Number(proceeds),
        documentStatus: documentStatus as
          | "attached"
          | "missing_accepted_warning"
          | "not_required",
      });
      const summary = (
        <>
          {payload.gain_or_loss > 0
            ? `${c.gainLabel}: ${formatKr(payload.gain_or_loss)}`
            : payload.gain_or_loss < 0
              ? `${c.lossLabel}: ${formatKr(Math.abs(payload.gain_or_loss))}`
              : null}
          {payload.gain_or_loss !== 0 ? " · " : ""}
          {`${c.remainingLabel}: ${payload.remaining_share_count}`}
        </>
      );
      return { block: null, lines: shareSaleLedgerLines(payload), summary };
    } catch (error) {
      return {
        block: error instanceof Error ? error.message : "Ugyldig aksjesalg",
        lines: null,
        summary: null,
      };
    }
  }, [ready, selected, saleDate, soldShareCount, proceeds, documentStatus, c]);

  if (sellable.length === 0) {
    return <Banner variant="info">{c.noPositions}</Banner>;
  }

  return (
    <form action={recordShareSale} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />

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
            {position.name} — {c.ofShares(position.share_count)}
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
      <div className="fieldRow">
        <TextField
          label={c.proceedsLabel}
          name="proceeds"
          value={proceeds}
          onChange={setProceeds}
          inputMode="decimal"
          required
        />
        <DocStatusSelect value={documentStatus} onChange={setDocumentStatus} />
      </div>

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
