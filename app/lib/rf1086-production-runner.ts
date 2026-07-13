import type { AuthorityTestRun } from "./authority-test-evidence.ts";
import type { AuthorityPermission } from "./authority-permission.ts";
import type { BillingAccount } from "./billing.ts";
import { buildFilingReleaseGates } from "./filing-release-gate.ts";
import type { LaunchSignoff } from "./launch-signoff.ts";
import { createRf1086AuthorityClient, type Rf1086AuthorityTransport } from "./rf1086-authority-client.ts";
import {
  inspectRf1086AuthorityProgress,
  runNextRf1086AuthorityStep,
} from "./rf1086-authority-orchestration.ts";
import {
  createRf1086SupabaseJournal,
  type Rf1086SupabaseJournalClient,
} from "./rf1086-supabase-journal.ts";
import type { Rf1086SubmissionConfirmations } from "./rf1086-submission.ts";
import type { CompanyMembershipRow, FilingPreviewRow } from "./supabase/server.ts";
import type { StepUpContext } from "./security.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export type Rf1086ProductionReleaseContext = {
  actorId: string;
  membership: CompanyMembershipRow | null;
  authorityPermissions: AuthorityPermission[];
  authorityTestRuns: Pick<
    AuthorityTestRun,
    "company_id" | "obligation" | "status" | "receipt_reference" | "archive_reference" | "recorded_at"
  >[];
  billingAccount: BillingAccount | null;
  filingReady: boolean;
  stepUpContext: StepUpContext;
  launchSignoffs: LaunchSignoff[];
  hardReviewBlockCount: number;
  blockingOverrideCount: number;
  confirmations: Rf1086SubmissionConfirmations;
  now?: Date;
};

export class Rf1086ProductionRunnerError extends Error {
  readonly code: string;
  readonly disabledReasons: string[];

  constructor(code: string, message: string, disabledReasons: string[] = []) {
    super(message);
    this.name = "Rf1086ProductionRunnerError";
    this.code = code;
    this.disabledReasons = [...disabledReasons];
  }
}

function runnerError(code: string, message: string, disabledReasons: string[] = []) {
  return new Rf1086ProductionRunnerError(code, message, disabledReasons);
}

function countIsValid(value: number) {
  return Number.isSafeInteger(value) && value >= 0;
}

function extractElementValues(xml: string, elementName: string) {
  const escaped = elementName.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
  const starts = [...xml.matchAll(new RegExp(`<${escaped}\\b`, "gu"))].length;
  const values = [...xml.matchAll(new RegExp(`<${escaped}\\b[^>]*>\\s*([^<]+?)\\s*</${escaped}>`, "gu"))]
    .map((match) => match[1].trim());
  return { starts, values };
}

export function assertRf1086ProductionPreviewScope(preview: FilingPreviewRow) {
  if (
    preview.source !== "python_rf1086_engine" ||
    preview.filing !== "aksjonærregisteroppgaven" ||
    preview.status !== "ready" ||
    !preview.hovedskjema_xml ||
    !Object.keys(preview.underskjema_xml).length
  ) {
    throw runnerError(
      "rf1086_production_preview_invalid",
      "RF-1086 production requires an immutable ready engine preview.",
    );
  }

  for (const xml of [preview.hovedskjema_xml, ...Object.values(preview.underskjema_xml)]) {
    const acquisitions = extractElementValues(xml, "AksjeErvervType-datadef-17745");
    const sales = extractElementValues(xml, "AksjerArvMvOmsattType-datadef-17753");
    const dividends = extractElementValues(xml, "AksjeUtbytteHendelsestype-datadef-36564");
    if (
      acquisitions.starts !== acquisitions.values.length ||
      acquisitions.values.some((value) => value !== "N") ||
      sales.starts > 0 ||
      dividends.starts > 0
    ) {
      throw runnerError(
        "rf1086_production_scope_unsupported",
        "RF-1086 production is limited to formation/no-activity cases without purchase, sale, or dividend events.",
      );
    }
  }
}

