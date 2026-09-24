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

// We can prove these alternatives disjoint without attempting general JSON
// Schema implication: every object requires a different string const tag.
// Refuse other oneOf shapes rather than silently giving them anyOf semantics.
function discriminatedVariants(document, schema, location) {
  if (!Array.isArray(schema.oneOf) || schema.oneOf.length === 0) {
    throw new Error(`${location} has invalid oneOf`);
  }
  const allowed = new Set(["oneOf", "discriminator", "title", "description", "examples", "default"]);
  if (Object.keys(schema).some((key) => !allowed.has(key))) {
    throw new Error(`${location} has unsupported oneOf sibling keywords`);
  }
  const discriminator = requireObject(schema.discriminator, `${location}.discriminator`);
  const property = discriminator.propertyName;
  if (typeof property !== "string" || !property ||
      Object.keys(discriminator).some((key) => !["propertyName", "mapping"].includes(key))) {
    throw new Error(`${location} has unsupported oneOf discriminator`);
  }
  const mapping = requireObject(discriminator.mapping, `${location}.discriminator.mapping`);
  const variants = new Map();
  for (const [index, member] of schema.oneOf.entries()) {
    requireObject(member, `${location}.oneOf[${index}]`);
    if (typeof member.$ref !== "string" || Object.keys(member).length !== 1) {
      throw new Error(`${location} oneOf alternatives must be plain local schema references`);
    }
    const variant = resolveSchema(document, member, location);
    const tag = variant.properties?.[property];
    if (variant.type !== "object" || variant.anyOf || variant.oneOf || variant.allOf ||
        !Array.isArray(variant.required) || !variant.required.includes(property) ||
        tag?.type !== "string" || typeof tag.const !== "string" ||
        tag.anyOf || tag.oneOf || tag.allOf || tag.$ref) {
      throw new Error(`${location} oneOf alternatives require a string const discriminator`);
    }
    if (variants.has(tag.const)) {
      throw new Error(`${location} has ambiguous oneOf discriminator ${tag.const}`);
    }
    if (!Object.hasOwn(mapping, tag.const) || mapping[tag.const] !== member.$ref) {
      throw new Error(`${location} has inconsistent oneOf discriminator mapping`);
    }
    variants.set(tag.const, member);
  }
  if (Object.keys(mapping).length !== variants.size) {
    throw new Error(`${location} has extra oneOf discriminator mappings`);
  }
  return variants;
}

// Strict comparison inside unions: preserve every keyword, including ones the
// ordinary additive response comparison does not interpret. Expand references
// so an unchanged $ref cannot conceal a changed component. Cycles are outside
// this deliberately finite supported subset.
function unionSchemaIdentity(document, schema, location, references = new Set()) {
  requireObject(schema, location);
  if (Object.hasOwn(schema, "$ref")) {
    if (Object.keys(schema).length !== 1 || references.has(schema.$ref)) {
      throw new Error(`${location} has unsupported recursive or sibling schema reference`);
    }
    return unionSchemaIdentity(document, resolveSchema(document, schema, location), location,
      new Set([...references, schema.$ref]));
  }
  const result = {};
  for (const key of Object.keys(schema).sort()) {
    const value = schema[key];
    if (key === "properties") {
      result[key] = Object.fromEntries(Object.keys(value).sort().map((name) => [name,
        unionSchemaIdentity(document, value[name], `${location}.${name}`, references)]));
    } else if (["items", "additionalProperties"].includes(key) && typeof value === "object" && value !== null) {
      result[key] = unionSchemaIdentity(document, value, `${location}.${key}`, references);
    } else if (["oneOf", "anyOf", "allOf"].includes(key)) {
      result[key] = value.map((member) => unionSchemaIdentity(document, member, location, references))
        .sort((a, b) => {
          const left = JSON.stringify(a), right = JSON.stringify(b);
          return left < right ? -1 : left > right ? 1 : 0;
        });
    } else if (key === "required" || key === "enum") {
      result[key] = [...value].sort();
    } else {
      result[key] = sortJsonKeys(value);
    }
  }
  return result;
}

