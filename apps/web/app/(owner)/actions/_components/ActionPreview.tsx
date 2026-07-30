import type { ReactNode } from "react";

import { Banner } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";

export type LedgerLine = {
  account: string;
  description: string;
  debit: number;
  credit: number;
};

const krFormatter = new Intl.NumberFormat("nb-NO", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatKr(value: number): string {
  return `${krFormatter.format(value)} kr`;
}

type ActionPreviewProps = {
  /** A blunt, plain-Norwegian reason the action cannot proceed. */
  block?: string | null;
  /** The double-entry lines that will be posted on confirm. */
  lines?: LedgerLine[] | null;
  /** Extra plain-language summary shown above the postings (e.g. gain/loss). */
  summary?: ReactNode;
};

/**
 * Shared preview for the holding-action wizards (#96): either a blunt block
 * banner (needs-accountant / unsupported), or the exact double-entry postings
 * that confirming will book. Account numbers are shown with Norwegian names so
 * the owner never sees internal English ledger memos.
 */
export function ActionPreview({ block, lines, summary }: ActionPreviewProps) {
  const a = ownerCopy.actions;

  if (block) {
    return (
      <Banner variant="danger" title={a.blockTitle}>
        {block}
      </Banner>
    );
  }

  if (!lines || lines.length === 0) {
    return <p className="fieldHelper">{a.fillToPreview}</p>;
  }

  const totalDebit = lines.reduce((sum, line) => sum + line.debit, 0);
  const totalCredit = lines.reduce((sum, line) => sum + line.credit, 0);

  return (
    <div className="postings">
      <strong className="cardLabel">{a.previewTitle}</strong>
      {summary ? <div className="fieldHelper">{summary}</div> : null}
      <p className="fieldHelper">{a.previewIntro}</p>
      <table className="postingsTable">
        <thead>
          <tr>
            <th>{a.account}</th>
            <th className="num">{a.debit}</th>
            <th className="num">{a.credit}</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line, index) => (
            <tr key={`${line.account}-${index}`}>
              <td>
                {line.account} {a.accountNames[line.account] ?? ""}
              </td>
              <td className="num">{line.debit ? formatKr(line.debit) : ""}</td>
              <td className="num">
                {line.credit ? formatKr(line.credit) : ""}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td>Sum</td>
            <td className="num">{formatKr(totalDebit)}</td>
            <td className="num">{formatKr(totalCredit)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
