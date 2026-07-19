"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useFormStatus } from "react-dom";

import { buttonClass, type ButtonSize, type ButtonVariant } from "./Button";
import { Spinner } from "./Spinner";

type SubmitButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  /** Optional label shown while the enclosing form is submitting. */
  pendingLabel?: ReactNode;
};

/**
 * Submit button that reflects the enclosing form's pending state
 * (spinner + disabled) via `useFormStatus`. Loading is a first-class state.
 */
export function SubmitButton({
  variant = "primary",
  size,
  block,
  className,
  children,
  pendingLabel,
  disabled,
  ...rest
}: SubmitButtonProps) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      className={buttonClass(variant, size, block, className)}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
      data-loading={pending || undefined}
      {...rest}
    >
      {pending ? <Spinner /> : null}
      {pending ? (pendingLabel ?? children) : children}
    </button>
  );
}
