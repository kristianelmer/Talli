"use client";

import { importBankCsv } from "../../actions";
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
};

/** Step 3 — optional bank CSV import. The owner can skip and finish anytime. */
export function BankImportForm({
  companyId,
  incomeYear,
  importedCount,
}: BankImportFormProps) {
  const c = ownerCopy.onboarding.bank;
  return (
    <div className="wizardForm">
      {importedCount > 0 ? (
        <Banner variant="success" title={c.importedTitle}>
          {c.importedBody(importedCount)}
        </Banner>
      ) : null}

      <form action={importBankCsv} className="wizardForm">
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
