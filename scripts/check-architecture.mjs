import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join, relative, resolve } from "node:path";

const MODULE_REQUIRED = [
  "schemaVersion",
  "kind",
  "name",
  "path",
  "owner",
  "purpose",
  "documentation",
  "publicEntryPoint",
  "dependencies",
  "allowedImports",
  "forbiddenResponsibilities",
  "tests",
  "compatibilityExceptions",
];
const BACKEND_SYSTEM_REQUIRED = [
  "schemaVersion",
  "name",
  "documentation",
  "compositionRoot",
  "workflows",
  "operationalControlState",
  "technicalOwnership",
  "infrastructure",
  "adapterBindings",
  "allowedDependencies",
];
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/u;

function rootPath(root) {
  return root instanceof URL ? fileURLToPath(root) : resolve(root);
}

function readJson(path, errors) {
  try {
    const value = JSON.parse(readFileSync(path, "utf8"));
    if (!value || Array.isArray(value) || typeof value !== "object") {
      errors.push(`${path}: expected a JSON object`);
      return {};
    }
    return value;
  } catch (error) {
    errors.push(`${path}: ${error.message}`);
    return {};
  }
}

function walk(directory, predicate, result = []) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (["node_modules", ".next", "__pycache__"].includes(entry.name)) continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) walk(path, predicate, result);
    else if (predicate(path)) result.push(path);
  }
  return result;
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
  }
  return value;
}

function moduleSourceFiles(root, manifest) {
  const extension = manifest.kind === "backend-capability" ? /\.py$/u : /\.[cm]?[jt]sx?$/u;
  return walk(join(root, manifest.path), (path) => extension.test(path));
}

