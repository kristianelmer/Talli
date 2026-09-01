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
    state.documentId
      && state.reference.trim()
      && state.mode === "manual_fallback"
      && state.ownerAttested,
  );
}

export function InvestmentEvidenceFields({
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
      <input
        type="hidden"
        name={fieldName(fieldPrefix, "evidenceMode")}
        value="manual_fallback"
      />
      <SelectField
        label={`Dokument${prefixLabel}`}
        name={fieldName(fieldPrefix, "documentId")}
        value={state.documentId}
        onChange={(documentId) => set({
          documentId,
          mode: "manual_fallback",
        })}
        required
      >
        <option value="" disabled>Velg dokument</option>
        {documents.map((item) => (
          <option key={item.id} value={item.id}>{item.label}</option>
        ))}
      </SelectField>
      <TextField
        label={`Bilags- eller meglerreferanse${prefixLabel}`}
        name={fieldName(fieldPrefix, "evidenceReference")}
        value={state.reference}
        onChange={(reference) => set({ reference })}
        helper="Referansen og eierbekreftelsen identifiserer de registrerte faktaene. Talli verifiserer ikke dokumentfilens innhold kryptografisk. Kontantoppgjøret avstemmes separat mot banken."
        required
      />
      <CheckboxField
        label={`Jeg bekrefter at de manuelt registrerte faktaene${prefixLabel} samsvarer med valgt dokument.`}
        name={fieldName(fieldPrefix, "ownerAttested")}
        checked={state.ownerAttested}
        onChange={(ownerAttested) => set({
          ownerAttested,
          mode: "manual_fallback",
        })}
        required
      />
    </>
  );
}
