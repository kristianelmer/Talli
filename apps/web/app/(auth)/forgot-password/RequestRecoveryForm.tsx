"use client";

import { useActionState, useEffect, useRef, useState } from "react";

import { Button, FormField, SubmitButton } from "../../components/ui";
import { authRecoveryMessage, type AuthRecoveryFormState } from "../../lib/auth-recovery-presentation";
import { requestPasswordRecovery } from "../recovery-actions";

export function RequestRecoveryForm({ next, enabled }: { next: string; enabled: boolean }) {
  const [state, action, pending] = useActionState<AuthRecoveryFormState, FormData>(requestPasswordRecovery, { status: "idle" });
  const [email, setEmail] = useState("");
  const [retry, setRetry] = useState(false);
  const resultRef = useRef<HTMLHeadingElement>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (state.status === "sent") resultRef.current?.focus();
    if (state.status === "error") errorRef.current?.focus();
  }, [state]);
  useEffect(() => {
    if (retry) document.getElementById("recoveryEmail")?.focus();
  }, [retry]);

  if (state.status === "sent" && !retry) {
    return (
      <div className="authForm">
        <h2 ref={resultRef} tabIndex={-1}>Se etter e-post</h2>
        <p>Hvis adressen er knyttet til en konto, får du en lenke for å velge et nytt passord.</p>
        <Button onClick={() => setRetry(true)} variant="secondary">Send en ny lenke</Button>
      </div>
    );
  }
  return (
    <form action={action} className="authForm" aria-busy={pending} onSubmit={(event) => {
      setEmail(String(new FormData(event.currentTarget).get("email") ?? ""));
      setRetry(false);
    }}>
      <input type="hidden" name="next" value={next} />
      {state.status === "error" ? (
        <p className="errorText" ref={errorRef} role="alert" tabIndex={-1}>
          {authRecoveryMessage[state.reason]}
        </p>
      ) : null}
      <FormField id="recoveryEmail" name="email" label="E-post" type="email" autoComplete="email"
        required maxLength={320} defaultValue={email} disabled={!enabled}
        error={state.status === "error" && state.reason === "email" ? authRecoveryMessage.email : undefined} />
      <SubmitButton block pendingLabel="Sender …" disabled={pending || !enabled}>Send lenke</SubmitButton>
    </form>
  );
}
