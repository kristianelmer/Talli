import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join, relative, resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import ts from "typescript";

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
const PYTHON_IMPORTS_SCRIPT = fileURLToPath(new URL("./python-imports.py", import.meta.url));

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

function validateAgainstSchema(schema, value, label, errors) {
  if (!schema) return;
  const validate = new Ajv2020({ allErrors: true, logger: false, strict: false }).compile(schema);
  if (!validate(value)) {
    for (const error of validate.errors ?? []) {
      errors.push(`${label}: schema ${error.instancePath || "/"} ${error.message}`);
    }
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

function unwrappedExpression(expression) {
  let current = expression;
  while (
    ts.isParenthesizedExpression(current)
    || ts.isAsExpression(current)
    || ts.isNonNullExpression(current)
    || ts.isSatisfiesExpression(current)
    || ts.isTypeAssertionExpression(current)
    || ts.isAwaitExpression(current)
  ) {
    current = current.expression;
  }
  return current;
}

function propertyAccess(expression) {
  const unwrapped = unwrappedExpression(expression);
  if (ts.isPropertyAccessExpression(unwrapped)) {
    return { receiver: unwrappedExpression(unwrapped.expression), name: unwrapped.name.text };
  }
  if (ts.isElementAccessExpression(unwrapped)) {
    const argument = unwrapped.argumentExpression;
    if (ts.isStringLiteral(argument) || ts.isNoSubstitutionTemplateLiteral(argument)) {
      return { receiver: unwrappedExpression(unwrapped.expression), name: argument.text };
    }
  }
  return undefined;
}

function propertyName(node) {
  if (!node) return undefined;
  if (ts.isIdentifier(node) || ts.isStringLiteral(node) || ts.isNumericLiteral(node)) return node.text;
  return undefined;
}

const WEB_COMPILER_OPTIONS = {
    target: ts.ScriptTarget.Latest,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    moduleDetection: ts.ModuleDetectionKind.Force,
    jsx: ts.JsxEmit.ReactJSX,
    allowJs: true,
    checkJs: false,
    skipLibCheck: true,
};

function webScriptKind(path) {
  if (/\.[cm]?jsx$/u.test(path)) return ts.ScriptKind.JSX;
  if (/\.[cm]?js$/u.test(path)) return ts.ScriptKind.JS;
  return /\.[cm]?tsx$/u.test(path) ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
}

function createWebBoundaryAnalysis(root) {
  const files = walk(join(root, "apps/web"), (candidate) => /\.[cm]?[jt]sx?$/u.test(candidate));
  const sources = new Map(files.map((path) => [resolve(path), readFileSync(path, "utf8")]));
  const host = ts.createCompilerHost(WEB_COMPILER_OPTIONS);
  const defaultGetSourceFile = host.getSourceFile.bind(host);
  host.fileExists = (candidate) => sources.has(resolve(candidate)) || ts.sys.fileExists(candidate);
  host.readFile = (candidate) => sources.get(resolve(candidate)) ?? ts.sys.readFile(candidate);
  host.getSourceFile = (candidate, languageVersion, onError, shouldCreateNewSourceFile) => (
    sources.has(resolve(candidate))
      ? ts.createSourceFile(
        resolve(candidate),
        sources.get(resolve(candidate)),
        languageVersion,
        true,
        webScriptKind(candidate),
      )
      : defaultGetSourceFile(candidate, languageVersion, onError, shouldCreateNewSourceFile)
  );
  return {
    program: ts.createProgram([...sources.keys()], WEB_COMPILER_OPTIONS, host),
    results: new Map(),
  };
}

function webBoundaryViolations(source, path, analysis) {
  const resolvedPath = resolve(path);
  if (analysis.results.has(resolvedPath)) return analysis.results.get(resolvedPath);
  const program = analysis.program;
  const sourceFile = program.getSourceFile(resolvedPath);
  if (!sourceFile) throw new Error(`TypeScript program omitted architecture source ${resolvedPath}`);
  const checker = program.getTypeChecker();
  const factorySymbols = new Set();
  const namespaceSymbols = new Set();
  const persistenceSymbols = new Set();
  const persistencePropertySymbols = new Set();
  const platformObjectSymbols = new Set();
  const platformFetchSymbols = new Set();

  function add(set, value) {
    if (!value || set.has(value)) return false;
    set.add(value);
    return true;
  }

  function symbolAt(node) {
    return node ? checker.getSymbolAtLocation(node) : undefined;
  }

  function moduleSpecifierFor(node) {
    let current = node;
    while (current && !ts.isImportDeclaration(current)) current = current.parent;
    return current && ts.isStringLiteral(current.moduleSpecifier) ? current.moduleSpecifier.text : undefined;
  }

  function isSupabaseModule(specifier) {
    return specifier === "@supabase/supabase-js" || specifier === "@supabase/ssr";
  }

  function importedName(node) {
    return ts.isImportSpecifier(node) ? (node.propertyName?.text ?? node.name.text) : undefined;
  }

  function typeSignalsPersistence(type, seen = new Set()) {
    if (!type || seen.has(type)) return false;
    seen.add(type);
    if (ts.isParenthesizedTypeNode(type)) return typeSignalsPersistence(type.type, seen);
    if (ts.isUnionTypeNode(type) || ts.isIntersectionTypeNode(type)) {
      return type.types.some((member) => typeSignalsPersistence(member, seen));
    }
    if (ts.isTypeReferenceNode(type)) {
      const symbol = symbolAt(type.typeName);
      for (const declaration of symbol?.declarations ?? []) {
        if (ts.isImportSpecifier(declaration)
          && importedName(declaration) === "SupabaseClient"
          && isSupabaseModule(moduleSpecifierFor(declaration))) {
          return true;
        }
        if (ts.isTypeAliasDeclaration(declaration)
          && typeSignalsPersistence(declaration.type, seen)) {
          return true;
        }
      }
    }
    return false;
  }

  function isPlatformGlobal(identifier) {
    if (!ts.isIdentifier(identifier) || !["globalThis", "window"].includes(identifier.text)) return false;
    const symbol = symbolAt(identifier);
    return Boolean(symbol && (symbol.declarations ?? []).every((declaration) => declaration.getSourceFile().isDeclarationFile));
  }

  function platformObject(expression) {
    const unwrapped = unwrappedExpression(expression);
    return ts.isIdentifier(unwrapped)
      && (platformObjectSymbols.has(symbolAt(unwrapped)) || isPlatformGlobal(unwrapped));
  }

  function namespaceExpression(expression) {
    const unwrapped = unwrappedExpression(expression);
    return ts.isIdentifier(unwrapped) && namespaceSymbols.has(symbolAt(unwrapped));
  }

  function symbolIsFactory(symbol, seen = new Set()) {
    if (!symbol || seen.has(symbol)) return false;
    seen.add(symbol);
    if (factorySymbols.has(symbol)) return true;
    for (const declaration of symbol.declarations ?? []) {
      if (ts.isImportSpecifier(declaration)) {
        if (isSupabaseModule(moduleSpecifierFor(declaration))
          && ["createClient", "createServerClient"].includes(importedName(declaration))) {
          return true;
        }
        if (symbol.flags & ts.SymbolFlags.Alias) {
          const aliased = checker.getAliasedSymbol(symbol);
          if (aliased !== symbol && symbolIsFactory(aliased, seen)) return true;
        }
      }
      if (ts.isFunctionDeclaration(declaration) && declaration.body) {
        let returnsFactory = false;
        function inspectReturn(node) {
          if (ts.isReturnStatement(node) && node.expression && factoryCall(node.expression, seen)) {
            returnsFactory = true;
          }
          ts.forEachChild(node, inspectReturn);
        }
        inspectReturn(declaration.body);
        if (returnsFactory) return true;
      }
    }
    return false;
  }

  function directFactory(expression, seen = new Set()) {
    const unwrapped = unwrappedExpression(expression);
    if (ts.isIdentifier(unwrapped) && symbolIsFactory(symbolAt(unwrapped), seen)) return true;
    const access = propertyAccess(unwrapped);
    return Boolean(access && access.name === "createClient" && namespaceExpression(access.receiver));
  }

  function platformFetch(expression) {
    const unwrapped = unwrappedExpression(expression);
    if (ts.isIdentifier(unwrapped)) {
      const symbol = symbolAt(unwrapped);
      if (platformFetchSymbols.has(symbol)) return true;
      return unwrapped.text === "fetch"
        && Boolean(symbol)
        && (symbol.declarations ?? []).every((declaration) => declaration.getSourceFile().isDeclarationFile);
    }
    const access = propertyAccess(unwrapped);
    return Boolean(access && access.name === "fetch" && platformObject(access.receiver));
  }

  function factoryCall(expression, seen = new Set()) {
    const unwrapped = unwrappedExpression(expression);
    return ts.isCallExpression(unwrapped) && directFactory(unwrapped.expression, seen);
  }

  function persistenceExpression(expression) {
    if (!expression) return false;
    const unwrapped = unwrappedExpression(expression);
    if (factoryCall(unwrapped)) return true;
    if (ts.isIdentifier(unwrapped)) return persistenceSymbols.has(symbolAt(unwrapped));
    const access = propertyAccess(unwrapped);
    return Boolean(access && persistencePropertySymbols.has(symbolAt(
      ts.isPropertyAccessExpression(unwrapped) ? unwrapped.name : unwrapped.argumentExpression,
    )));
  }

  function bindingElementSource(element, initializer) {
    const property = propertyName(element.propertyName) ?? (ts.isIdentifier(element.name) ? element.name.text : undefined);
    return { property, initializer: unwrappedExpression(initializer) };
  }

  function collectEvidence(node) {
    let changed = false;
    if (ts.isImportDeclaration(node)
      && ts.isStringLiteral(node.moduleSpecifier)
      && isSupabaseModule(node.moduleSpecifier.text)) {
      const bindings = node.importClause?.namedBindings;
      if (bindings && ts.isNamespaceImport(bindings)) {
        changed = add(namespaceSymbols, symbolAt(bindings.name)) || changed;
      } else if (bindings && ts.isNamedImports(bindings)) {
        for (const element of bindings.elements) {
          if (importedName(element) === "createClient" || importedName(element) === "createServerClient") {
            changed = add(factorySymbols, symbolAt(element.name)) || changed;
          }
        }
      }
    }
    if ((ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node))
      && node.type && typeSignalsPersistence(node.type) && node.name) {
      changed = add(factorySymbols, symbolAt(node.name)) || changed;
    }
    if ((ts.isParameter(node) || ts.isVariableDeclaration(node))
      && ts.isIdentifier(node.name)
      && typeSignalsPersistence(node.type)) {
      changed = add(persistenceSymbols, symbolAt(node.name)) || changed;
    }
    if (ts.isPropertySignature(node) && typeSignalsPersistence(node.type)) {
      changed = add(persistencePropertySymbols, symbolAt(node.name)) || changed;
    }
    if (ts.isVariableDeclaration(node) && node.initializer) {
      if (ts.isIdentifier(node.name)) {
        const target = symbolAt(node.name);
        changed = add(factorySymbols, directFactory(node.initializer) ? target : undefined) || changed;
        changed = add(platformFetchSymbols, platformFetch(node.initializer) ? target : undefined) || changed;
        changed = add(platformObjectSymbols, platformObject(node.initializer) ? target : undefined) || changed;
        changed = add(namespaceSymbols, namespaceExpression(node.initializer) ? target : undefined) || changed;
        changed = add(persistenceSymbols, persistenceExpression(node.initializer) ? target : undefined) || changed;
      } else if (ts.isObjectBindingPattern(node.name)) {
        for (const element of node.name.elements) {
          if (!ts.isIdentifier(element.name)) continue;
          const binding = bindingElementSource(element, node.initializer);
          const target = symbolAt(element.name);
          if (binding.property === "createClient" && namespaceExpression(binding.initializer)) {
            changed = add(factorySymbols, target) || changed;
          }
          if (binding.property === "fetch" && platformObject(binding.initializer)) {
            changed = add(platformFetchSymbols, target) || changed;
          }
        }
      }
    }
    if (ts.isPropertyAssignment(node) && persistenceExpression(node.initializer)) {
      changed = add(persistencePropertySymbols, symbolAt(node.name)) || changed;
    }
    if (ts.isShorthandPropertyAssignment(node) && persistenceExpression(node.name)) {
      changed = add(persistencePropertySymbols, symbolAt(node.name)) || changed;
    }
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
      const left = unwrappedExpression(node.left);
      if (ts.isIdentifier(left)) {
        const target = symbolAt(left);
        changed = add(factorySymbols, directFactory(node.right) ? target : undefined) || changed;
        changed = add(platformFetchSymbols, platformFetch(node.right) ? target : undefined) || changed;
        changed = add(platformObjectSymbols, platformObject(node.right) ? target : undefined) || changed;
        changed = add(namespaceSymbols, namespaceExpression(node.right) ? target : undefined) || changed;
        changed = add(persistenceSymbols, persistenceExpression(node.right) ? target : undefined) || changed;
      } else {
        const access = propertyAccess(left);
        if (access && persistenceExpression(node.right)) {
          changed = add(persistencePropertySymbols, symbolAt(
            ts.isPropertyAccessExpression(left) ? left.name : left.argumentExpression,
          )) || changed;
        }
      }
    }
    ts.forEachChild(node, (child) => {
      changed = collectEvidence(child) || changed;
    });
    return changed;
  }

  let changed;
  do {
    changed = collectEvidence(sourceFile);
  } while (changed);

  let persistence = false;
  let fetch = false;
  function visit(node) {
    if (ts.isCallExpression(node)) {
      if (platformFetch(node.expression)) fetch = true;
      const access = propertyAccess(node.expression);
      if (access && ["from", "rpc"].includes(access.name)) {
        if (persistenceExpression(access.receiver)) persistence = true;
        const receiverAccess = propertyAccess(access.receiver);
        if (access.name === "from" && receiverAccess?.name === "storage"
          && persistenceExpression(receiverAccess.receiver)) {
          persistence = true;
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  const result = { fetch, persistence };
  analysis.results.set(resolvedPath, result);
  return result;
}

function generatedClientDeepImport(source, path) {
  const scriptKind = webScriptKind(path);
  const sourceFile = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, scriptKind);
  let violation = false;
  function forbidden(specifier) {
    return specifier.startsWith("@talli/talli-api-client/");
  }
  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node))
      && node.moduleSpecifier
      && ts.isStringLiteralLike(node.moduleSpecifier)
      && forbidden(node.moduleSpecifier.text)) {
      violation = true;
    }
    if (ts.isImportEqualsDeclaration(node)
      && ts.isExternalModuleReference(node.moduleReference)
      && node.moduleReference.expression
      && ts.isStringLiteralLike(node.moduleReference.expression)
      && forbidden(node.moduleReference.expression.text)) {
      violation = true;
    }
    if (ts.isCallExpression(node)
      && (node.expression.kind === ts.SyntaxKind.ImportKeyword
        || (ts.isIdentifier(node.expression) && node.expression.text === "require"))
      && node.arguments.length
      && ts.isStringLiteralLike(node.arguments[0])
      && forbidden(node.arguments[0].text)) {
      violation = true;
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return violation;
}

function pythonInspection(root, paths, errors) {
  if (!paths.length) return new Map();
  const result = spawnSync(
    "uv",
    ["run", "--project", join(root, "apps/backend"), "python", PYTHON_IMPORTS_SCRIPT],
    {
      cwd: root,
      encoding: "utf8",
      input: JSON.stringify({
        sourceRoot: join(root, "apps/backend/src"),
        files: paths.map((path) => ({ path, source: readFileSync(path, "utf8") })),
      }),
    },
  );
  if (result.error || result.status !== 0) {
    errors.push(`Python import inspection failed: ${result.error?.message ?? result.stderr.trim()}`);
    return new Map();
  }
  try {
    const parsed = JSON.parse(result.stdout);
    return new Map(parsed.files.map((file) => {
      if (file.error) errors.push(`${relative(root, file.path)}: Python import parse failed: ${file.error}`);
      return [file.path, file];
    }));
  } catch (error) {
    errors.push(`Python import inspection returned invalid output: ${error.message}`);
    return new Map();
  }
}

function pythonImports(root, paths, errors) {
  return new Map(
    [...pythonInspection(root, paths, errors)]
      .map(([path, inspection]) => [path, inspection.imports ?? []]),
  );
}

function normalizedCompositionDependency(specifier) {
  if (specifier.startsWith("talli_backend.")) return specifier;
  return specifier.split(".")[0];
}

function checkCompositionRoot(root, system, errors) {
  const sourcePath = join(root, system.compositionRoot);
  if (!existsSync(sourcePath)) return;
  const allowed = new Set(system.allowedDependencies?.transport ?? []);
  for (const specifier of pythonImports(root, [sourcePath], errors).get(sourcePath) ?? []) {
    if (specifier.startsWith("talli_backend.modules.") && !specifier.endsWith(".public")) {
      errors.push(`${system.compositionRoot}: private backend module dependency ${specifier}`);
      continue;
    }
    const dependency = normalizedCompositionDependency(specifier);
    if (!allowed.has(dependency)) {
      errors.push(`${system.compositionRoot}: undeclared composition-root dependency ${dependency}`);
    }
  }
}

function pythonSymbol(root, qualifiedName, errors) {
  const parts = qualifiedName.split(".");
  const symbolName = parts.pop();
  const modulePath = join(root, "apps/backend/src", ...parts) + ".py";
  if (!existsSync(modulePath)) return undefined;
  const inspection = pythonInspection(root, [modulePath], errors).get(modulePath);
  return inspection?.symbols?.find((symbol) => symbol.name === symbolName);
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
    tokens.push(...(manifest.publicImportPaths ?? []), ...(manifest.ownedRoutes ?? []), ...(manifest.apiOperations ?? []));
  } else {
    for (const values of Object.values(manifest.exports)) tokens.push(...values);
    tokens.push(...manifest.owns.tables, ...manifest.ports.map((port) => port.name));
  }
  return tokens;
}

