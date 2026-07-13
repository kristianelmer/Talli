import type { AuthorityTestRun } from "./authority-test-evidence.ts";
import { authorityTestEvidenceGate } from "./authority-test-evidence.ts";
import type { AuthorityObligation, AuthorityPermission } from "./authority-permission.ts";
import { authorityObligationLabel, authorityObligations, productionAuthorityGate } from "./authority-permission.ts";
import type { BillingAccount } from "./billing.ts";
import { productionBillingGate } from "./billing.ts";
import type { LaunchSignoff, LaunchSignoffKey } from "./launch-signoff.ts";
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

function launchSignoffApproved(signoffs: LaunchSignoff[], key: LaunchSignoffKey) {
  const signoff = signoffs.find((item) => item.key === key);
  return Boolean(
    signoff &&
      signoff.status === "approved" &&
      signoff.reviewer.trim() &&
      signoff.evidenceLink.trim() &&
      signoff.decision.trim() &&
      Number.isFinite(Date.parse(signoff.reviewedAt)),
  );
}

export function buildFilingReleaseGates(input: {
  authorityPermissions: Pick<AuthorityPermission, "obligation" | "confirmed_at" | "production_enabled">[];
  authorityTestRuns: Pick<AuthorityTestRun, "obligation" | "status" | "receipt_reference" | "archive_reference" | "recorded_at">[];
  billingAccount: BillingAccount | null;
  filingReadyByObligation: Partial<Record<AuthorityObligation, boolean>>;
  stepUpContext: StepUpContext;
  launchSignoffs: LaunchSignoff[];
  adapterCapabilities?: AuthorityAdapterCapabilities;
  now?: Date;
}): FilingReleaseGate[] {
  const adapterCapabilities = input.adapterCapabilities ?? currentAuthorityAdapterCapabilities();
  return authorityObligations.map((obligation) => {
    const disabledReasons: string[] = [];
    const authorityGate = productionAuthorityGate(input.authorityPermissions, obligation);
    if (!authorityGate.allowed) {
      disabledReasons.push(authorityGate.status);
    }

    if (!input.billingAccount) {
      disabledReasons.push("billing_account_missing");
    } else {
      const billingGate = productionBillingGate(input.billingAccount, Boolean(input.filingReadyByObligation[obligation]));
      if (!billingGate.allowed) {
        disabledReasons.push(billingGate.status);
      }
    }

    const evidenceGate = authorityTestEvidenceGate(input.authorityTestRuns, obligation);
    if (!evidenceGate.ready) {
      disabledReasons.push(evidenceGate.status);
    }

    try {
      assertStepUpAllowed("production_filing", input.stepUpContext, input.now);
    } catch (error) {
      disabledReasons.push(error instanceof SensitiveActionStepUpError ? error.code : "production_step_up_failed");
    }

    const signoffKey = authoritySignoffKeyByObligation[obligation];
    if (!launchSignoffApproved(input.launchSignoffs, signoffKey)) {
      disabledReasons.push(`${signoffKey}_signoff_missing`);
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
