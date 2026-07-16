"use client";

import { createElement, startTransition, useActionState, useEffect } from "react";

import { ownerCopy } from "../../lib/copy";
import type {
  Rf1086OwnerReconciliationActionState,
} from "../../lib/rf1086-production-presentation";

type Rf1086ReconciliationControlProps = {
  action: (
    state: Rf1086OwnerReconciliationActionState,
    formData: FormData,
  ) => Promise<Rf1086OwnerReconciliationActionState>;
  submissionId: string;
  initialState: Rf1086OwnerReconciliationActionState;
};

export function Rf1086ReconciliationControl({
  action,
  submissionId,
  initialState,
}: Rf1086ReconciliationControlProps) {
  const [state, dispatch, isPending] = useActionState(action, initialState);
  const copy = ownerCopy.filing.production;

  useEffect(() => {
    if (!state.shouldPoll || isPending || state.requiresManualRetry) return;
    const timer = setTimeout(() => {
      const formData = new FormData();
      formData.set("submissionId", submissionId);
      startTransition(() => dispatch(formData));
    }, 5_000);
    return () => clearTimeout(timer);
  }, [dispatch, isPending, state.requiresManualRetry, state.shouldPoll, submissionId]);

  return createElement(
    "div",
    { className: "filingConfirmForm" },
    state.errorCode
      ? createElement("p", { className: "filingLockNote", role: "alert" }, copy.errors[state.errorCode])
      : null,
    createElement(
      "form",
      { action: dispatch },
      createElement("input", { type: "hidden", name: "submissionId", value: submissionId }),
      createElement(
        "button",
        { className: "btn btn--secondary", type: "submit", disabled: isPending },
        isPending ? copy.reconciliation.checkPending : copy.reconciliation.checkCta,
      ),
    ),
  );
}