function readDocumentationInventory(documentation, label, errors) {
  const inventory = {};
  const matches = [...documentation.matchAll(/<!--\s*architecture-inventory\s*([\s\S]*?)-->/gu)];
  if (!matches.length) {
    errors.push(`${label}: documentation is missing architecture inventory`);
    return inventory;
  }
  for (const match of matches) {
    try {
      const fragment = JSON.parse(match[1].trim());
      for (const [key, values] of Object.entries(fragment)) {
        if (!Array.isArray(values) || values.some((value) => typeof value !== "string")) {
          errors.push(`${label}: documentation inventory ${key} must be a string array`);
          continue;
        }
        inventory[key] = [...new Set([...(inventory[key] ?? []), ...values])].sort();
      }
    } catch (error) {
      errors.push(`${label}: invalid architecture inventory: ${error.message}`);
    }
  }
  return inventory;
}

function reconcileDocumentationInventory(documentation, label, expected, errors) {
  const actual = readDocumentationInventory(documentation, label, errors);
  for (const [key, expectedValues] of Object.entries(expected)) {
    const expectedSet = new Set(expectedValues);
    const actualValues = actual[key] ?? [];
    const missing = expectedValues.filter((value) => !actualValues.includes(value));
    const extra = actualValues.filter((value) => !expectedSet.has(value));
    if (missing.length) errors.push(`${label}: documentation inventory is missing ${key} ${missing.join(", ")}`);
    if (extra.length) errors.push(`${label}: documentation inventory has extra ${key} ${extra.join(", ")}`);
  }
  for (const key of Object.keys(actual)) {
    if (!(key in expected) && actual[key].length) {
      errors.push(`${label}: documentation inventory has extra material field ${key}`);
    }
  }
}

