"use client";

import {
  useId,
  useState,
  type ChangeEvent,
  type FocusEvent,
  type InputHTMLAttributes,
} from "react";

import { cx } from "./cx";
import { AlertTriangle } from "./Icons";

type FieldOwnProps = {
  label: string;
  name: string;
  helper?: string;
  /** Server-provided error; always takes precedence over client validation. */
  error?: string;
  required?: boolean;
  /** Show a "(valgfritt)" hint when the field is not required. */
  optionalHint?: boolean;
  multiline?: boolean;
  rows?: number;
  /** Returns an error message for the value, or undefined when valid. */
  validate?: (value: string) => string | undefined;
};

type FormFieldProps = FieldOwnProps &
  Omit<InputHTMLAttributes<HTMLInputElement>, keyof FieldOwnProps>;

/**
 * Labelled input/textarea with helper text and inline validation.
 * Validates on blur, then re-validates on change once touched. Errors are
 * announced via `aria-invalid` + `aria-describedby` and shown with an icon
 * (never colour alone).
 */
export function FormField({
  label,
  name,
  helper,
  error,
  required,
  optionalHint,
  multiline,
  rows = 4,
  validate,
  className,
  id: idProp,
  onBlur,
  onChange,
  ...rest
}: FormFieldProps) {
  const reactId = useId();
  const id = idProp ?? reactId;
  const [localError, setLocalError] = useState<string | undefined>(undefined);
  const [touched, setTouched] = useState(false);

  const shownError = error ?? (touched ? localError : undefined);
  const helperId = `${id}-helper`;
  const errorId = `${id}-error`;
  const describedBy =
    cx(helper && !shownError && helperId, shownError && errorId) || undefined;

  function check(value: string) {
    if (validate) setLocalError(validate(value));
  }

  const shared = {
    id,
    name,
    required,
    "aria-invalid": shownError ? true : undefined,
    "aria-describedby": describedBy,
  } as const;

  return (
    <div className={cx("field", shownError && "field--error", className)}>
      <label className="fieldLabel" htmlFor={id}>
        {label}
        {required ? (
          <span className="fieldRequired" aria-hidden="true">
            *
          </span>
        ) : optionalHint ? (
          <span className="fieldOptional">(valgfritt)</span>
        ) : null}
      </label>

      {multiline ? (
        <textarea
          {...shared}
          rows={rows}
          defaultValue={rest.defaultValue as string | undefined}
          placeholder={rest.placeholder}
          disabled={rest.disabled}
          readOnly={rest.readOnly}
          maxLength={rest.maxLength}
          onBlur={(e: FocusEvent<HTMLTextAreaElement>) => {
            setTouched(true);
            check(e.target.value);
          }}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => {
            if (touched) check(e.target.value);
          }}
        />
      ) : (
        <input
          {...rest}
          {...shared}
          onBlur={(e: FocusEvent<HTMLInputElement>) => {
            setTouched(true);
            check(e.target.value);
            onBlur?.(e);
          }}
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            if (touched) check(e.target.value);
            onChange?.(e);
          }}
        />
      )}

      {helper && !shownError ? (
        <p className="fieldHelper" id={helperId}>
          {helper}
        </p>
      ) : null}
      {shownError ? (
        <p className="fieldError" id={errorId}>
          <AlertTriangle size={14} aria-hidden="true" />
          {shownError}
        </p>
      ) : null}
    </div>
  );
}
