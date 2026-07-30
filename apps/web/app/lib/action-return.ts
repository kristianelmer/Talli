const localOrigin = "https://talli.invalid";
const annualPath = /^\/companies\/[A-Za-z0-9_-]+\/annual-reporting\/\d{4}(?:\/(?:aksjonaerregisteroppgaven|aarsregnskap|skattemelding|review))?\/?$/;

export function actionReturnPath(value: FormDataEntryValue | string | null | undefined) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return "/";
  try {
    const url = new URL(value, localOrigin);
    if (url.origin !== localOrigin || !annualPath.test(url.pathname)) return "/";
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "/";
  }
}

export function actionReturnPathWithMessage(
  value: FormDataEntryValue | string | null | undefined,
  key: "error" | "success",
  message: string,
) {
  const safePath = actionReturnPath(value);
  const url = new URL(safePath, localOrigin);
  url.searchParams.set(key, message);
  return `${url.pathname}${url.search}${url.hash}`;
}
