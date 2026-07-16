"use client";

import { createElement, startTransition, useActionState, useEffect } from "react";

import type {
  Rf1086ReconciliationActionState,
} from "../../actions";

const PENDING_STATES = new Set(["sent", "processing", "unknown"]);
const TERMINAL_STATES = new Set(["accepted", "rejected", "action_required"]);

type Rf1086ReconciliationControlProps = {
  action: (
    state: Rf1086ReconciliationActionState,
    formData: FormData,
  ) => Promise<Rf1086ReconciliationActionState>;
  submissionId: string;
  initialState: Rf1086ReconciliationActionState;
};

export function Rf1086ReconciliationControl({
  action,
  submissionId,
  initialState,
}: Rf1086ReconciliationControlProps) {
  const [state, dispatch, isPending] = useActionState(action, initialState);
  const pending = PENDING_STATES.has(state.state);
  const terminal = TERMINAL_STATES.has(state.state);

  useEffect(() => {
    if (!pending || terminal || isPending || state.requiresManualRetry) return;
    const timer = setTimeout(() => {
      const formData = new FormData();
      formData.set("submissionId", submissionId);
      startTransition(() => dispatch(formData));
    }, 5_000);
    return () => clearTimeout(timer);
  }, [dispatch, isPending, pending, state.requiresManualRetry, submissionId, terminal]);

  return createElement(
    "div",
    { className: "filingConfirmForm" },
    state.error
      ? createElement("p", { className: "filingLockNote", role: "alert" }, state.error)
      : null,
    createElement(
      "form",
      { action: dispatch },
      createElement("input", { type: "hidden", name: "submissionId", value: submissionId }),
      createElement(
        "button",
        { className: "btn btn--secondary", type: "submit", disabled: isPending },
        isPending ? "Sjekker status …" : "Sjekk status på nytt",
      ),
    ),
  );
}
