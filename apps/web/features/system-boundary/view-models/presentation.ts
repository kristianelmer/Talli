import type { SystemBoundaryStatus } from "@talli/talli-api-client";

export interface BoundaryPresentation {
  heading: string;
  message: string;
  tone: "success" | "failure";
}

export function presentSystemBoundarySuccess(
  response: SystemBoundaryStatus,
): BoundaryPresentation {
  if (response.status !== "AVAILABLE") {
    return presentSystemBoundaryFailure(undefined);
  }
  return {
    heading: "Forbindelsen virker",
    message: "Talli-nettsiden har kontakt med backend-tjenesten.",
    tone: "success",
  };
}

export function presentSystemBoundaryFailure(
  _error: unknown,
  requestId?: string,
): BoundaryPresentation {
  const reference = requestId ? ` Oppgi referansen ${requestId} hvis problemet fortsetter.` : "";
  return {
    heading: "Tjenesten er midlertidig utilgjengelig",
    message: `Prøv igjen om litt.${reference}`,
    tone: "failure",
  };
}
