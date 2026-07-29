// Pinned runtime of the generated v1.0.0 client from commit c13fa25a.
// Keep this fixture unchanged so overlap tests exercise a previously deployed consumer.

function isRecord(value) {
  return typeof value === "object" && value !== null;
}

function isSystemBoundaryStatus(value) {
  return (
    isRecord(value) &&
    typeof value.apiVersion === "string" &&
    typeof value.service === "string" &&
    value.status === "AVAILABLE"
  );
}

function isProblemDetails(value) {
  return (
    isRecord(value) &&
    typeof value.type === "string" &&
    typeof value.title === "string" &&
    typeof value.status === "number" &&
    typeof value.detail === "string" &&
    typeof value.instance === "string" &&
    typeof value.code === "string" &&
    typeof value.requestId === "string"
  );
}

export class BaselineTalliApiError extends Error {
  constructor(status, problem) {
    super(problem?.code ?? `HTTP_${status}`);
    this.name = "BaselineTalliApiError";
    this.status = status;
    this.problem = problem;
  }
}

export function createBaselineTalliApiClient(options) {
  const fetchImplementation = options.fetch ?? globalThis.fetch;
  const baseUrl = options.baseUrl.replace(/\/$/, "");

  return {
    async systemBoundaryGetTracerStatus(request = {}) {
      const response = await fetchImplementation(
        `${baseUrl}/api/v1/system-boundary/tracer`,
        {
          cache: "no-store",
          headers: {
            Accept: "application/json, application/problem+json",
            ...options.headers,
            ...request.headers,
          },
          method: "GET",
          signal: request.signal,
        },
      );

      if (!response.ok) {
        const contentType = response.headers.get("content-type") ?? "";
        const candidate = contentType.includes("application/problem+json")
          ? await response.json().catch(() => undefined)
          : undefined;
        const problem = isProblemDetails(candidate) ? candidate : undefined;
        throw new BaselineTalliApiError(response.status, problem);
      }

      const candidate = await response.json();
      if (!isSystemBoundaryStatus(candidate)) {
        throw new BaselineTalliApiError(502, undefined);
      }
      return candidate;
    },
  };
}
