import type { AnnualAgreementCleanupWire, annualBillingRecovery } from "../../features/billing";

/** Presentation state from an explicit action, never persisted provider authority. */
export type AnnualAgreementCleanupActionState =
  | { kind: "idle" }
  | { kind: "invalid" }
  | { kind: "result"; value: AnnualAgreementCleanupWire }
  | {
    kind: "recovery";
    companyId: string;
    purchaseId: string;
    reason: ReturnType<typeof annualBillingRecovery>;
    href: string | null;
  };

export type AnnualAgreementCleanupAction = (
  previous: AnnualAgreementCleanupActionState,
  formData: FormData,
) => Promise<AnnualAgreementCleanupActionState>;
