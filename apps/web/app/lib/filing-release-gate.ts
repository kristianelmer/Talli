import type { AuthorityTestRun } from "./authority-test-evidence.ts";
import { authorityTestEvidenceGate } from "./authority-test-evidence.ts";
import type { AuthorityObligation, AuthorityPermission } from "./authority-permission.ts";
import { authorityObligationLabel, authorityObligations, productionAuthorityGate } from "./authority-permission.ts";
import type { BillingEntitlementDecisionWire } from "../../features/billing";
import {
  evaluateLaunchSignoff,
  type LaunchSignoff,
  type LaunchSignoffKey,
} from "./launch-signoff.ts";
import { assertStepUpAllowed, SensitiveActionStepUpError, type StepUpContext } from "./security.ts";
import {
  currentAuthorityAdapterCapabilities,
  type AuthorityAdapterCapabilities,
} from "./authority-adapters.ts";

export type FilingReleaseGateStatus = "production_ready" | "production_disabled";

export type FilingReleaseGate = {
  obligation: AuthorityObligation;
  label: string;
  status: FilingReleaseGateStatus;
  disabledReasons: string[];
  publicCopyRestriction: string;
};

const authoritySignoffKeyByObligation: Record<AuthorityObligation, LaunchSignoffKey> = {
  aksjonaerregisteroppgaven: "rf1086_authority",
  aarsregnskap: "annual_accounts_authority",
  skattemelding: "tax_return_authority",
};

const commonProductionSignoffKeys: LaunchSignoffKey[] = [
  "launch_legal_name_public_copy",
  "legal_policy_pack",
  "security_restore",
  "billing_refund",
  "support_rollback",
  "founder_production_go_live",
];

function launchSignoffDisabledReason(input: {
  signoffs: LaunchSignoff[];
  key: LaunchSignoffKey;
  now: Date;
}) {
  const status = evaluateLaunchSignoff(input);
  return status === "approved" ? null : `${input.key}_signoff_${status}`;
}

export function buildFilingReleaseGates(input: {
  authorityPermissions: Pick<AuthorityPermission, "obligation" | "confirmed_at" | "production_enabled">[];
  authorityTestRuns: Pick<AuthorityTestRun, "obligation" | "status" | "receipt_reference" | "archive_reference" | "recorded_at">[];
  billingEntitlements: Partial<Record<AuthorityObligation, BillingEntitlementDecisionWire>>;
  stepUpContext: StepUpContext;
  launchSignoffs: LaunchSignoff[];
  adapterCapabilities?: AuthorityAdapterCapabilities;
  now?: Date;
}): FilingReleaseGate[] {
  const adapterCapabilities = input.adapterCapabilities ?? currentAuthorityAdapterCapabilities();
  const now = input.now ?? new Date();
  return authorityObligations.map((obligation) => {
    const disabledReasons: string[] = [];
    const billingDecision = input.billingEntitlements[obligation];
    const billingExemptPilot = billingDecision?.billingExempt === true;

    const authorityGate = productionAuthorityGate(input.authorityPermissions, obligation);
    if (!authorityGate.allowed) {
      disabledReasons.push(authorityGate.status);
    }

    if (!billingDecision) {
      disabledReasons.push("billing_account_missing");
    } else if (!billingDecision.allowed) {
      disabledReasons.push(billingDecision.status);
    }

    const evidenceGate = authorityTestEvidenceGate(input.authorityTestRuns, obligation);
    if (!evidenceGate.ready) {
      disabledReasons.push(evidenceGate.status);
    }

    try {
      assertStepUpAllowed("production_filing", input.stepUpContext, now);
    } catch (error) {
      disabledReasons.push(error instanceof SensitiveActionStepUpError ? error.code : "production_step_up_failed");
    }

    for (const signoffKey of [
      ...commonProductionSignoffKeys,
      authoritySignoffKeyByObligation[obligation],
    ].filter((key) => !(billingExemptPilot && key === "billing_refund"))) {
      const reason = launchSignoffDisabledReason({
        signoffs: input.launchSignoffs,
        key: signoffKey,
        now,
      });
      if (reason) {
        disabledReasons.push(reason);
      }
    }

    const adapterCapability = adapterCapabilities[obligation];
    if (!adapterCapability.productionImplemented) {
      disabledReasons.push("production_adapter_unimplemented");
    } else if (!adapterCapability.productionEnabled) {
      disabledReasons.push("production_adapter_disabled");
    }

    return {
      obligation,
      label: authorityObligationLabel(obligation),
      status: disabledReasons.length ? "production_disabled" : "production_ready",
      disabledReasons,
      publicCopyRestriction: disabledReasons.length
        ? `${authorityObligationLabel(obligation)} kan bare omtales som forhåndsvisning/simulering til produksjonsbevis og reviewer-signoff finnes.`
        : `${authorityObligationLabel(obligation)} kan omtales som produksjonsklar for støttede saker med lagret kvittering.`,
    };
  });
}
