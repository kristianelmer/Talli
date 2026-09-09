import type { SystemUserResultWire } from "@talli/talli-api-client";

export const SYSTEM_USER_COOKIE = {
  name: "talli_system_user_request",
  options: {
    httpOnly: true, secure: true, sameSite: "lax",
    path: "/auth/systembruker/confirm", maxAge: 3600,
  },
} as const;

export function callbackStateForResult(result: Pick<SystemUserResultWire, "status" | "preflightVerifiedAt">) {
  if (result.status === "accepted") return result.preflightVerifiedAt ? "connected" : "verifying";
  if (result.status === "new" || result.status === "creating") return "pending";
  if (result.status === "rejected" || result.status === "denied" || result.status === "timedout") return result.status;
  return "manual";
}
