"use client";

import { useState } from "react";

import { acceptBankCsvPreview, importBankCsv } from "../../actions";
import {
  Banner,
  FileDropzone,
  LinkButton,
  SubmitButton,
} from "../../components/ui";
import { ownerCopy } from "../../lib/copy";

type BankImportFormProps = {
  companyId: string;
  incomeYear: number;
  importedCount: number;
  retryOperationId?: string;
  retryAccountId?: string;
  persistedPreview?: {
    sourceFileId: string;
    documentSha256: string;
    transactionCount: number;
    operationId?: string;
  };
};

/** Step 3 — optional bank CSV import. The owner can skip and finish anytime. */
export function BankImportForm({
  companyId,
  incomeYear,
  importedCount,
  retryOperationId,
  retryAccountId,
  persistedPreview,
}: BankImportFormProps) {
  const [operationId] = useState(() => retryOperationId ?? crypto.randomUUID());
  const [accountId] = useState(() => retryAccountId ?? crypto.randomUUID());
  const [acceptanceOperationId] = useState(
    () => persistedPreview?.operationId ?? crypto.randomUUID(),
  );
  const c = ownerCopy.onboarding.bank;
  return (
    <div className="wizardForm">
      {importedCount > 0 ? (
        <Banner variant="success" title={c.importedTitle}>
          {c.importedBody(importedCount)}
        </Banner>
      ) : null}

      {persistedPreview ? (
        <form action={acceptBankCsvPreview} className="wizardForm">
          <input type="hidden" name="operationId" value={acceptanceOperationId} />
          <input type="hidden" name="sourceFileId" value={persistedPreview.sourceFileId} />
          <input type="hidden" name="documentSha256" value={persistedPreview.documentSha256} />
          <input type="hidden" name="transactionCount" value={persistedPreview.transactionCount} />
          <input type="hidden" name="returnTo" value="/onboarding?step=bank" />
          <input type="hidden" name="companyId" value={companyId} />
          <input type="hidden" name="incomeYear" value={incomeYear} />
          <Banner variant="info" title={c.persistedPreviewTitle}>
            {c.persistedPreviewBody(persistedPreview.transactionCount)}
          </Banner>
          <SubmitButton variant="secondary" pendingLabel={c.acceptPending}>
            {c.acceptCta}
          </SubmitButton>
        </form>
      ) : (
      <form action={importBankCsv} className="wizardForm">
        <input type="hidden" name="operationId" value={operationId} />
        <input type="hidden" name="accountId" value={accountId} />
        <input type="hidden" name="returnTo" value="/onboarding?step=bank" />
        <input type="hidden" name="companyId" value={companyId} />
        <input type="hidden" name="incomeYear" value={incomeYear} />
        <div className="field">
          <span className="fieldLabel">{c.csvLabel}</span>
          <FileDropzone
            name="csvText"
            label={c.dropLabel}
            hint={c.dropHint}
            chosenLabel={c.chosen}
            fileError={c.fileError}
          />
          <p className="fieldHelp">{c.csvHelp}</p>
        </div>
        <SubmitButton variant="secondary" pendingLabel={c.pending}>
          {c.cta}
        </SubmitButton>
      </form>
      )}

      <footer className="wizardFooter">
        <LinkButton variant="ghost" href="/dashboard">
          {c.skip}
        </LinkButton>
        <LinkButton variant="primary" href="/dashboard">
          {c.finish}
        </LinkButton>
      </footer>
    </div>
  );
}
