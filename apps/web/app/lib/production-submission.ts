export type ProductionSubmissionStatus =
  | "approved"
  | "sending"
  | "received"
  | "processing"
  | "accepted"
  | "rejected"
  | "action_required"
  | "unknown";

const TERMINAL_STATUSES = new Set<ProductionSubmissionStatus>([
  "accepted",
  "rejected",
  "action_required",
]);

const ALLOWED_TRANSITIONS: Record<ProductionSubmissionStatus, ProductionSubmissionStatus[]> = {
  approved: ["sending"],
  sending: ["received", "unknown", "rejected"],
  received: ["processing", "rejected", "action_required"],
  processing: ["accepted", "rejected", "action_required"],
  accepted: [],
  rejected: [],
  action_required: [],
  unknown: [],
};

export function transitionProductionSubmission(
  current: ProductionSubmissionStatus,
  next: ProductionSubmissionStatus,
  evidence: { finalAuthorityDecision?: boolean } = {},
) {
  if (TERMINAL_STATUSES.has(current)) {
    throw new Error(`Production submission status ${current} is terminal.`);
  }
  if (!ALLOWED_TRANSITIONS[current].includes(next)) {
    throw new Error(`Illegal production submission transition: ${current} -> ${next}.`);
  }
  if (next === "accepted" && evidence.finalAuthorityDecision !== true) {
    throw new Error("Accepted status requires an explicit final authority decision.");
  }
  return next;
}

export function classifyRf1086TransportOutcome(input: {
  forsendelseId: string | null;
  documents: string[];
  finalAuthorityDecision: "accepted" | "rejected" | null;
}): ProductionSubmissionStatus {
  if (input.finalAuthorityDecision === "accepted") return "accepted";
  if (input.finalAuthorityDecision === "rejected") return "rejected";
  if (input.forsendelseId) return input.documents.length ? "processing" : "received";
  return "unknown";
}
