"use client";

import Link from "next/link";
import { useActionState, useEffect, useRef } from "react";

import { FormField, SubmitButton } from "../../components/ui";
import { authRecoveryMessage, type AuthRecoveryFormState } from "../../lib/auth-recovery-presentation";
import { updateRecoveredPassword } from "../recovery-actions";

export function ResetPasswordForm({ userId, next }: { userId: string; next: string }) {
  const [state, action, pending] = useActionState<AuthRecoveryFormState, FormData>(updateRecoveredPassword, { status: "idle" });
  const formRef = useRef<HTMLFormElement>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (state.status === "error") errorRef.current?.focus();
  }, [state]);
  return (
    <form ref={formRef} className="authForm" action={action} aria-busy={pending}>
      <input name="userId" type="hidden" value={userId} />
      {state.status === "error" ? (
        <p ref={errorRef} role="alert" tabIndex={-1} className="errorText">{authRecoveryMessage[state.reason]}</p>
      ) : null}
      <FormField id="recoveryPassword" name="password" label="Nytt passord" type="password"
        autoComplete="new-password" required minLength={12} helper="Minst 12 tegn."
        error={state.status === "error" && state.reason === "password-short" ? authRecoveryMessage["password-short"] : undefined} />
      <FormField id="recoveryPasswordConfirmation" name="confirmation" label="Gjenta nytt passord" type="password"
        autoComplete="new-password" required minLength={12}
        validate={(value) => {
          const password = formRef.current?.elements.namedItem("password");
          return value && password instanceof HTMLInputElement && value !== password.value
            ? authRecoveryMessage["password-mismatch"] : undefined;
        }}
        error={state.status === "error" && state.reason === "password-mismatch" ? authRecoveryMessage["password-mismatch"] : undefined} />
      <SubmitButton block pendingLabel="Endrer …" disabled={pending}>Endre passord</SubmitButton>
      {state.status === "error" ? (
        <p className="authAlt">
          {state.reason === "mfa" ? <Link href={`/mfa?${new URLSearchParams({ fresh: "1", next: `/reset-password?${new URLSearchParams({ next })}` })}`}>Bekreft med autentiseringsappen</Link>
            : <Link href={`/forgot-password?${new URLSearchParams({ next })}`}>Be om en ny lenke</Link>}
        </p>
      ) : null}
    </form>
  );
}