function moduleDocumentationInventory(manifest) {
  if (manifest.kind === "web-feature") {
    return {
      publicEntryPoints: [...manifest.publicImportPaths].sort(),
      routes: [...manifest.ownedRoutes].sort(),
      apiOperations: [...manifest.apiOperations].sort(),
      dependencies: manifest.dependencies.map((dependency) => `${dependency.kind}:${dependency.module}`).sort(),
    };
  }
  return {
    publicEntryPoints: [manifest.publicEntryPoint],
    ownedTables: [...manifest.owns.tables].sort(),
    ports: manifest.ports.map((port) => port.name).sort(),
    dependencies: manifest.dependencies.map((dependency) => `${dependency.kind}:${dependency.module}`).sort(),
  };
}

function backendSystemDocumentationInventory(manifest) {
  return {
    compositionRoots: [manifest.compositionRoot],
    workflows: (manifest.workflows ?? []).map((workflow) => workflow.name).sort(),
    workflowPurposes: (manifest.workflows ?? [])
      .map((workflow) => `${workflow.name}=>${workflow.purpose}`)
      .sort(),
    routes: (manifest.workflows ?? []).flatMap((workflow) => workflow.routes ?? []).sort(),
    publicPackages: (manifest.workflows ?? []).flatMap((workflow) => workflow.publicPackages ?? []).sort(),
    operationalOwners: manifest.operationalControlState?.owner ? [manifest.operationalControlState.owner] : [],
    operationalTables: [...(manifest.operationalControlState?.tables ?? [])].sort(),
    operationalReleaseDecisions: manifest.operationalControlState?.releaseDecision
      ? [manifest.operationalControlState.releaseDecision]
      : [],
    operationalAdapterRechecks: [String(manifest.operationalControlState?.consequentialAdapterRecheck)],
    technicalSchemas: [...(manifest.technicalOwnership?.schemas ?? [])].sort(),
    technicalTables: [...(manifest.technicalOwnership?.tables ?? [])].sort(),
    technicalMigrations: [...(manifest.technicalOwnership?.migrations ?? [])].sort(),
    technicalStatements: manifest.technicalOwnership?.statement ? [manifest.technicalOwnership.statement] : [],
    infrastructure: Object.entries(manifest.infrastructure ?? {})
      .map(([key, value]) => `${key}=>${value}`)
      .sort(),
    ports: (manifest.adapterBindings ?? []).map((binding) => binding.port).sort(),
    adapterBindings: (manifest.adapterBindings ?? [])
      .map((binding) => `${binding.port}=>${binding.adapter}`)
      .sort(),
    adapterBindingOwners: (manifest.adapterBindings ?? [])
      .map((binding) => `${binding.port}=>${binding.owner}`)
      .sort(),
    adapterBindingModes: (manifest.adapterBindings ?? [])
      .map((binding) => `${binding.port}=>${binding.mode}`)
      .sort(),
    transportDependencies: [...(manifest.allowedDependencies?.transport ?? [])].sort(),
    workflowDependencies: [...(manifest.allowedDependencies?.workflows ?? [])].sort(),
    adapterDependencies: [...(manifest.allowedDependencies?.adapters ?? [])].sort(),
  };
}

