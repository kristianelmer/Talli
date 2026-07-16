import { randomBytes } from "node:crypto";

export const SYSTEM_USER_SYSTEM_ID = "930835978_talli" as const;
export const SYSTEM_USER_RIGHT = "ske-innrapportering-aksjonaerregisteroppgave" as const;
export const SYSTEM_USER_CALLBACK_URL = "https://talli.no/auth/systembruker/confirm" as const;

export type SystemUserRequestStatus =
  | "creating"
  | "new"
  | "accepted"
  | "rejected"
  | "denied"
  | "timedout"
  | "verification_failed";

const allowedTransitions: Record<SystemUserRequestStatus, ReadonlySet<SystemUserRequestStatus>> = {
  creating: new Set([
    "creating",
    "new",
    "accepted",
    "rejected",
    "denied",
    "timedout",
    "verification_failed",
  ]),
  new: new Set(["new", "accepted", "rejected", "denied", "timedout", "verification_failed"]),
  accepted: new Set(["accepted", "verification_failed"]),
  rejected: new Set(["rejected"]),
  denied: new Set(["denied"]),
  timedout: new Set(["timedout"]),
  verification_failed: new Set(["verification_failed", "accepted"]),
};

export function generateSystemUserExternalRef() {
  return randomBytes(32).toString("base64url");
}

export function assertSystemUserTransition(
  from: SystemUserRequestStatus,
  to: SystemUserRequestStatus,
) {
  if (!allowedTransitions[from].has(to)) throw new Error("invalid_system_user_transition");
  return to;
}
