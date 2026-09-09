import type { AnnualSupportCleanupRecoveryWire } from "../../features/billing";
import type { OperatorReadRecovery } from "./operator-support";

export type AnnualSupportCleanupIdentity = {
  initiatingUserId: string;
  supportCaseId: string;
  companyId: string;
  purchaseId: string;
};

export type AnnualSupportCleanupRecoveryActionState =
  | { kind: "idle" }
  | { kind: "invalid" }
  | ({ kind: "different-user" } & AnnualSupportCleanupIdentity)
  | ({ kind: "observed"; status: AnnualSupportCleanupRecoveryWire["status"] } & AnnualSupportCleanupIdentity)
  | ({ kind: "recovery"; reason: OperatorReadRecovery; href: string } & AnnualSupportCleanupIdentity);

export type AnnualSupportCleanupRecoveryAction = (
  previous: AnnualSupportCleanupRecoveryActionState, formData: FormData,
) => Promise<AnnualSupportCleanupRecoveryActionState>;