function validateModule(root, manifestPath, errors, schema) {
  const manifest = readJson(manifestPath, errors);
  const label = relative(root, manifestPath);
  validateAgainstSchema(schema, manifest, label, errors);
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
    reconcileDocumentationInventory(documentation, label, moduleDocumentationInventory(manifest), errors);
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
    } else {
      const publicSource = readFileSync(join(root, manifest.path, "public.py"), "utf8");
      const exported = new Set(
        [...publicSource.matchAll(/__all__\s*=\s*\[([^\]]*)\]/gu)]
          .flatMap((match) => [...match[1].matchAll(/["']([^"']+)["']/gu)].map((item) => item[1])),
      );
      for (const name of Object.values(manifest.exports ?? {}).flat()) {
        if (!exported.has(name)) errors.push(`${label}: declared public export ${name} missing from public package`);
      }
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
    for (const field of ["ownedRoutes", "apiOperations", "cachePolicy", "directBrowserFlows", "publicImportPaths"]) {
      if (!(field in manifest)) errors.push(`${label}: web manifest missing ${field}`);
    }
  }
  return manifest;
}

function checkModuleImports(root, manifest, errors, webAnalysis) {
  const label = `${manifest.owner} (${manifest.path})`;
  const allowedModuleImports = manifest.kind === "web-feature"
    ? declaredFeatureImports(manifest)
    : declaredBackendImports(manifest);
  const sourceFiles = moduleSourceFiles(root, manifest);
  const pythonImportMap = manifest.kind === "backend-capability"
    ? pythonImports(root, sourceFiles, errors)
    : new Map();
  for (const path of sourceFiles) {
    const source = readFileSync(path, "utf8");
    const specifiers = manifest.kind === "backend-capability"
      ? pythonImportMap.get(path) ?? []
      : importedSpecifiers(source);
    for (const specifier of specifiers) {
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
        const ownModule = `talli_backend.modules.${manifest.name}`;
        if (specifier === ownModule || specifier.startsWith(`${ownModule}.`)) continue;
        if (!allowedModuleImports.has(specifier)) errors.push(`${label}: forbidden backend deep import ${specifier}`);
        continue;
      }
      if (!manifest.allowedImports.includes(specifier) && !["typing"].includes(specifier)) {
        errors.push(`${label}: undeclared import ${specifier}`);
      }
    }
    if (manifest.kind === "web-feature") {
      const boundary = webBoundaryViolations(source, path, webAnalysis);
      if (boundary.fetch) errors.push(`${label}: direct business fetch is forbidden`);
      if (boundary.persistence) {
        errors.push(`${label}: direct web business persistence is forbidden`);
      }
      if (generatedClientDeepImport(source, path)) {
        errors.push(`${label}: generated-client deep import is forbidden`);
      }
    }
  }
}

