import type { AnnualSupportRefundRecoveryWire, AnnualSupportRefundRecoveryTargetPageWire } from "../../features/billing";
import type { OperatorReadRecovery } from "./operator-support";

export type AnnualSupportRefundTargetsView = {
  purchaseId: string;
  selectedRefundRequestId?: string;
  beforeRefundRequestId?: string;
  page: AnnualSupportRefundRecoveryTargetPageWire | null;
};

export type AnnualSupportRefundIdentity = {
  initiatingUserId: string;
  supportCaseId: string;
  companyId: string;
  purchaseId: string;
  refundRequestId: string;
};

/** Feedback concerns one recorded operation; canonical history owns balances. */
export type AnnualSupportRefundRecoveryActionState =
  | { kind: "idle" }
  | { kind: "invalid" }
  | ({ kind: "different-user" } & AnnualSupportRefundIdentity)
  | ({ kind: "observed"; status: AnnualSupportRefundRecoveryWire["status"] } & AnnualSupportRefundIdentity)
  | ({ kind: "recovery"; reason: OperatorReadRecovery; href: string } & AnnualSupportRefundIdentity);

export type AnnualSupportRefundRecoveryAction = (
  previous: AnnualSupportRefundRecoveryActionState, formData: FormData,
) => Promise<AnnualSupportRefundRecoveryActionState>;
