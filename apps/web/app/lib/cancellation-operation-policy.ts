export type PendingCancellationOperation =
  | { command: "request"; operationId: string; companyId: string; incomeYear: number; reason: string }
  | { command: "resume"; operationId: string; companyId: string; cancellationId: string; incomeYear: number; expectedUpdatedAt: string }
  | { command: "finalize"; operationId: string; companyId: string; cancellationId: string; expectedUpdatedAt: string }
  | { command: "review"; operationId: string; companyId: string; cancellationId: string; expectedUpdatedAt: string; decision: "approved" | "rejected"; evidenceReference: string };

export function isIndeterminateCancellationError(error: unknown): boolean {
  return (typeof error === "object" && error !== null && "status" in error
      && typeof error.status === "number" && error.status >= 500 && error.status <= 599)
    || error instanceof TypeError
    || (error instanceof Error && ["AbortError", "TimeoutError"].includes(error.name));
}

export function pendingCancellationOperationForError(
  error: unknown,
  operation: PendingCancellationOperation,
): PendingCancellationOperation | null {
  return isIndeterminateCancellationError(error) ? operation : null;
}