function validateSystemManifest(root, errors, schema) {
  const path = join(root, "architecture/backend-system.json");
  const manifest = readJson(path, errors);
  validateAgainstSchema(schema, manifest, "architecture/backend-system.json", errors);
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
    reconcileDocumentationInventory(
      documentation,
      "architecture/backend-system.json",
      backendSystemDocumentationInventory(manifest),
      errors,
    );
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
  for (const migrationPath of technical.migrations ?? []) {
    const sourcePath = join(root, migrationPath);
    if (!existsSync(sourcePath)) {
      errors.push(`architecture/backend-system.json: missing migration ${migrationPath}`);
      continue;
    }
  }
  return manifest;
}

function discoverMigrationTables(root) {
  const tables = new Set();
  for (const path of walk(join(root, "supabase/migrations"), (candidate) => candidate.endsWith(".sql"))) {
    const source = readFileSync(path, "utf8");
    for (const match of source.matchAll(/create\s+table\s+(?:if\s+not\s+exists\s+)?(public\.[a-z_]+)/giu)) {
      tables.add(match[1].toLowerCase());
    }
  }
  return [...tables].sort();
}

function validateDatabaseCatalog(root, backendSystem, errors, schema) {
  const catalog = readJson(join(root, "architecture/database-catalog.json"), errors);
  validateAgainstSchema(schema, catalog, "architecture/database-catalog.json", errors);
  const discovered = new Set(discoverMigrationTables(root));
  const catalogEntries = catalog.tables ?? [];
  const catalogNames = new Set(catalogEntries.map((entry) => entry.name));
  if (catalogNames.size !== catalogEntries.length) errors.push("architecture/database-catalog.json: duplicate table name");
  for (const table of discovered) {
    if (!catalogNames.has(table)) errors.push(`architecture/database-catalog.json: migration table missing from catalog ${table}`);
  }
  for (const table of catalogNames) {
    if (!discovered.has(table)) errors.push(`architecture/database-catalog.json: catalog table missing from migrations ${table}`);
  }
  const declaredTechnical = new Set(backendSystem.technicalOwnership?.tables ?? []);
  const catalogTechnical = new Set(catalogEntries.filter((entry) => entry.kind === "technical").map((entry) => entry.name));
  for (const table of catalogTechnical) {
    if (!declaredTechnical.has(table)) errors.push(`architecture/backend-system.json: undeclared technical ownership ${table}`);
  }
  for (const table of declaredTechnical) {
    if (!catalogTechnical.has(table)) errors.push(`architecture/backend-system.json: technical ownership is not catalogued ${table}`);
  }
  return catalog;
}

