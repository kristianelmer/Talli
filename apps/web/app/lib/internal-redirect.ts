export function sanitizeInternalRedirect(
  value: string | null | undefined,
  fallback = "/dashboard",
): string {
  if (
    !value ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    /[\r\n\0]/u.test(value)
  ) {
    return fallback;
  }
  const parsed = new URL(value, "https://talli.internal");
  if (parsed.origin !== "https://talli.internal") return fallback;
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}
