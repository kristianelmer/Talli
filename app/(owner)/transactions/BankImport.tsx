"use client";

import { useMemo, useState } from "react";

import { importBankCsv } from "../../actions";
import { FileDropzone, SubmitButton } from "../../components/ui";
import { ownerCopy } from "../../lib/copy";

const c = ownerCopy.transactions.import;
const PREVIEW_LIMIT = 6;

type PreviewRow = {
  date: string;
  text: string;
  amount: string;
  balance: string;
};

type Preview = {
  rows: PreviewRow[];
  headerOk: boolean;
  hasBalance: boolean;
  total: number;
};

function buildPreview(csv: string): Preview {
  const lines = csv
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) {
    return { rows: [], headerOk: true, hasBalance: false, total: 0 };
  }
  const headers = lines[0].split(",").map((header) => header.trim().toLowerCase());
  const headerOk = ["date", "text", "amount"].every((header) => headers.includes(header));
  const index = (name: string) => headers.indexOf(name);
  const hasBalance = index("balance") >= 0;
  const rows = lines.slice(1).map((line) => {
    const values = line.split(",");
    const at = (name: string) => {
      const i = index(name);
      return i >= 0 ? (values[i] ?? "").trim() : "";
    };
    return {
      date: at("date"),
      text: at("text"),
      amount: at("amount"),
      balance: at("balance"),
    };
  });
  return { rows, headerOk, hasBalance, total: rows.length };
}

type BankImportProps = {
  companyId: string;
  incomeYear: number;
  returnTo: string;
};

export function BankImport({ companyId, incomeYear, returnTo }: BankImportProps) {
  const [csv, setCsv] = useState("");
  const preview = useMemo(() => buildPreview(csv), [csv]);
  const hasContent = csv.trim().length > 0;
  const showMissingColumns = hasContent && !preview.headerOk;
  const canSubmit = hasContent && preview.headerOk && preview.total > 0;
  const shownRows = preview.rows.slice(0, PREVIEW_LIMIT);
  const remaining = preview.total - shownRows.length;

  return (
    <form className="txImport" action={importBankCsv}>
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />
      <input type="hidden" name="returnTo" value={returnTo} />

      <div className="field">
        <span className="fieldLabel">{c.title}</span>
        <FileDropzone
          name="csvText"
          label={c.dropLabel}
          hint={c.dropHint}
          chosenLabel={c.chosen}
          fileError={c.fileError}
          onText={(text) => setCsv(text)}
        />
      </div>
      <p className="fieldHelp">{c.formatHint}</p>

      <div className="txPreview">
        <span className="txPreviewTitle">{c.previewTitle}</span>
        {showMissingColumns ? (
          <p className="txPreviewWarn">{c.missingColumns}</p>
        ) : !hasContent || preview.total === 0 ? (
          <p className="fieldHelp">{c.previewEmpty}</p>
        ) : (
          <>
            <table className="txTable">
              <thead>
                <tr>
                  <th>{c.cols.date}</th>
                  <th>{c.cols.text}</th>
                  <th className="txNum">{c.cols.amount}</th>
                  {preview.hasBalance ? <th className="txNum">{c.cols.balance}</th> : null}
                </tr>
              </thead>
              <tbody>
                {shownRows.map((row, idx) => (
                  <tr key={`${row.date}-${row.text}-${idx}`}>
                    <td>{row.date}</td>
                    <td>{row.text}</td>
                    <td className="txNum">{row.amount}</td>
                    {preview.hasBalance ? <td className="txNum">{row.balance}</td> : null}
                  </tr>
                ))}
              </tbody>
            </table>
            {remaining > 0 ? <p className="fieldHelp">{c.moreRows(remaining)}</p> : null}
            <p className="txPreviewCount">{c.previewCount(preview.total)}</p>
          </>
        )}
      </div>

      <SubmitButton disabled={!canSubmit} pendingLabel={c.pending}>
        {c.cta}
      </SubmitButton>
    </form>
  );
}