function validateSystemBindings(root, system, manifests, errors) {
  const backendByPublicEntryPoint = new Map(
    manifests
      .filter((manifest) => manifest.kind === "backend-capability")
      .map((manifest) => [manifest.publicEntryPoint, manifest]),
  );
  const knownPorts = new Map(
    manifests.flatMap((manifest) => (manifest.ports ?? []).map((port) => [port.name, port])),
  );
  for (const workflow of system.workflows ?? []) {
    for (const publicPackage of workflow.publicPackages ?? []) {
      if (!backendByPublicEntryPoint.has(publicPackage)) {
        errors.push(`architecture/backend-system.json: workflow ${workflow.name} calls undeclared public package ${publicPackage}`);
      }
    }
  }
  for (const binding of system.adapterBindings ?? []) {
    const port = knownPorts.get(binding.port);
    if (!port) {
      errors.push(`architecture/backend-system.json: adapter binding has undeclared port ${binding.port}`);
      continue;
    }
    if (!port.adapters.includes(binding.adapter)) {
      errors.push(`architecture/backend-system.json: adapter binding does not match declared port adapter ${binding.port}`);
    }
    const adapter = pythonSymbol(root, binding.adapter, errors);
    if (!adapter) {
      errors.push(`architecture/backend-system.json: adapter symbol does not exist ${binding.adapter}`);
      continue;
    }
    const contract = port.contract ? pythonSymbol(root, port.contract, errors) : undefined;
    if (!contract || contract.kind !== "class" || !contract.bases?.includes("Protocol")) {
      errors.push(`architecture/backend-system.json: port contract is not a Protocol ${port.contract ?? binding.port}`);
    }
    const registration = port.registrationDecorator
      ? pythonSymbol(root, port.registrationDecorator, errors)
      : undefined;
    if (!registration || registration.kind !== "function") {
      errors.push(`architecture/backend-system.json: port registration decorator does not exist ${port.registrationDecorator ?? binding.port}`);
    }
    const decoratorName = port.registrationDecorator?.split(".").at(-1);
    const contractName = port.contract?.split(".").at(-1);
    const expectedDecorator = `${decoratorName}(${contractName})`;
    if (!decoratorName || !contractName || !adapter.decorators?.includes(expectedDecorator)) {
      errors.push(`architecture/backend-system.json: adapter is not registered for port ${binding.port}`);
    }
  }
}

