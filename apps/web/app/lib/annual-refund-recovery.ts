import type { AnnualRefundRecoveryWire, AnnualRefundRecoveryTargetPageWire, annualBillingRecovery } from "../../features/billing";

export type AnnualRefundTargetsView = {
  purchaseId: string;
  beforeRefundRequestId?: string;
  selectedRefundRequestId?: string;
  page: AnnualRefundRecoveryTargetPageWire | null;
};

/** Operation feedback only; refreshed purchase history owns refund balances. */
export type AnnualRefundRecoveryActionState =
  | { kind: "idle" }
  | { kind: "invalid" }
  | { kind: "observed"; companyId: string; purchaseId: string; refundRequestId: string; status: AnnualRefundRecoveryWire["status"] }
  | { kind: "recovery"; companyId: string; purchaseId: string; refundRequestId: string;
      reason: ReturnType<typeof annualBillingRecovery>; href: string | null };

export type AnnualRefundRecoveryAction = (
  previous: AnnualRefundRecoveryActionState,
  formData: FormData,
) => Promise<AnnualRefundRecoveryActionState>;
