import type { CorporateArtifactKind } from "./corporate-documents.ts";

export type CorporateDecisionState =
  | "draft"
  | "rendered"
  | "facts_approved"
  | "signed_owner_attested"
  | "finalized"
  | "superseded"
  | "rejected";

export type CorporateDecisionLifecycleRow = {
  id: string;
  decision_kind: "owner_dividend" | "annual_close";
  decision_hash: string;
  source_hash?: string;
};

export type CorporateDocumentSetLifecycleRow = {
  id: string;
  decision_id: string;
  decision_hash: string;
};

export type CorporateArtifactLifecycleRow = {
  id: string;
  set_id: string;
  artifact_kind: string;
  variant: "unsigned" | "signed_owner_attested";
};

export type CorporateEventLifecycleRow = {
  id: string;
  decision_id: string;
  set_id: string;
  event_kind: string;
  decision_hash: string;
};

export type CorporateFinalizationLifecycleRow = {
  id: string;
  decision_id: string;
  decision_hash: string;
};

export type CorporateDecisionLifecycle = {
  decision: CorporateDecisionLifecycleRow | null;
  documentSet: CorporateDocumentSetLifecycleRow | null;
  artifacts: CorporateArtifactLifecycleRow[];
  events: CorporateEventLifecycleRow[];
  finalizations: CorporateFinalizationLifecycleRow[];
};

export type CorporateDocumentReadinessInput = CorporateDecisionLifecycle & {
  currentDecisionHash: string;
  currentSourceHash?: string;
};

export type CorporateDocumentBlockerCode =
  | "corporate_documents_decision_missing"
  | "corporate_documents_current_hash_mismatch"
  | "corporate_documents_missing_required_artifacts"
  | "corporate_documents_facts_approval_required"
  | "corporate_documents_missing_signed_artifacts"
  | "corporate_documents_finalization_required"
  | "corporate_documents_terminal_decision";

export type CorporateDocumentReadiness = {
  state: CorporateDecisionState;
  currentHashMatches: boolean;
  readyForSigning: boolean;
  finalized: boolean;
  annualSubmissionReady: boolean;
  blockers: Array<{ code: CorporateDocumentBlockerCode; message: string }>;
};

function requiredKinds(decisionKind: CorporateDecisionLifecycleRow["decision_kind"]): CorporateArtifactKind[] {
  return decisionKind === "owner_dividend"
    ? ["dividend_board_proposal", "dividend_general_meeting_minutes"]
    : ["annual_board_minutes", "annual_general_meeting_minutes"];
}

function currentEvents(input: CorporateDecisionLifecycle) {
  if (!input.decision || !input.documentSet) return [];
  return input.events.filter((event) => event.decision_id === input.decision!.id
    && event.set_id === input.documentSet!.id
    && event.decision_hash === input.decision!.decision_hash);
}

function hasExactArtifacts(
  input: CorporateDecisionLifecycle,
  variant: CorporateArtifactLifecycleRow["variant"],
) {
  if (!input.decision || !input.documentSet) return false;
  const expected = requiredKinds(input.decision.decision_kind).sort();
  const actual = input.artifacts
    .filter((artifact) => artifact.set_id === input.documentSet!.id && artifact.variant === variant)
    .map(({ artifact_kind }) => artifact_kind)
    .sort();
  return actual.length === expected.length && actual.every((kind, index) => kind === expected[index]);
}

function hasFinalization(input: CorporateDecisionLifecycle) {
  if (!input.decision) return false;
  return input.finalizations.some((finalization) => finalization.decision_id === input.decision!.id
    && finalization.decision_hash === input.decision!.decision_hash);
}

export function deriveCorporateDecisionState(input: CorporateDecisionLifecycle): CorporateDecisionState {
  if (!input.decision
    || !input.documentSet
    || input.documentSet.decision_id !== input.decision.id
    || input.documentSet.decision_hash !== input.decision.decision_hash) {
    return "draft";
  }
  const events = currentEvents(input);
  if (events.some(({ event_kind }) => event_kind === "rejected")) return "rejected";
  if (events.some(({ event_kind }) => event_kind === "superseded")) return "superseded";
  if (!hasExactArtifacts(input, "unsigned")) return "draft";
  if (!events.some(({ event_kind }) => event_kind === "facts_approved")) return "rendered";
  if (!hasExactArtifacts(input, "signed_owner_attested")) return "facts_approved";
  if (!hasFinalization(input)) return "signed_owner_attested";
  return "finalized";
}

function blocker(code: CorporateDocumentBlockerCode, message: string) {
  return { code, message };
}

export function evaluateCorporateDocumentReadiness(
  input: CorporateDocumentReadinessInput,
): CorporateDocumentReadiness {
  const state = deriveCorporateDecisionState(input);
  const blockers: CorporateDocumentReadiness["blockers"] = [];
  if (!input.decision) {
    blockers.push(blocker(
      "corporate_documents_decision_missing",
      "Årsbeslutning med dokumentsett må opprettes.",
    ));
  }
  const currentHashMatches = Boolean(input.decision)
    && input.decision!.decision_hash === input.currentDecisionHash
    && (input.currentSourceHash === undefined
      || input.decision!.source_hash === input.currentSourceHash);
  if (input.decision && !currentHashMatches) {
    blockers.push(blocker(
      "corporate_documents_current_hash_mismatch",
      "Beslutningsdokumentene er basert på et eldre årsgrunnlag.",
    ));
  }
  if (state === "rejected" || state === "superseded") {
    blockers.push(blocker(
      "corporate_documents_terminal_decision",
      "Beslutningen er avvist eller erstattet og kan ikke brukes.",
    ));
  }
  if (input.decision && !hasExactArtifacts(input, "unsigned")) {
    blockers.push(blocker(
      "corporate_documents_missing_required_artifacts",
      "Alle genererte beslutningsdokumenter må finnes.",
    ));
  }
  if (input.decision && !currentEvents(input).some(({ event_kind }) => event_kind === "facts_approved")) {
    blockers.push(blocker(
      "corporate_documents_facts_approval_required",
      "Fakta og dokumenthash må godkjennes av eier.",
    ));
  }
  if (input.decision && !hasExactArtifacts(input, "signed_owner_attested")) {
    blockers.push(blocker(
      "corporate_documents_missing_signed_artifacts",
      "Alle signerte dokumenter må lastes opp og eierbekreftes.",
    ));
  }
  if (input.decision && !hasFinalization(input)) {
    blockers.push(blocker(
      "corporate_documents_finalization_required",
      "Beslutningen må sluttføres etter signering.",
    ));
  }
  const terminal = state === "rejected" || state === "superseded";
  const readyForSigning = currentHashMatches
    && !terminal
    && hasExactArtifacts(input, "unsigned")
    && currentEvents(input).some(({ event_kind }) => event_kind === "facts_approved");
  const finalized = state === "finalized" && currentHashMatches;
  return {
    state,
    currentHashMatches,
    readyForSigning,
    finalized,
    annualSubmissionReady: Boolean(input.decision?.decision_kind === "annual_close" && finalized),
    blockers,
  };
}