export function validateCompatibilityRegistry(path, { now = new Date(), schema } = {}) {
  const errors = [];
  const registry = readJson(path, errors);
  validateAgainstSchema(schema, registry, path, errors);
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
    else if (new Date(entry.expiresAt).getTime() <= now.getTime()) errors.push(`${prefix} expiresAt must be strictly in the future`);
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
  const allowed = new Map(
    manifests
      .filter((manifest) => manifest.kind === "web-feature")
      .map((manifest) => [manifest.name, new Set(manifest.publicImportPaths)]),
  );
  for (const path of walk(join(root, "apps/web/app"), (candidate) => /\.[jt]sx?$/u.test(candidate))) {
    for (const specifier of importedSpecifiers(readFileSync(path, "utf8"))) {
      if (specifier.includes("/features/")) {
        const feature = specifier.match(/(?:^@\/features\/|features\/)([a-z][a-z0-9-]*)(?:\/|$)/u)?.[1];
        const declared = feature ? allowed.get(feature) : undefined;
        const normalized = specifier.startsWith("@/")
          ? specifier
          : relative(root, resolve(dirname(path), specifier));
        if (!declared || !declared.has(normalized)) {
          errors.push(`${relative(root, path)}: undeclared public feature entry point ${specifier}`);
        }
      }
    }
  }
}

function hasActiveCompatibility(registry, path, rule, now) {
  return (registry.exceptions ?? []).some((entry) => (
    entry.paths?.includes(path)
    && entry.rules?.includes(rule)
    && RFC3339.test(entry.expiresAt ?? "")
    && new Date(entry.expiresAt).getTime() > now.getTime()
  ));
}

