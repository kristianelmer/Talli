import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const HTTP_METHODS = new Set([
  "delete",
  "get",
  "head",
  "options",
  "patch",
  "post",
  "put",
  "trace",
]);

function requireObject(value, location) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${location} must be an object`);
  }
  return value;
}

function resolveSchema(document, schema, location) {
  requireObject(schema, location);
  if (!schema.$ref) return schema;
  const prefix = "#/components/schemas/";
  if (typeof schema.$ref !== "string" || !schema.$ref.startsWith(prefix)) {
    throw new Error(`${location} has unsupported schema reference ${schema.$ref}`);
  }
  const name = schema.$ref.slice(prefix.length);
  const resolved = document.components?.schemas?.[name];
  if (!resolved) throw new Error(`${location} references missing schema ${name}`);
  return resolved;
}

function validateSchema(document, schema, location) {
  const resolved = resolveSchema(document, schema, location);
  if (!["array", "boolean", "integer", "number", "object", "string"].includes(resolved.type)) {
    throw new Error(`${location} has unsupported or missing type`);
  }
  if (resolved.type === "object") {
    const properties = requireObject(resolved.properties ?? {}, `${location}.properties`);
    for (const required of resolved.required ?? []) {
      if (!(required in properties)) {
        throw new Error(`${location} requires missing property ${required}`);
      }
    }
    for (const [name, propertySchema] of Object.entries(properties)) {
      validateSchema(document, propertySchema, `${location}.${name}`);
    }
  }
  if (resolved.type === "array") {
    validateSchema(document, resolved.items, `${location}.items`);
  }
}

export function validateOpenApiDocument(document) {
  requireObject(document, "OpenAPI document");
  if (typeof document.openapi !== "string" || !document.openapi.startsWith("3.1.")) {
    throw new Error("OpenAPI document must use OpenAPI 3.1");
  }
  if (!document.info?.title || !document.info?.version) {
    throw new Error("OpenAPI info.title and info.version are required");
  }
  const paths = requireObject(document.paths, "OpenAPI paths");
  const operationIds = new Set();
  for (const [path, pathItem] of Object.entries(paths)) {
    requireObject(pathItem, `path ${path}`);
    for (const [method, operation] of Object.entries(pathItem)) {
      if (!HTTP_METHODS.has(method)) continue;
      requireObject(operation, `${method.toUpperCase()} ${path}`);
      if (!operation.operationId) {
        throw new Error(`${method.toUpperCase()} ${path} is missing operationId`);
      }
      if (operationIds.has(operation.operationId)) {
        throw new Error(`duplicate operationId ${operation.operationId}`);
      }
      operationIds.add(operation.operationId);
      const responses = requireObject(
        operation.responses,
        `${operation.operationId}.responses`,
      );
      for (const [status, response] of Object.entries(responses)) {
        requireObject(response, `${operation.operationId}.responses.${status}`);
        for (const [mediaType, content] of Object.entries(response.content ?? {})) {
          validateSchema(
            document,
            content.schema,
            `${operation.operationId}.responses.${status}.${mediaType}`,
          );
        }
      }
    }
  }
  if (operationIds.size === 0) throw new Error("OpenAPI document has no operations");
}

export function assertValueMatchesSchema(document, schema, value, location = "response") {
  const resolved = resolveSchema(document, schema, location);
  if (resolved.const !== undefined && value !== resolved.const) {
    throw new Error(`${location} does not match const ${resolved.const}`);
  }
  if (resolved.type === "object") {
    requireObject(value, location);
    for (const required of resolved.required ?? []) {
      if (!(required in value)) throw new Error(`${location}.${required} is required`);
    }
    for (const [property, propertySchema] of Object.entries(resolved.properties ?? {})) {
      if (property in value) {
        assertValueMatchesSchema(
          document,
          propertySchema,
          value[property],
          `${location}.${property}`,
        );
      }
    }
    return;
  }
  const expectedType =
    resolved.type === "integer" || resolved.type === "number" ? "number" : resolved.type;
  if (typeof value !== expectedType) {
    throw new Error(`${location} must be ${resolved.type}`);
  }
  if (resolved.type === "integer" && !Number.isInteger(value)) {
    throw new Error(`${location} must be integer`);
  }
}

function compareResponseSchema(
  baselineDocument,
  currentDocument,
  baselineSchema,
  currentSchema,
  location,
) {
  const baseline = resolveSchema(baselineDocument, baselineSchema, location);
  const current = resolveSchema(currentDocument, currentSchema, location);
  if (baseline.type !== current.type) {
    throw new Error(`${location} changed type from ${baseline.type} to ${current.type}`);
  }
  if (baseline.type !== "object") return;

  const baselineRequired = new Set(baseline.required ?? []);
  const currentRequired = new Set(current.required ?? []);
  for (const [property, propertySchema] of Object.entries(baseline.properties ?? {})) {
    const currentProperty = current.properties?.[property];
    if (!currentProperty) {
      throw new Error(`response property ${location}.${property} was removed`);
    }
    if (baselineRequired.has(property) && !currentRequired.has(property)) {
      throw new Error(`response property ${location}.${property} is no longer required`);
    }
    compareResponseSchema(
      baselineDocument,
      currentDocument,
      propertySchema,
      currentProperty,
      `${location}.${property}`,
    );
  }
}

export function assertCompatible(baseline, current) {
  validateOpenApiDocument(baseline);
  validateOpenApiDocument(current);
  for (const [path, baselinePath] of Object.entries(baseline.paths)) {
    const currentPath = current.paths[path];
    if (!currentPath) throw new Error(`path ${path} was removed`);
    for (const [method, baselineOperation] of Object.entries(baselinePath)) {
      if (!HTTP_METHODS.has(method)) continue;
      const currentOperation = currentPath[method];
      if (!currentOperation) throw new Error(`${method.toUpperCase()} ${path} was removed`);
      if (currentOperation.operationId !== baselineOperation.operationId) {
        throw new Error(`${method.toUpperCase()} ${path} changed operationId`);
      }
      for (const [status, baselineResponse] of Object.entries(
        baselineOperation.responses,
      )) {
        const currentResponse = currentOperation.responses?.[status];
        if (!currentResponse) {
          throw new Error(`${baselineOperation.operationId} removed response ${status}`);
        }
        for (const [mediaType, baselineContent] of Object.entries(
          baselineResponse.content ?? {},
        )) {
          const currentContent = currentResponse.content?.[mediaType];
          if (!currentContent) {
            throw new Error(
              `${baselineOperation.operationId} response ${status} removed ${mediaType}`,
            );
          }
          compareResponseSchema(
            baseline,
            current,
            baselineContent.schema,
            currentContent.schema,
            baselineContent.schema.$ref?.split("/").at(-1) ??
              `${baselineOperation.operationId}.${status}.${mediaType}`,
          );
        }
      }
    }
  }
}

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const currentPath = process.argv[2] ?? "contracts/openapi/talli-v1.json";
  const baselinePath =
    process.argv[3] ?? "contracts/openapi/baselines/talli-v1.0.0.json";
  const current = readJson(currentPath);
  const baseline = readJson(baselinePath);
  validateOpenApiDocument(current);
  assertCompatible(baseline, current);
  console.log(`OpenAPI valid and compatible with ${baselinePath}`);
}
