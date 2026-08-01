export type InvitationStatus = "pending" | "accepted" | "revoked" | "expired";

export function invitationStatus(
  invitation: { status: InvitationStatus; expiresAt?: string; expires_at?: string },
  now = new Date(),
): InvitationStatus {
  if (invitation.status !== "pending") {
    return invitation.status;
  }
  return new Date(invitation.expiresAt ?? invitation.expires_at ?? "").getTime() < now.getTime()
    ? "expired"
    : "pending";
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
