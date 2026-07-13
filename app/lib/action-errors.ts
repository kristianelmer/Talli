export const GENERIC_ACTION_ERROR =
  "Handlingen kunne ikke fullføres. Prøv igjen, eller kontakt støtte med tidspunktet for feilen.";
export const RF1086_RELEASE_SEALED_ACTION_ERROR =
  "En RF-1086-innsending pågår. Prøv handlingen igjen om et par minutter.";

const RF1086_RELEASE_SEALED_DATABASE_CODE = "55000";
const RF1086_RELEASE_SEALED_DATABASE_MESSAGE =
  "RF-1086 production release is temporarily sealed.";

type ErrorExposure = "internal" | "public";

function normalizedMessage(message: string) {
  const normalized = message.trim();
  return normalized ? normalized.slice(0, 500) : GENERIC_ACTION_ERROR;
}

function errorMessage(error: unknown) {
  if (typeof error === "string") return error;
  if (
    typeof error === "object" &&
    error !== null &&
    "message" in error &&
    typeof error.message === "string"
  ) {
    return error.message;
  }
  return GENERIC_ACTION_ERROR;
}

function isRf1086ReleaseSealError(error: unknown) {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === RF1086_RELEASE_SEALED_DATABASE_CODE &&
    "message" in error &&
    error.message === RF1086_RELEASE_SEALED_DATABASE_MESSAGE
  );
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

export function encodeActionError(error: unknown, environment = process.env.NODE_ENV) {
  const message =
    environment === "production" && isRf1086ReleaseSealError(error)
      ? RF1086_RELEASE_SEALED_ACTION_ERROR
      : actionErrorMessage(errorMessage(error), "internal", environment);
  return encodeURIComponent(message);
}

export function encodePublicActionError(message: string) {
  return encodeURIComponent(actionErrorMessage(message, "public"));
}
