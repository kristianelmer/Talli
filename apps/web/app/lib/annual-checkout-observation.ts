import type { AnnualCheckoutWire, annualBillingRecovery } from "../../features/billing";

/** Explicit status-check feedback; refreshed purchase history owns balances and access. */
export type AnnualCheckoutObservationActionState =
  | { kind: "idle" }
  | { kind: "invalid" }
  | { kind: "observed"; companyId: string; purchaseId: string; status: AnnualCheckoutWire["status"] }
  | {
    kind: "recovery";
    companyId: string;
    purchaseId: string;
    reason: ReturnType<typeof annualBillingRecovery>;
    href: string | null;
  };

export type AnnualCheckoutObservationAction = (
  previous: AnnualCheckoutObservationActionState,
  formData: FormData,
) => Promise<AnnualCheckoutObservationActionState>;
