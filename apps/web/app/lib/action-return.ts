const localOrigin = "https://talli.invalid";
const annualPath = /^\/companies\/[A-Za-z0-9_-]+\/annual-reporting\/\d{4}(?:\/(?:aksjonaerregisteroppgaven|aarsregnskap|skattemelding|review))?\/?$/;

export function actionReturnPath(value: FormDataEntryValue | string | null | undefined) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return "/";
  try {
    const url = new URL(value, localOrigin);
    if (url.origin !== localOrigin) return "/";
    if (url.pathname === "/onboarding") {
      const allowed = new Set(["companyId", "accountingYear", "step"]);
      const keys = [...url.searchParams.keys()];
      if (url.hash || keys.some((key) => !allowed.has(key)) || keys.length !== new Set(keys).size) return "/";
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(url.searchParams.get("companyId") ?? "")) return "/";
      if (!["2025", "2026"].includes(url.searchParams.get("accountingYear") ?? "")) return "/";
      if (url.searchParams.has("step") && url.searchParams.get("step") !== "bank") return "/";
      return `${url.pathname}${url.search}`;
    }
    if (!annualPath.test(url.pathname)) return "/";
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
