export const GENERIC_ACTION_ERROR =
  "Handlingen kunne ikke fullføres. Prøv igjen, eller kontakt støtte med tidspunktet for feilen.";

type ErrorExposure = "internal" | "public";

function normalizedMessage(message: string) {
  const normalized = message.trim();
  return normalized ? normalized.slice(0, 500) : GENERIC_ACTION_ERROR;
}

export function actionErrorMessage(
  message: string,
  exposure: ErrorExposure = "internal",
  environment = process.env.NODE_ENV,
) {
  if (exposure === "internal" && environment === "production") {
    return GENERIC_ACTION_ERROR;
  }
  return normalizedMessage(message);
}

export function encodeActionError(message: string) {
  return encodeURIComponent(actionErrorMessage(message));
}

export function encodePublicActionError(message: string) {
  return encodeURIComponent(actionErrorMessage(message, "public"));
}
