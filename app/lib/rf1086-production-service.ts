import type { Rf1086AuthorityTransport } from "./rf1086-authority-client.ts";
import {
  assertRf1086ProductionRelease,
  Rf1086ProductionRunnerError,
  runRf1086ProductionStep,
} from "./rf1086-production-runner.ts";
import {
  loadRf1086ProductionState,
  type Rf1086ProductionStateDatabaseClient,
} from "./rf1086-production-state.ts";
import type { Rf1086SubmissionConfirmations } from "./rf1086-submission.ts";

export type Rf1086ProductionServiceDatabaseClient = Rf1086ProductionStateDatabaseClient & {
  rpc(name: string, parameters: Record<string, unknown>): any;
};

function auditFailed() {
  return new Rf1086ProductionRunnerError(
    "rf1086_production_audit_failed",
    "RF-1086 production stopped because the security audit could not be recorded.",
  );
}

function assertAccessToken(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length < 8 || value.length > 16_384 || /\s/u.test(value)) {
    throw new Rf1086ProductionRunnerError(
      "rf1086_production_access_token_invalid",
      "RF-1086 production requires a valid short-lived system-user token.",
    );
  }
}

async function recordAuthorizedAttempt(input: {
  databaseClient: Rf1086ProductionServiceDatabaseClient;
  companyId: string;
  actorId: string;
  previewId: string;
  allowConfirm: boolean;
}) {
  try {
    const result = await input.databaseClient.from("audit_events").insert({
      company_id: input.companyId,
      actor_id: input.actorId,
      category: "security",
      action: input.allowConfirm
        ? "rf1086_production_confirmation_authorized"
        : "rf1086_production_step_authorized",
      message: `RF-1086 production attempt authorized for preview ${input.previewId}.`,
    });
    if (!result || result.error !== null) throw auditFailed();
  } catch (error) {
    if (error instanceof Rf1086ProductionRunnerError) throw error;
    throw auditFailed();
  }
}

export async function runPersistedRf1086ProductionStep(input: {
  databaseClient: Rf1086ProductionServiceDatabaseClient;
  actorId: string;
  previewId: string;
  confirmations: Rf1086SubmissionConfirmations;
  accessToken: string;
  allowConfirm?: boolean;
  now?: Date;
  authorityTransport?: Rf1086AuthorityTransport;
}) {
  assertAccessToken(input.accessToken);
  const state = await loadRf1086ProductionState({
    databaseClient: input.databaseClient,
    actorId: input.actorId,
    previewId: input.previewId,
    confirmations: input.confirmations,
    ...(input.now ? { now: input.now } : {}),
  });
  assertRf1086ProductionRelease(state.preview, state.release);
  await recordAuthorizedAttempt({
    databaseClient: input.databaseClient,
    companyId: state.preview.company_id,
    actorId: input.actorId,
    previewId: state.preview.id,
    allowConfirm: input.allowConfirm === true,
  });
  return runRf1086ProductionStep({
    preview: state.preview,
    databaseClient: input.databaseClient,
    accessToken: input.accessToken,
    release: state.release,
    ...(input.allowConfirm === true ? { allowConfirm: true } : {}),
    ...(input.authorityTransport ? { authorityTransport: input.authorityTransport } : {}),
  });
}