function importedSpecifiers(source) {
  const values = [];
  for (const match of source.matchAll(/(?:from\s+|import\s*\()["']([^"']+)["']/gu)) {
    values.push(match[1]);
  }
  for (const match of source.matchAll(/^\s*from\s+([A-Za-z_][\w.]*)\s+import\s+/gmu)) {
    values.push(match[1]);
  }
  for (const match of source.matchAll(/^\s*import\s+["']([^"']+)["']/gmu)) {
    values.push(match[1]);
  }
  return values;
}

function declaredFeatureImports(manifest) {
  return new Set(
    manifest.dependencies
      .filter((dependency) => dependency.kind === "feature")
      .map((dependency) => `@/features/${dependency.module}`),
  );
}

function declaredBackendImports(manifest) {
  return new Set(
    manifest.dependencies
      .map((dependency) => `talli_backend.modules.${dependency.module}.public`),
  );
}

function documentationTokens(manifest) {
  const tokens = [manifest.publicEntryPoint];
  if (manifest.kind === "web-feature") {
    tokens.push(...manifest.ownedRoutes, ...manifest.apiOperations);
  } else {
    for (const values of Object.values(manifest.exports)) tokens.push(...values);
    tokens.push(...manifest.owns.tables, ...manifest.ports.map((port) => port.name));
  }
  return tokens;
}

function validateModule(root, manifestPath, errors) {
  const manifest = readJson(manifestPath, errors);
  const label = relative(root, manifestPath);
  for (const field of MODULE_REQUIRED) {
    if (!(field in manifest)) errors.push(`${label}: missing ${field}`);
  }
  if (manifest.schemaVersion !== "1.0") errors.push(`${label}: unsupported schemaVersion`);
  if (!["backend-capability", "web-feature"].includes(manifest.kind)) {
    errors.push(`${label}: unsupported kind`);
    return manifest;
  }
  if (!Array.isArray(manifest.forbiddenResponsibilities) || !manifest.forbiddenResponsibilities.length) {
    errors.push(`${label}: forbiddenResponsibilities must be a non-empty array`);
  }
  if (!Array.isArray(manifest.dependencies) || !Array.isArray(manifest.allowedImports)) {
    errors.push(`${label}: dependencies and allowedImports must be arrays`);
  }
  if (join(root, manifest.path) !== dirname(manifestPath)) {
    errors.push(`${label}: path must name the directory containing module.json`);
  }
  const documentationPath = join(root, manifest.documentation ?? "");
  if (!existsSync(documentationPath)) {
    errors.push(`${label}: documentation does not exist`);
  } else {
    const documentation = readFileSync(documentationPath, "utf8");
    for (const token of documentationTokens(manifest)) {
      if (token && !documentation.includes(token)) {
        errors.push(`${label}: documentation omits declared ${token}`);
      }
    }
  }

  if (manifest.kind === "backend-capability") {
    if (!manifest.path.match(/^apps\/backend\/src\/talli_backend\/modules\/[a-z][a-z0-9_]*$/u)) {
      errors.push(`${label}: backend path must be a capability module directory`);
    }
    if (manifest.publicEntryPoint !== `talli_backend.modules.${manifest.name}.public`) {
      errors.push(`${label}: backend publicEntryPoint must be the module public package`);
    }
    if (!existsSync(join(root, manifest.path, "public.py"))) {
      errors.push(`${label}: backend publicEntryPoint has no public.py`);
    }
    for (const field of ["exports", "owns", "ports"]) {
      if (!(field in manifest)) errors.push(`${label}: backend manifest missing ${field}`);
    }
  } else {
    if (!manifest.path.match(/^apps\/web\/features\/[a-z][a-z0-9-]*$/u)) {
      errors.push(`${label}: web path must be a feature directory`);
    }
    if (manifest.publicEntryPoint !== `@/features/${manifest.name}`) {
      errors.push(`${label}: web publicEntryPoint must be the feature root alias`);
    }
    if (!existsSync(join(root, manifest.path, "index.ts"))) {
      errors.push(`${label}: web publicEntryPoint has no index.ts`);
    }
    for (const field of ["ownedRoutes", "apiOperations", "cachePolicy", "directBrowserFlows"]) {
      if (!(field in manifest)) errors.push(`${label}: web manifest missing ${field}`);
    }
  }
  return manifest;
}

function checkModuleImports(root, manifest, errors) {
  const label = `${manifest.owner} (${manifest.path})`;
  const allowedModuleImports = manifest.kind === "web-feature"
    ? declaredFeatureImports(manifest)
    : declaredBackendImports(manifest);
  for (const path of moduleSourceFiles(root, manifest)) {
    const source = readFileSync(path, "utf8");
    for (const specifier of importedSpecifiers(source)) {
      if (specifier.startsWith(".")) {
        const sourceRoot = resolve(root, manifest.path);
        const importedPath = resolve(dirname(path), specifier);
        if (importedPath !== sourceRoot && !importedPath.startsWith(`${sourceRoot}/`)) {
          errors.push(`${label}: forbidden cross-module relative import ${specifier}`);
        }
        continue;
      }
      if (specifier.startsWith("node:")) continue;
      if (manifest.kind === "web-feature" && specifier.startsWith("@/features/")) {
        if (!allowedModuleImports.has(specifier)) errors.push(`${label}: undeclared feature import ${specifier}`);
        continue;
      }
      if (manifest.kind === "backend-capability" && specifier.startsWith("talli_backend.modules.")) {
        if (!allowedModuleImports.has(specifier)) errors.push(`${label}: forbidden backend deep import ${specifier}`);
        continue;
      }
      if (!manifest.allowedImports.includes(specifier) && !["typing"].includes(specifier)) {
        errors.push(`${label}: undeclared import ${specifier}`);
      }
    }
    if (manifest.kind === "web-feature") {
      if (/\bfetch\s*\(/u.test(source)) errors.push(`${label}: direct business fetch is forbidden`);
      if (/\bcreate(?:Browser|Server)?Client\s*\(|\.(?:from|rpc|storage|channel)\s*\(/u.test(source)) {
        errors.push(`${label}: direct web business persistence is forbidden`);
      }
      if (/@talli\/talli-api-client\//u.test(source)) {
        errors.push(`${label}: generated-client deep import is forbidden`);
      }
    }
  }
}

function validateSystemManifest(root, errors) {
  const path = join(root, "architecture/backend-system.json");
  const manifest = readJson(path, errors);
  for (const field of BACKEND_SYSTEM_REQUIRED) {
    if (!(field in manifest)) errors.push(`architecture/backend-system.json: missing ${field}`);
  }
  if (manifest.schemaVersion !== "1.0" || manifest.name !== "talli-backend-system") {
    errors.push("architecture/backend-system.json: invalid identity");
  }
  const documentationPath = join(root, manifest.documentation ?? "");
  if (!existsSync(documentationPath)) {
    errors.push("architecture/backend-system.json: missing documentation");
  } else {
    const documentation = readFileSync(documentationPath, "utf8");
    const tokens = [
      ...(manifest.workflows ?? []).flatMap((workflow) => [workflow.name, ...(workflow.publicPackages ?? []), ...(workflow.routes ?? [])]),
      ...(manifest.operationalControlState?.tables ?? []),
      ...(manifest.technicalOwnership?.tables ?? []),
      ...Object.keys(manifest.infrastructure ?? {}),
      ...(manifest.adapterBindings ?? []).flatMap((binding) => [binding.port, binding.adapter]),
    ];
    for (const token of tokens) {
      if (token && !documentation.includes(token)) {
        errors.push(`architecture/backend-system.json: documentation omits declared ${token}`);
      }
    }
  }
  if (!existsSync(join(root, manifest.compositionRoot ?? ""))) {
    errors.push("architecture/backend-system.json: missing composition root");
  }
  const technical = manifest.technicalOwnership ?? {};
  const requiredInfrastructure = ["transactions", "idempotency", "eventDelivery", "migrationRunner", "durableWorker"];
  for (const field of requiredInfrastructure) {
    if (!manifest.infrastructure?.[field]) errors.push(`architecture/backend-system.json: missing infrastructure.${field}`);
  }
  for (const table of technical.tables ?? []) {
    if (!/^public\.[a-z_]+$/u.test(table)) errors.push(`architecture/backend-system.json: invalid technical table ${table}`);
  }
  const knownTechnicalTables = new Set(["public.launch_signoffs", "public.notification_outbox"]);
  for (const migrationPath of technical.migrations ?? []) {
    const sourcePath = join(root, migrationPath);
    if (!existsSync(sourcePath)) {
      errors.push(`architecture/backend-system.json: missing migration ${migrationPath}`);
      continue;
    }
    const source = readFileSync(sourcePath, "utf8");
    for (const table of knownTechnicalTables) {
      if (source.includes(table) && !technical.tables?.includes(table)) {
        errors.push(`architecture/backend-system.json: undeclared technical ownership ${table}`);
      }
    }
  }
  return manifest;
}

function validateSystemBindings(system, manifests, errors) {
  const backendByPublicEntryPoint = new Map(
    manifests
      .filter((manifest) => manifest.kind === "backend-capability")
      .map((manifest) => [manifest.publicEntryPoint, manifest]),
  );
  const knownPorts = new Set(
    manifests.flatMap((manifest) => manifest.ports?.map((port) => port.name) ?? []),
  );
  for (const workflow of system.workflows ?? []) {
    for (const publicPackage of workflow.publicPackages ?? []) {
      if (!backendByPublicEntryPoint.has(publicPackage)) {
        errors.push(`architecture/backend-system.json: workflow ${workflow.name} calls undeclared public package ${publicPackage}`);
      }
    }
  }
  for (const binding of system.adapterBindings ?? []) {
    if (!knownPorts.has(binding.port)) {
      errors.push(`architecture/backend-system.json: adapter binding has undeclared port ${binding.port}`);
    }
  }
}

export function validateCompatibilityRegistry(path) {
  const errors = [];
  const registry = readJson(path, errors);
  if (registry.schemaVersion !== "1.0" || !Array.isArray(registry.exceptions)) {
    errors.push(`${path}: invalid compatibility registry`);
    return errors;
  }
  for (const entry of registry.exceptions) {
    const prefix = `${entry.id ?? "compatibility exception"}:`;
    for (const field of ["id", "owner", "creationIssue", "removalIssue", "paths", "expiresAt", "removalCondition"]) {
      if (!(field in entry)) errors.push(`${prefix} missing ${field}`);
    }
    if (!String(entry.id).startsWith("compat-")) errors.push(`${prefix} id must start compat-`);
    if (!/^#[0-9]+$/u.test(entry.creationIssue ?? "")) errors.push(`${prefix} creationIssue must be an issue`);
    if (!/^#[0-9]+$/u.test(entry.removalIssue ?? "")) errors.push(`${prefix} removalIssue must be an issue`);
    if (!Array.isArray(entry.paths) || !entry.paths.length) errors.push(`${prefix} paths must be non-empty`);
    if (!RFC3339.test(entry.expiresAt ?? "")) errors.push(`${prefix} expiresAt must be RFC 3339`);
    if (!String(entry.removalCondition ?? "").trim()) errors.push(`${prefix} removalCondition must be non-empty`);
  }
  return errors;
}

function assertAcyclic(manifests, errors) {
  const graph = new Map(manifests.map((manifest) => [manifest.owner, []]));
  for (const manifest of manifests) {
    for (const dependency of manifest.dependencies) {
      const owner = `${manifest.kind === "web-feature" ? "web" : "backend"}:${dependency.module}`;
      if (!graph.has(owner)) errors.push(`${manifest.owner}: dependency has no manifest ${owner}`);
      else graph.get(manifest.owner).push(owner);
    }
  }
  const visiting = new Set();
  const visited = new Set();
  function visit(node) {
    if (visiting.has(node)) {
      errors.push(`circular module dependency: ${[...visiting, node].join(" -> ")}`);
      return;
    }
    if (visited.has(node)) return;
    visiting.add(node);
    for (const neighbor of graph.get(node) ?? []) visit(neighbor);
    visiting.delete(node);
    visited.add(node);
  }
  for (const node of graph.keys()) visit(node);
}

function checkRouteImports(root, manifests, errors) {
  const allowed = new Set(manifests.filter((manifest) => manifest.kind === "web-feature").map((manifest) => manifest.publicEntryPoint));
  for (const path of walk(join(root, "apps/web/app"), (candidate) => /\.[jt]sx?$/u.test(candidate))) {
    for (const specifier of importedSpecifiers(readFileSync(path, "utf8"))) {
      if (specifier.includes("/features/")) {
        const feature = specifier.match(/(?:^@\/features\/|features\/)([a-z][a-z0-9-]*)(?:\/|$)/u)?.[1];
        const expected = feature ? `@/features/${feature}` : undefined;
        const isDeepImport = feature
          && !specifier.endsWith(`features/${feature}`)
          && !specifier.endsWith(`features/${feature}/index.ts`)
          && specifier !== expected;
        if (!expected || !allowed.has(expected) || isDeepImport) {
          errors.push(`${relative(root, path)}: undeclared public feature entry point ${specifier}`);
        }
      }
    }
  }
}

export function checkArchitecture({ root, writeEvidence = false }) {
  const resolvedRoot = rootPath(root);
  const errors = [];
  for (const schema of ["module.schema.json", "backend-system.schema.json", "compatibility.schema.json"]) {
    readJson(join(resolvedRoot, "architecture", schema), errors);
  }
  const manifests = walk(join(resolvedRoot, "apps"), (path) => path.endsWith("/module.json"))
    .sort()
    .map((path) => validateModule(resolvedRoot, path, errors));
  for (const manifest of manifests) checkModuleImports(resolvedRoot, manifest, errors);
  checkRouteImports(resolvedRoot, manifests, errors);
  const backendSystem = validateSystemManifest(resolvedRoot, errors);
  validateSystemBindings(backendSystem, manifests, errors);
  errors.push(...validateCompatibilityRegistry(join(resolvedRoot, "architecture/compatibility.json")));
  const sharedKernel = readJson(join(resolvedRoot, "architecture/shared-kernel.json"), errors);
  if (!Array.isArray(sharedKernel.allowedPublicPackages) || !Array.isArray(sharedKernel.forbidden)) {
    errors.push("architecture/shared-kernel.json: missing minimal shared-kernel policy");
  }
  assertAcyclic(manifests, errors);
  const evidence = stable({
    schemaVersion: "1.0",
    generatedBy: "scripts/check-architecture.mjs",
    modules: manifests.map((manifest) => manifest.owner).sort(),
    edges: [
      ...manifests.flatMap((manifest) => manifest.dependencies.map((dependency) => ({
      from: manifest.owner,
      to: `${manifest.kind === "web-feature" ? "web" : "backend"}:${dependency.module}`,
      kind: dependency.kind,
      imports: [...dependency.imports].sort(),
      }))),
      ...(backendSystem.workflows ?? []).flatMap((workflow) =>
        (workflow.publicPackages ?? []).map((publicPackage) => ({
          from: `backend-system:${workflow.name}`,
          to: backendSystemEdgeTarget(manifests, publicPackage),
          kind: "workflow",
          imports: [publicPackage],
        })),
      ),
    ].sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right))),
    technicalOwnership: (backendSystem.technicalOwnership?.tables ?? [])
      .map((table) => ({ owner: "backend-system", table }))
      .sort((left, right) => left.table.localeCompare(right.table)),
  });
  if (writeEvidence && !errors.length) {
    writeFileSync(join(resolvedRoot, "architecture/dependency-evidence.json"), `${JSON.stringify(evidence, null, 2)}\n`);
  }
  return { errors, evidence };
}

function backendSystemEdgeTarget(manifests, publicPackage) {
  return manifests.find((manifest) => manifest.publicEntryPoint === publicPackage)?.owner
    ?? `undeclared:${publicPackage}`;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = checkArchitecture({ root: resolve(dirname(fileURLToPath(import.meta.url)), ".."), writeEvidence: process.argv.includes("--write-evidence") });
  if (result.errors.length) {
    for (const error of result.errors) console.error(`architecture: ${error}`);
    process.exitCode = 1;
  } else {
    console.log(JSON.stringify(result.evidence, null, 2));
  }
}
