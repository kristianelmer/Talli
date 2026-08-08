import { cookies } from "next/headers";
import type { PendingCancellationOperation } from "./cancellation-operation-policy";

export type { PendingCancellationOperation } from "./cancellation-operation-policy";

const COOKIE = "talli_pending_cancellation_operation";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;

function valid(value: unknown): value is PendingCancellationOperation {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  if (!UUID.test(String(item.operationId)) || !UUID.test(String(item.companyId))) return false;
  if (item.command === "request") {
    return Number.isInteger(item.incomeYear) && Number(item.incomeYear) >= 2000 && Number(item.incomeYear) <= 2100
      && typeof item.reason === "string" && item.reason.length >= 1 && item.reason.length <= 1000;
  }
  if (!UUID.test(String(item.cancellationId)) || typeof item.expectedUpdatedAt !== "string") return false;
  if (item.command === "finalize") return true;
  return item.command === "review"
    && (item.decision === "approved" || item.decision === "rejected")
    && typeof item.evidenceReference === "string"
    && item.evidenceReference.length >= 1 && item.evidenceReference.length <= 500;
}

export async function preservePendingCancellationOperation(operation: PendingCancellationOperation) {
  (await cookies()).set(COOKIE, Buffer.from(JSON.stringify(operation)).toString("base64url"), {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 600,
  });
}

export async function clearPendingCancellationOperation() {
  (await cookies()).delete(COOKIE);
}

export async function loadPendingCancellationOperation(): Promise<PendingCancellationOperation | null> {
  const encoded = (await cookies()).get(COOKIE)?.value;
  if (!encoded) return null;
  try {
    const candidate: unknown = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8"));
    return valid(candidate) ? candidate : null;
  } catch {
    return null;
  }
}