function checkGlobalWebBoundary(root, registry, errors, now, webAnalysis) {
  for (const path of walk(join(root, "apps/web"), (candidate) => /\.[cm]?[jt]sx?$/u.test(candidate))) {
    const scopedPath = relative(root, path);
    const source = readFileSync(path, "utf8");
    const boundary = webBoundaryViolations(source, path, webAnalysis);
    if (boundary.fetch
      && !hasActiveCompatibility(registry, scopedPath, "direct-business-fetch", now)) {
      errors.push(`${scopedPath}: direct business fetch is forbidden`);
    }
    if (boundary.persistence
      && !hasActiveCompatibility(registry, scopedPath, "direct-web-business-persistence", now)) {
      errors.push(`${scopedPath}: direct web business persistence is forbidden`);
    }
    if (generatedClientDeepImport(source, path)
      && !hasActiveCompatibility(registry, scopedPath, "generated-client-deep-import", now)) {
      errors.push(`${scopedPath}: generated-client deep import is forbidden`);
    }
  }
}

function checkSharedKernel(root, sharedKernel, errors) {
  const allowed = new Set([
    ...(sharedKernel.allowedPublicPackages ?? []),
    ...(sharedKernel.allowedPrimitives ?? []),
  ]);
  const forbiddenPrefixes = sharedKernel.forbiddenImportPrefixes ?? [];
  const files = [];
  for (const sourceScope of sharedKernel.sourceScopes ?? []) {
    const scope = join(root, sourceScope);
    if (!existsSync(scope)) {
      errors.push(`architecture/shared-kernel.json: source scope does not exist ${sourceScope}`);
      continue;
    }
    files.push(...walk(scope, (candidate) => candidate.endsWith(".py")));
  }
  const importsByFile = pythonImports(root, files, errors);
  for (const path of files) {
    for (const specifier of importsByFile.get(path) ?? []) {
        if (!specifier.startsWith("talli_backend.shared.")) continue;
        if (forbiddenPrefixes.some((prefix) => specifier === prefix || specifier.startsWith(`${prefix}.`))) {
          errors.push(`${relative(root, path)}: forbidden shared-kernel import ${specifier}`);
        } else if (!allowed.has(specifier)) {
          errors.push(`${relative(root, path)}: undeclared shared-kernel import ${specifier}`);
        }
    }
  }
}

export function checkArchitecture({ root, writeEvidence = false, now = new Date() }) {
  const resolvedRoot = rootPath(root);
  const errors = [];
  const webAnalysis = createWebBoundaryAnalysis(resolvedRoot);
  const schemas = Object.fromEntries([
    ["module", "module.schema.json"],
    ["backendSystem", "backend-system.schema.json"],
    ["compatibility", "compatibility.schema.json"],
    ["sharedKernel", "shared-kernel.schema.json"],
    ["databaseCatalog", "database-catalog.schema.json"],
    ["evidence", "dependency-evidence.schema.json"],
  ].map(([name, file]) => [name, readJson(join(resolvedRoot, "architecture", file), errors)]));
  const manifests = walk(join(resolvedRoot, "apps"), (path) => path.endsWith("/module.json"))
    .sort()
    .map((path) => validateModule(resolvedRoot, path, errors, schemas.module));
  for (const manifest of manifests) checkModuleImports(resolvedRoot, manifest, errors, webAnalysis);
  checkRouteImports(resolvedRoot, manifests, errors);
  const backendSystem = validateSystemManifest(resolvedRoot, errors, schemas.backendSystem);
  validateSystemBindings(resolvedRoot, backendSystem, manifests, errors);
  checkCompositionRoot(resolvedRoot, backendSystem, errors);
  const compatibilityPath = join(resolvedRoot, "architecture/compatibility.json");
  const compatibility = readJson(compatibilityPath, []);
  errors.push(...validateCompatibilityRegistry(compatibilityPath, { now, schema: schemas.compatibility }));
  checkGlobalWebBoundary(resolvedRoot, compatibility, errors, now, webAnalysis);
  const sharedKernel = readJson(join(resolvedRoot, "architecture/shared-kernel.json"), errors);
  validateAgainstSchema(schemas.sharedKernel, sharedKernel, "architecture/shared-kernel.json", errors);
  if (!Array.isArray(sharedKernel.allowedPublicPackages) || !Array.isArray(sharedKernel.forbidden)) {
    errors.push("architecture/shared-kernel.json: missing minimal shared-kernel policy");
  }
  checkSharedKernel(resolvedRoot, sharedKernel, errors);
  validateDatabaseCatalog(resolvedRoot, backendSystem, errors, schemas.databaseCatalog);
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
  validateAgainstSchema(schemas.evidence, evidence, "architecture/dependency-evidence.json", errors);
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