export function assertRf1086ProductionRelease(
  preview: FilingPreviewRow,
  release: Rf1086ProductionReleaseContext,
) {
  if (
    !UUID_PATTERN.test(release.actorId) ||
    !UUID_PATTERN.test(preview.id) ||
    !UUID_PATTERN.test(preview.company_id) ||
    release.stepUpContext.actorId !== release.actorId ||
    !countIsValid(release.hardReviewBlockCount) ||
    !countIsValid(release.blockingOverrideCount) ||
    (release.now && Number.isNaN(release.now.getTime()))
  ) {
    throw runnerError("rf1086_production_release_invalid", "RF-1086 production release state is invalid.");
  }
  assertRf1086ProductionPreviewScope(preview);

  if (
    !release.membership ||
    release.membership.company_id !== preview.company_id ||
    release.membership.user_id !== release.actorId ||
    release.membership.role !== "owner" ||
    !release.membership.accepted_at
  ) {
    throw runnerError("rf1086_production_owner_required", "RF-1086 production requires an accepted company owner.");
  }

  const permission = release.authorityPermissions.find(
    (item) => item.company_id === preview.company_id && item.obligation === "aksjonaerregisteroppgaven",
  );
  if (
    permission &&
    (permission.submitter_user_id !== release.actorId || permission.confirmed_by !== release.actorId)
  ) {
    throw runnerError(
      "rf1086_production_authority_actor_mismatch",
      "RF-1086 authority confirmation does not belong to the authenticated owner.",
    );
  }
  if (!release.confirmations.authorityConfirmed || !release.confirmations.previewConfirmed) {
    throw runnerError(
      "rf1086_production_confirmation_missing",
      "RF-1086 production requires authority and final-preview confirmation.",
    );
  }

  const gate = buildFilingReleaseGates({
    authorityPermissions: release.authorityPermissions.filter((item) => item.company_id === preview.company_id),
    authorityTestRuns: release.authorityTestRuns.filter((item) => item.company_id === preview.company_id),
    billingAccount: release.billingAccount?.company_id === preview.company_id ? release.billingAccount : null,
    filingReadyByObligation: { aksjonaerregisteroppgaven: release.filingReady },
    stepUpContext: release.stepUpContext,
    launchSignoffs: release.launchSignoffs,
    productionAdapters: { aksjonaerregisteroppgaven: true },
    ...(release.now ? { now: release.now } : {}),
  }).find((item) => item.obligation === "aksjonaerregisteroppgaven");

  const disabledReasons = [...(gate?.disabledReasons ?? ["production_gate_unavailable"])];
  if (release.hardReviewBlockCount) disabledReasons.push("hard_review_block");
  if (release.blockingOverrideCount) disabledReasons.push("blocking_filing_override");
  if (!gate || gate.status !== "production_ready" || disabledReasons.length) {
    throw runnerError(
      "rf1086_production_gate_disabled",
      "RF-1086 production release gates are not complete.",
      [...new Set(disabledReasons)],
    );
  }
}

export async function runRf1086ProductionStep(input: {
  preview: FilingPreviewRow;
  databaseClient: Rf1086SupabaseJournalClient;
  accessToken: string;
  release: Rf1086ProductionReleaseContext;
  allowConfirm?: boolean;
  authorityTransport?: Rf1086AuthorityTransport;
}) {
  assertRf1086ProductionRelease(input.preview, input.release);
  const journal = createRf1086SupabaseJournal({ preview: input.preview, client: input.databaseClient });
  const progress = await inspectRf1086AuthorityProgress({
    preview: input.preview,
    environment: "production",
    journal,
  });
  if (progress.blocked) {
    throw runnerError(
      "rf1086_production_checkpoint_blocked",
      "RF-1086 production checkpoint requires operator reconciliation.",
    );
  }
  if (progress.complete && progress.checkpoint) {
    return { checkpoint: progress.checkpoint, complete: true };
  }
  if (progress.nextOperation === "bekreft" && input.allowConfirm !== true) {
    throw runnerError(
      "rf1086_production_confirmation_required",
      "RF-1086 production confirmation requires a separate explicit flag.",
    );
  }

  const client = createRf1086AuthorityClient({
    environment: "production",
    accessToken: input.accessToken,
    ...(input.authorityTransport ? { transport: input.authorityTransport } : {}),
  });
  return runNextRf1086AuthorityStep({ preview: input.preview, client, journal });
}
