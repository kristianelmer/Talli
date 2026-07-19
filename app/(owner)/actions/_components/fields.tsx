"use client";

import type { ReactNode } from "react";

import { ChevronDown } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";

function RequiredMark({ required }: { required?: boolean }) {
  if (!required) return null;
  return (
    <span className="fieldRequired" aria-hidden="true">
      *
    </span>
  );
}

type TextFieldProps = {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  helper?: string;
  placeholder?: string;
  inputMode?: "decimal" | "numeric" | "text";
};

export function TextField({
  label,
  name,
  value,
  onChange,
  required,
  helper,
  placeholder,
  inputMode,
}: TextFieldProps) {
  return (
    <label className="field">
      <span className="fieldLabel">
        {label}
        <RequiredMark required={required} />
      </span>
      <input
        name={name}
        value={value}
        inputMode={inputMode}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        required={required}
      />
      {helper ? <p className="fieldHelper">{helper}</p> : null}
    </label>
  );
}

type SelectFieldProps = {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  helper?: string;
  children: ReactNode;
};

export function SelectField({
  label,
  name,
  value,
  onChange,
  required,
  helper,
  children,
}: SelectFieldProps) {
  return (
    <label className="field">
      <span className="fieldLabel">
        {label}
        <RequiredMark required={required} />
      </span>
      <span className="selectControl">
        <select
          name={name}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          required={required}
        >
          {children}
        </select>
        <ChevronDown size={16} />
      </span>
      {helper ? <p className="fieldHelper">{helper}</p> : null}
    </label>
  );
}

type CheckboxFieldProps = {
  label: string;
  name: string;
  checked: boolean;
  onChange: (value: boolean) => void;
};

export function CheckboxField({
  label,
  name,
  checked,
  onChange,
}: CheckboxFieldProps) {
  return (
    <label className="checkboxField">
      <input
        type="checkbox"
        name={name}
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

export function DocStatusSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const d = ownerCopy.actions.doc;
  return (
    <SelectField
      label={d.label}
      name="documentStatus"
      value={value}
      onChange={onChange}
      required
    >
      <option value="attached">{d.attached}</option>
      <option value="missing_accepted_warning">{d.missing}</option>
      <option value="not_required">{d.notRequired}</option>
    </SelectField>
  );
}
