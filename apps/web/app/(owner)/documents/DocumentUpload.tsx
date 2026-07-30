"use client";

import { useState } from "react";

import { uploadDocument } from "../../actions";
import { SubmitButton } from "../../components/ui";
import { ownerCopy } from "../../lib/copy";

const c = ownerCopy.documents.upload;
const TYPE_KEYS = ["bank_statement", "accounting_document", "corporate_document"] as const;
const LINKED_KEYS = [
  "workspace",
  "aksjonaerregisteroppgaven",
  "skattemelding",
  "aarsregnskap",
] as const;

type DocumentUploadProps = {
  companyId: string;
  incomeYear: number;
  returnTo: string;
};

export function DocumentUpload({ companyId, incomeYear, returnTo }: DocumentUploadProps) {
  const [hasFile, setHasFile] = useState(false);

  return (
    <form className="docUpload" action={uploadDocument}>
      <input type="hidden" name="returnTo" value={returnTo} />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />

      <p className="cardNote">{c.intro}</p>

      <div className="docUploadGrid">
        <label className="field">
          <span className="fieldLabel">{c.typeLabel}</span>
          <select name="documentType" defaultValue="bank_statement">
            {TYPE_KEYS.map((key) => (
              <option key={key} value={key}>
                {c.types[key]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="fieldLabel">{c.linkedToLabel}</span>
          <select name="linkedTo" defaultValue="workspace">
            {LINKED_KEYS.map((key) => (
              <option key={key} value={key}>
                {c.linkedOptions[key]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="field">
        <span className="fieldLabel">{c.fileLabel}</span>
        <input
          name="file"
          type="file"
          accept=".pdf,application/pdf"
          required
          onChange={(event) => setHasFile((event.target.files?.length ?? 0) > 0)}
        />
      </label>
      <p className="fieldHelp">{c.fileHint}</p>

      <SubmitButton disabled={!hasFile} pendingLabel={c.pending}>
        {c.cta}
      </SubmitButton>
    </form>
  );
}
