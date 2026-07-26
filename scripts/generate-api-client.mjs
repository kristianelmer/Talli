import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const check = process.argv.includes("--check");
const contractPath = resolve("contracts/openapi/talli-v1.json");
const outputPath = resolve("packages/talli-api-client/src/generated/client.ts");
const contract = JSON.parse(readFileSync(contractPath, "utf8"));
const path = "/api/v1/system-boundary/tracer";
const operation = contract.paths?.[path]?.get;

if (operation?.operationId !== "systemBoundaryGetTracerStatus") {
  throw new Error(`Expected systemBoundaryGetTracerStatus at ${path}`);
}

function resolveSchema(schema) {
  if (!schema?.$ref) {
    return schema;
  }
  const name = schema.$ref.split("/").at(-1);
  return contract.components?.schemas?.[name];
}

function schemaType(schema) {
  if (schema?.type === "string") return "string";
  if (schema?.type === "integer" || schema?.type === "number") return "number";
  if (schema?.type === "boolean") return "boolean";
  throw new Error(`Unsupported generated-client schema type: ${schema?.type}`);
}

function renderInterface(name, schema) {
  const required = new Set(schema.required ?? []);
  const properties = Object.entries(schema.properties ?? {})
    .map(([property, propertySchema]) => {
      const optional = required.has(property) ? "" : "?";
      return `  ${property}${optional}: ${schemaType(propertySchema)};`;
    })
    .join("\n");
  return `export interface ${name} {\n${properties}\n}`;
}

function renderGuard(name, schema) {
  const checks = (schema.required ?? []).map((property) => {
    const expectedType = schemaType(schema.properties[property]);
    return `    typeof value.${property} === "${expectedType}"`;
  });
  return `function is${name}(value: unknown): value is ${name} {
  return (
    isRecord(value) &&
${checks.join(" &&\n")}
  );
}`;
}

const successSchema = resolveSchema(
  operation.responses["200"].content["application/json"].schema,
);
const problemSchema = resolveSchema(
  operation.responses["503"].content["application/problem+json"].schema,
);

const source = `// Generated from contracts/openapi/talli-v1.json. Do not edit by hand.
// Contract version: ${contract.info.version}

${renderInterface("SystemBoundaryStatus", successSchema)}

${renderInterface("ProblemDetails", problemSchema)}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

${renderGuard("SystemBoundaryStatus", successSchema)}

${renderGuard("ProblemDetails", problemSchema)}

export class TalliApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails | undefined;

  constructor(
    status: number,
    problem: ProblemDetails | undefined,
  ) {
    super(problem?.code ?? \`HTTP_\${status}\`);
    this.name = "TalliApiError";
    this.status = status;
    this.problem = problem;
  }
}

export interface TalliApiClientOptions {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
  headers?: HeadersInit;
}

export interface TalliRequestOptions {
  signal?: AbortSignal;
  headers?: HeadersInit;
}

export function createTalliApiClient(options: TalliApiClientOptions) {
  const fetchImplementation = options.fetch ?? globalThis.fetch;
  const baseUrl = options.baseUrl.replace(/\\/$/, "");

  return {
    async ${operation.operationId}(
      request: TalliRequestOptions = {},
    ): Promise<SystemBoundaryStatus> {
      const response = await fetchImplementation(\`\${baseUrl}${path}\`, {
        cache: "no-store",
        headers: {
          Accept: "application/json, application/problem+json",
          ...options.headers,
          ...request.headers,
        },
        method: "GET",
        signal: request.signal,
      });

      if (!response.ok) {
        const contentType = response.headers.get("content-type") ?? "";
        const candidate = contentType.includes("application/problem+json")
          ? await response.json().catch(() => undefined)
          : undefined;
        const problem = isProblemDetails(candidate) ? candidate : undefined;
        throw new TalliApiError(response.status, problem);
      }

      const candidate: unknown = await response.json();
      if (!isSystemBoundaryStatus(candidate)) {
        throw new TalliApiError(502, undefined);
      }
      return candidate;
    },
  };
}
`;

if (check) {
  let committed = "";
  try {
    committed = readFileSync(outputPath, "utf8");
  } catch {
    // A missing artifact is contract drift.
  }
  if (committed !== source) {
    console.error("Generated TypeScript client drift detected.");
    process.exitCode = 1;
  }
} else {
  mkdirSync(resolve("packages/talli-api-client/src/generated"), { recursive: true });
  writeFileSync(outputPath, source);
}
