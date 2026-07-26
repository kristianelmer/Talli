import type { SupabaseClient } from "@supabase/supabase-js";

import type { SystemUserRequestRow } from "../../lib/supabase/server";
import type { SystemUserRequestStatus } from "../../lib/system-user-requests";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const PRODUCTION_CONFIRMATION_PREFIX =
  "https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=";
const REQUEST_STATUSES = new Set<SystemUserRequestStatus>([
  "creating",
  "new",
  "accepted",
  "rejected",
  "denied",
  "timedout",
  "verification_failed",
]);

type StatusCopy = { title: string; body: string };
type FilingCopy = {
  label: string;
  body: string;
  variant: "success" | "warning" | "danger";
  ready: boolean;
};

export type SystemUserConnectionCopy = {
  states: Record<SystemUserRequestStatus, StatusCopy>;
  verified: StatusCopy;
  filing: {
    missing: FilingCopy;
    waiting: FilingCopy;
    ready: FilingCopy;
    action: FilingCopy;
  };
  callbackNotices: Record<SystemUserCallbackNotice, string>;
};

export type SystemUserRequestAction =
  | "continue"
  | "refresh"
  | "retry_verification"
  | "create";

export type SystemUserRequestPresentation = {
  companyId: string;
  requestId: string;
  title: string;
  body: string;
  badgeVariant: "success" | "warning" | "danger" | "info";
  badgeIcon?: "check" | "alert";
  continueHref: string | null;
  actions: SystemUserRequestAction[];
  filing: FilingCopy;
};

type SystemUserCallbackNotice =
  | "pending"
  | "verifying"
  | "connected"
  | "rejected"
  | "denied"
  | "timedout"
  | "manual";

const CALLBACK_NOTICES = new Set<SystemUserCallbackNotice>([
  "pending",
  "verifying",
  "connected",
  "rejected",
  "denied",
  "timedout",
  "manual",
]);

function requiredLocalUuid(value: string): string {
  if (!UUID_PATTERN.test(value)) throw new Error("invalid_local_system_user_request");
  return value;
}

function validatedContinueHref(request: SystemUserRequestRow): string | null {
  if (
    request.status !== "new"
    || request.altinn_request_id === null
    || !UUID_PATTERN.test(request.altinn_request_id)
  ) {
    return null;
  }
  const canonical = `${PRODUCTION_CONFIRMATION_PREFIX}${request.altinn_request_id}`;
  return request.confirm_url === canonical ? canonical : null;
}

export function selectReadableCompany<T extends { id: string }>(
  selected: unknown,
  companies: readonly T[],
): T | null {
  const readableCompanies = companies.filter((company) => UUID_PATTERN.test(company.id));
  if (typeof selected === "string" && UUID_PATTERN.test(selected)) {
    const readable = readableCompanies.find((company) => company.id === selected);
    if (readable) return readable;
  }
  return readableCompanies[0] ?? null;
}

export function systemUserCallbackNotice(
  value: unknown,
  copy: SystemUserConnectionCopy,
): string | null {
  if (typeof value !== "string" || !CALLBACK_NOTICES.has(value as SystemUserCallbackNotice)) {
    return null;
  }
  return copy.callbackNotices[value as SystemUserCallbackNotice];
}

export function systemUserFilingPresentation(
  request: SystemUserRequestPresentation | null,
  copy: SystemUserConnectionCopy,
): FilingCopy {
  return request?.filing ?? copy.filing.missing;
}

export function buildSystemUserRequestPresentation(
  request: SystemUserRequestRow,
  copy: SystemUserConnectionCopy,
): SystemUserRequestPresentation {
  if (!REQUEST_STATUSES.has(request.status)) {
    throw new Error("invalid_local_system_user_request");
  }
  const companyId = requiredLocalUuid(request.company_id);
  const requestId = requiredLocalUuid(request.id);
  const continueHref = validatedContinueHref(request);

  if (request.status === "accepted" && request.preflight_verified_at !== null) {
    return {
      companyId,
      requestId,
      ...copy.verified,
      badgeVariant: "success",
      badgeIcon: "check",
      continueHref: null,
      actions: [],
      filing: copy.filing.ready,
    };
  }

  const base = {
    companyId,
    requestId,
    ...copy.states[request.status],
    continueHref,
  };

  switch (request.status) {
    case "creating":
      return {
        ...base,
        badgeVariant: "info",
        actions: ["refresh"],
        filing: copy.filing.action,
      };
    case "new":
      return {
        ...base,
        badgeVariant: "warning",
        actions: continueHref ? ["continue", "refresh"] : ["refresh"],
        filing: copy.filing.waiting,
      };
    case "accepted":
      return {
        ...base,
        badgeVariant: "info",
        actions: ["refresh"],
        filing: copy.filing.action,
      };
    case "verification_failed":
      return {
        ...base,
        badgeVariant: "danger",
        badgeIcon: "alert",
        actions: ["retry_verification"],
        filing: copy.filing.action,
      };
    case "rejected":
    case "denied":
    case "timedout":
      return {
        ...base,
        badgeVariant: "danger",
        badgeIcon: "alert",
        actions: ["create"],
        filing: copy.filing.action,
      };
  }
}

export async function loadSystemUserRequestPresentations(
  supabase: SupabaseClient,
  companyIds: string[],
  copy: SystemUserConnectionCopy,
): Promise<SystemUserRequestPresentation[]> {
  const { listSystemUserRequests } = await import("../../lib/supabase/server");
  const requests = await listSystemUserRequests(supabase, companyIds);
  return requests.map((request) => buildSystemUserRequestPresentation(request, copy));
}
