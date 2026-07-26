export type InvitationRole = "reviewer" | "read_only";
export type InvitationStatus = "pending" | "accepted" | "revoked" | "expired";

export type InvitationDeliveryEvent = {
  channel: "email";
  status: "queued" | "sent" | "failed";
  template: "workspace_invitation";
  recipientEmail: string;
  queuedAt: string;
};

export function validateInvitationRole(value: string): InvitationRole {
  if (!["reviewer", "read_only"].includes(value)) {
    throw new Error("Ugyldig invitasjonsrolle.");
  }
  return value as InvitationRole;
}

export function normalizeInvitationEmail(email: string) {
  const normalized = email.trim().toLowerCase();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(normalized)) {
    throw new Error("Ugyldig e-postadresse for invitasjon.");
  }
  return normalized;
}

export function invitationExpiry(now = new Date()) {
  const expires = new Date(now);
  expires.setDate(expires.getDate() + 14);
  return expires.toISOString();
}

export function invitationStatus(
  invitation: { status: InvitationStatus; expires_at: string },
  now = new Date(),
): InvitationStatus {
  if (invitation.status !== "pending") {
    return invitation.status;
  }
  return new Date(invitation.expires_at).getTime() < now.getTime() ? "expired" : "pending";
}

export async function invitationTokenHash(token: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function invitationDeliveryEvent(input: {
  recipientEmail: string;
  status?: "queued" | "sent" | "failed";
  queuedAt?: string;
}): InvitationDeliveryEvent {
  return {
    channel: "email",
    status: input.status ?? "queued",
    template: "workspace_invitation",
    recipientEmail: normalizeInvitationEmail(input.recipientEmail),
    queuedAt: input.queuedAt ?? new Date().toISOString(),
  };
}

export function buildInvitationEmail(input: {
  companyName: string;
  recipientEmail: string;
  role: InvitationRole;
  acceptUrl: string;
}) {
  const roleLabel = input.role === "reviewer" ? "reviewer" : "read-only";
  return {
    to: normalizeInvitationEmail(input.recipientEmail),
    subject: `Invitasjon til Talli: ${input.companyName}`,
    body: `Du er invitert som ${roleLabel} i Talli for ${input.companyName}. Godta invitasjonen: ${input.acceptUrl}`,
  };
}

export function reviewChecklistStatus(
  comments: { severity: "advisory" | "hard_block"; acknowledged_by?: string | null }[],
) {
  const advisoryCount = comments.filter((comment) => comment.severity === "advisory").length;
  const hardBlockCount = comments.filter((comment) => comment.severity === "hard_block").length;
  const acknowledgedAdvisoryCount = comments.filter(
    (comment) => comment.severity === "advisory" && comment.acknowledged_by,
  ).length;
  return {
    advisoryCount,
    hardBlockCount,
    acknowledgedAdvisoryCount,
    readinessImpact: hardBlockCount > 0 ? "hard_block" : "advisory_only",
  };
}
