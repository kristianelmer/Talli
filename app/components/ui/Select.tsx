import type { SelectHTMLAttributes } from "react";

import { cx } from "./cx";
import { AlertTriangle, ChevronDown } from "./Icons";

export type SelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

type SelectProps = Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  "name" | "id"
> & {
  label: string;
  name: string;
  options: SelectOption[];
  helper?: string;
  error?: string;
  required?: boolean;
  placeholder?: string;
  id?: string;
};

/** Labelled native select (keyboard-accessible) with a custom chevron. */
export function Select({
  label,
  name,
  options,
  helper,
  error,
  required,
  placeholder,
  id,
  className,
  ...rest
}: SelectProps) {
  const fieldId = id ?? `field-${name}`;
  const helperId = `${fieldId}-helper`;
  const errorId = `${fieldId}-error`;
  const describedBy =
    cx(helper && !error && helperId, error && errorId) || undefined;

  return (
    <div className={cx("field", error && "field--error", className)}>
      <label className="fieldLabel" htmlFor={fieldId}>
        {label}
        {required ? (
          <span className="fieldRequired" aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
      <span className="selectControl">
        <select
          id={fieldId}
          name={name}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          defaultValue={placeholder ? "" : undefined}
          {...rest}
        >
          {placeholder ? (
            <option value="" disabled>
              {placeholder}
            </option>
          ) : null}
          {options.map((option) => (
            <option
              key={option.value}
              value={option.value}
              disabled={option.disabled}
            >
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown size={16} />
      </span>
      {helper && !error ? (
        <p className="fieldHelper" id={helperId}>
          {helper}
        </p>
      ) : null}
      {error ? (
        <p className="fieldError" id={errorId}>
          <AlertTriangle size={14} aria-hidden="true" />
          {error}
        </p>
      ) : null}
    </div>
  );
}