function sortJsonKeys(value) {
  if (Array.isArray(value)) return value.map(sortJsonKeys);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortJsonKeys(value[key])]));
  }
  return value;
}

function validateSchema(document, schema, location, references = new Set()) {
  const resolved = resolveSchema(document, schema, location);
  if (schema.$ref) {
    if (references.has(schema.$ref)) throw new Error(`${location} has unsupported recursive schema reference`);
    references = new Set([...references, schema.$ref]);
  }
  if (Object.hasOwn(resolved, "oneOf")) {
    for (const [tag, member] of discriminatedVariants(document, resolved, location)) {
      validateSchema(document, member, `${location}.oneOf[${tag}]`, references);
    }
    return;
  }
  if (Object.hasOwn(resolved, "anyOf")) {
    if (!Array.isArray(resolved.anyOf) || resolved.anyOf.length === 0) {
      throw new Error(`${location} has invalid anyOf`);
    }
    for (const member of resolved.anyOf) validateSchema(document, member, location, references);
    return;
  }
  if (!["array", "boolean", "integer", "null", "number", "object", "string"].includes(resolved.type)) {
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
      validateSchema(document, propertySchema, `${location}.${name}`, references);
    }
  }
  if (resolved.type === "array") {
    validateSchema(document, resolved.items, `${location}.items`, references);
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
  if (Object.hasOwn(resolved, "oneOf")) {
    const variants = discriminatedVariants(document, resolved, location);
    let matches = 0;
    for (const member of variants.values()) {
      try {
        assertValueMatchesSchema(document, member, value, location);
        matches += 1;
      } catch {
        // oneOf requires exactly one successful branch, not the first success.
      }
    }
    if (matches !== 1) throw new Error(`${location} must match exactly one schema`);
    return;
  }
  if (resolved.anyOf) {
    for (const member of resolved.anyOf) {
      try {
        assertValueMatchesSchema(document, member, value, location);
        return;
      } catch {
        // Try the next permitted schema.
      }
    }
    throw new Error(`${location} does not match any allowed schema`);
  }
  if (resolved.const !== undefined && value !== resolved.const) {
    throw new Error(`${location} does not match const ${resolved.const}`);
  }
  if (resolved.enum && !resolved.enum.includes(value)) {
    throw new Error(`${location} does not match enum`);
  }
  if (resolved.type === "array") {
    if (!Array.isArray(value)) throw new Error(`${location} must be array`);
    for (const [index, item] of value.entries()) {
      assertValueMatchesSchema(document, resolved.items, item, `${location}[${index}]`);
    }
    return;
  }
  if (resolved.type === "object") {
    requireObject(value, location);
    for (const required of resolved.required ?? []) {
      if (!Object.hasOwn(value, required)) throw new Error(`${location}.${required} is required`);
    }
    for (const property of Object.keys(value)) {
      if (Object.hasOwn(resolved.properties ?? {}, property)) continue;
      if (resolved.additionalProperties === false) throw new Error(`${location}.${property} is not allowed`);
      if (typeof resolved.additionalProperties === "object" && resolved.additionalProperties !== null) {
        assertValueMatchesSchema(document, resolved.additionalProperties, value[property], `${location}.${property}`);
      }
    }
    for (const [property, propertySchema] of Object.entries(resolved.properties ?? {})) {
      if (Object.hasOwn(value, property)) {
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
  if (resolved.type === "null") {
    if (value !== null) throw new Error(`${location} must be null`);
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
  if ((resolved.type === "number" || resolved.type === "integer") &&
      (!Number.isFinite(value) || (resolved.minimum !== undefined && value < resolved.minimum) ||
      (resolved.maximum !== undefined && value > resolved.maximum))) {
    throw new Error(`${location} is outside numeric bounds`);
  }
  if (resolved.type === "string" && resolved.pattern !== undefined && !new RegExp(resolved.pattern, "u").test(value)) {
    throw new Error(`${location} does not match pattern`);
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
  if ([baseline, current].some((schema) => Object.hasOwn(schema, "oneOf") || Object.hasOwn(schema, "anyOf"))) {
    // Strict union identity also checks oneOf nested within a nullable anyOf.
    // Reordering alternatives is harmless; additions, removals, discriminator
    // changes, or any referenced variant change require an explicit new contract.
    const before = unionSchemaIdentity(baselineDocument, baselineSchema, location);
    const after = unionSchemaIdentity(currentDocument, currentSchema, location);
    if (JSON.stringify(before) !== JSON.stringify(after)) {
      throw new Error(`${location} changed union schema`);
    }
    return;
  }
  if (baseline.type !== current.type) {
    throw new Error(`${location} changed type from ${baseline.type} to ${current.type}`);
  }
  for (const keyword of ["const", "format", "default", "nullable"]) {
    if (
      (Object.hasOwn(baseline, keyword) || Object.hasOwn(current, keyword)) &&
      JSON.stringify(baseline[keyword]) !== JSON.stringify(current[keyword])
    ) {
      throw new Error(
        `${location} changed ${keyword} from ${JSON.stringify(baseline[keyword])} to ${JSON.stringify(current[keyword])}`,
      );
    }
  }
  if (
    (Object.hasOwn(baseline, "enum") || Object.hasOwn(current, "enum")) &&
    JSON.stringify(baseline.enum) !== JSON.stringify(current.enum)
  ) {
    throw new Error(
      `${location} changed enum from ${JSON.stringify(baseline.enum)} to ${JSON.stringify(current.enum)}`,
    );
  }
  if (baseline.type === "array") {
    compareResponseSchema(
      baselineDocument,
      currentDocument,
      baseline.items,
      current.items,
      `${location}.items`,
    );
    return;
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

function operationParameters(pathItem, operation) {
  return [...(pathItem.parameters ?? []), ...(operation.parameters ?? [])];
}

function compareRequestRequirements(
  baselineDocument,
  currentDocument,
  baselinePath,
  currentPath,
  baselineOperation,
  currentOperation,
) {
  const baselineParameters = new Map(
    operationParameters(baselinePath, baselineOperation).map((parameter) => [
      `${parameter.in}:${parameter.name}`,
      parameter,
    ]),
  );
  const currentParameters = new Map(
    operationParameters(currentPath, currentOperation).map((parameter) => [
      `${parameter.in}:${parameter.name}`,
      parameter,
    ]),
  );
  for (const [key, baselineParameter] of baselineParameters) {
    const currentParameter = currentParameters.get(key);
    if (!currentParameter) {
      throw new Error(
        `${baselineOperation.operationId} removed parameter ${baselineParameter.in} ${baselineParameter.name}`,
      );
    }
    const location = `${baselineOperation.operationId} parameter ${baselineParameter.in} ${baselineParameter.name}`;
    const baselineSchema = resolveSchema(
      baselineDocument,
      baselineParameter.schema,
      location,
    );
    const currentSchema = resolveSchema(
      currentDocument,
      currentParameter.schema,
      location,
    );
    if (JSON.stringify(baselineSchema) !== JSON.stringify(currentSchema)) {
      throw new Error(`${location} changed schema`);
    }
  }
  for (const parameter of operationParameters(currentPath, currentOperation)) {
    const baselineParameter = baselineParameters.get(`${parameter.in}:${parameter.name}`);
    if (parameter.required === true && baselineParameter?.required !== true) {
      throw new Error(
        `${baselineOperation.operationId} added required parameter ${parameter.in} ${parameter.name}`,
      );
    }
  }
  if (
    currentOperation.requestBody?.required === true &&
    baselineOperation.requestBody?.required !== true
  ) {
    throw new Error(`${baselineOperation.operationId} made the request body required`);
  }
  if (baselineOperation.requestBody && !currentOperation.requestBody) {
    throw new Error(`${baselineOperation.operationId} removed the request body`);
  }
  for (const [mediaType, baselineContent] of Object.entries(
    baselineOperation.requestBody?.content ?? {},
  )) {
    const currentContent = currentOperation.requestBody?.content?.[mediaType];
    if (!currentContent) {
      throw new Error(
        `${baselineOperation.operationId} request body removed ${mediaType}`,
      );
    }
    const location = `${baselineOperation.operationId} request body ${mediaType}`;
    const baselineSchema = resolveSchema(
      baselineDocument,
      baselineContent.schema,
      location,
    );
    const currentSchema = resolveSchema(
      currentDocument,
      currentContent.schema,
      location,
    );
    if (JSON.stringify(baselineSchema) !== JSON.stringify(currentSchema)) {
      throw new Error(`${location} changed schema`);
    }
  }
}

function effectiveSecurity(document, operation) {
  const security = Object.hasOwn(operation, "security")
    ? operation.security
    : document.security;
  return !security?.length ? [{}] : security;
}

function canonicalSecurity(security) {
  return security
    .map((requirement) =>
      Object.fromEntries(
        Object.entries(requirement)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([scheme, scopes]) => [scheme, [...scopes].sort()]),
      ),
    )
    .map((requirement) => JSON.stringify(requirement))
    .sort();
}

function compareSecurityRequirements(
  baselineDocument,
  currentDocument,
  baselineOperation,
  currentOperation,
) {
  const baselineSecurity = effectiveSecurity(baselineDocument, baselineOperation);
  const currentSecurity = effectiveSecurity(currentDocument, currentOperation);
  if (
    JSON.stringify(canonicalSecurity(baselineSecurity)) !==
    JSON.stringify(canonicalSecurity(currentSecurity))
  ) {
    throw new Error(
      `${baselineOperation.operationId} changed authentication requirements incompatibly`,
    );
  }

  const referencedSchemes = new Set(
    baselineSecurity.flatMap((requirement) => Object.keys(requirement)),
  );
  for (const scheme of referencedSchemes) {
    const baselineScheme = baselineDocument.components?.securitySchemes?.[scheme];
    const currentScheme = currentDocument.components?.securitySchemes?.[scheme];
    if (!currentScheme) {
      throw new Error(`security scheme ${scheme} changed incompatibly`);
    }
    const contractKeys = [
      "type",
      "scheme",
      "bearerFormat",
      "name",
      "in",
      "openIdConnectUrl",
      "flows",
    ];
    if (
      contractKeys.some(
        (key) =>
          JSON.stringify(baselineScheme?.[key]) !== JSON.stringify(currentScheme[key]),
      )
    ) {
      throw new Error(`security scheme ${scheme} changed incompatibly`);
    }
  }
}

export function assertContractPackageVersion(document, packageManifest) {
  const contractVersion = document.info?.version;
  const packageVersion = packageManifest?.version;
  if (contractVersion !== packageVersion) {
    throw new Error(
      `contract version ${contractVersion} does not match client package version ${packageVersion}`,
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
      compareRequestRequirements(
        baseline,
        current,
        baselinePath,
        currentPath,
        baselineOperation,
        currentOperation,
      );
      compareSecurityRequirements(
        baseline,
        current,
        baselineOperation,
        currentOperation,
      );
      for (const [status, baselineResponse] of Object.entries(
        baselineOperation.responses,
      )) {
        const currentResponse = currentOperation.responses?.[status];
        if (!currentResponse) {
          throw new Error(`${baselineOperation.operationId} removed response ${status}`);
        }
        for (const [header, baselineHeader] of Object.entries(
          baselineResponse.headers ?? {},
        )) {
          const currentHeader = currentResponse.headers?.[header];
          if (!currentHeader) {
            throw new Error(
              `${baselineOperation.operationId} response ${status} removed header ${header}`,
            );
          }
          if (
            JSON.stringify(baselineHeader.schema) !==
            JSON.stringify(currentHeader.schema)
          ) {
            throw new Error(
              `${baselineOperation.operationId} response ${status} header ${header} changed schema`,
            );
          }
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
