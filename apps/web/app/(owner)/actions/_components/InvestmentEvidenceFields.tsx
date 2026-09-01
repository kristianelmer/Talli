"use client";

import { CheckboxField, SelectField, TextField } from "./fields";

export type InvestmentEvidenceOption = {
  id: string;
  label: string;
};

export type InvestmentEvidenceState = {
  mode: "linked_sources" | "manual_fallback";
  bankTransactionId: string;
  documentId: string;
  reference: string;
  ownerAttested: boolean;
};

type Props = {
  bankTransactions: InvestmentEvidenceOption[];
  documents: InvestmentEvidenceOption[];
  state: InvestmentEvidenceState;
  onChange: (state: InvestmentEvidenceState) => void;
  fieldPrefix?: "" | "replacement";
};

function fieldName(prefix: Props["fieldPrefix"], name: string) {
  if (!prefix) return name;
  return `${prefix}${name[0]?.toUpperCase() ?? ""}${name.slice(1)}`;
}

export function investmentEvidenceComplete(state: InvestmentEvidenceState) {
  return Boolean(
    state.bankTransactionId
      && state.documentId
      && state.reference.trim()
      && (state.mode === "linked_sources" || state.ownerAttested),
  );
}

export function InvestmentEvidenceFields({
  bankTransactions,
  documents,
  state,
  onChange,
  fieldPrefix = "",
}: Props) {
  const set = (change: Partial<InvestmentEvidenceState>) => onChange({
    ...state,
    ...change,
  });
  const prefixLabel = fieldPrefix ? " for de nye faktaene" : "";

  return (
    <>
      <SelectField
        label={`Kildekanal${prefixLabel}`}
        name={fieldName(fieldPrefix, "evidenceMode")}
        value={state.mode}
        onChange={(mode) => set({
          mode: mode as InvestmentEvidenceState["mode"],
          ownerAttested: false,
        })}
        required
      >
        <option value="linked_sources">Koblede kilder</option>
        <option value="manual_fallback">Manuelt registrerte fakta med komplette kilder</option>
      </SelectField>
      <div className="fieldRow">
        <SelectField
          label={`Bankbevegelse${prefixLabel}`}
          name={fieldName(fieldPrefix, "bankTransactionId")}
          value={state.bankTransactionId}
          onChange={(bankTransactionId) => set({ bankTransactionId })}
          required
        >
          <option value="" disabled>Velg bankbevegelse</option>
          {bankTransactions.map((item) => (
            <option key={item.id} value={item.id}>{item.label}</option>
          ))}
        </SelectField>
        <SelectField
          label={`Dokument${prefixLabel}`}
          name={fieldName(fieldPrefix, "documentId")}
          value={state.documentId}
          onChange={(documentId) => set({ documentId })}
          required
        >
          <option value="" disabled>Velg dokument</option>
          {documents.map((item) => (
            <option key={item.id} value={item.id}>{item.label}</option>
          ))}
        </SelectField>
      </div>
      <TextField
        label={`Bilags- eller leverandørreferanse${prefixLabel}`}
        name={fieldName(fieldPrefix, "evidenceReference")}
        value={state.reference}
        onChange={(reference) => set({ reference })}
        helper="Referansen identifiserer de samme faktaene som bankbevegelsen og dokumentet."
        required
      />
      {state.mode === "manual_fallback" ? (
        <CheckboxField
          label={`Jeg bekrefter at de manuelt registrerte faktaene${prefixLabel} samsvarer med valgte kilder.`}
          name={fieldName(fieldPrefix, "ownerAttested")}
          checked={state.ownerAttested}
          onChange={(ownerAttested) => set({ ownerAttested })}
          required
        />
      ) : (
        <input
          type="hidden"
          name={fieldName(fieldPrefix, "ownerAttested")}
          value="false"
        />
      )}
    </>
  );
}
