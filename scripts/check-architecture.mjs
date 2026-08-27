import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
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
const RFC3339 = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-](\d{2}):(\d{2}))$/u;
const PYTHON_IMPORTS_SCRIPT = fileURLToPath(new URL("./python-imports.py", import.meta.url));
const CHECKER_REPOSITORY_ROOT = resolve(dirname(PYTHON_IMPORTS_SCRIPT), "..");
const FROZEN_LEGACY_SOURCE_REVISION = "d331ee2717d1eeacef0d81db42b9d4fb5848b408";
const SUPPRESSIBLE_COMPATIBILITY_RULES = new Set([
  "direct-web-business-persistence",
  "direct-business-fetch",
  "generated-client-deep-import",
]);
const COMPLETE_GATE_CHECKS = new Set([
  "credential-scan",
  "typecheck",
  "architecture",
  "boundary",
  "build-web",
  "build-backend",
  "boundary-smoke",
  "launch-rehearsal",
  "production-dependency-audit",
  "database-isolation",
  "whitespace",
]);

function isBackendModule(manifest) {
  return ["backend-capability", "backend-technical-module"].includes(manifest.kind);
}

function rfc3339Timestamp(value) {
  const match = String(value ?? "").match(RFC3339);
  if (!match) return undefined;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, zone, zoneHourText, zoneMinuteText] = match;
  const [year, month, day, hour, minute, second] = [
    yearText,
    monthText,
    dayText,
    hourText,
    minuteText,
    secondText,
  ].map(Number);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth[month - 1]
    || hour > 23 || minute > 59 || second > 59) {
    return undefined;
  }
  if (zone !== "Z" && (Number(zoneHourText) > 23 || Number(zoneMinuteText) > 59)) {
    return undefined;
  }
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : undefined;
}

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

function readGitJson(root, revision, path, errors) {
  if (!/^[a-f0-9]{40}$/u.test(revision ?? "")) {
    errors.push(`${path}: frozen source revision is invalid`);
    return undefined;
  }
  const result = spawnSync("git", ["-C", root, "show", `${revision}:${path}`], {
    encoding: "utf8",
  });
  if (result.status !== 0) {
    errors.push(`${path}: frozen source revision ${revision} is not readable`);
    return undefined;
  }
  try {
    return JSON.parse(result.stdout);
  } catch (error) {
    errors.push(`${path}: frozen source registry is invalid JSON (${error.message})`);
    return undefined;
  }
}

function isReachableGitRevision(root, revision) {
  return spawnSync("git", ["-C", root, "merge-base", "--is-ancestor", revision, "HEAD"]).status === 0;
}

function isCommittedUnmodified(root, path) {
  return spawnSync("git", ["-C", root, "ls-files", "--error-unmatch", path]).status === 0
    && spawnSync("git", ["-C", root, "diff", "--quiet", "HEAD", "--", path]).status === 0;
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
  const extension = isBackendModule(manifest) ? /\.py$/u : /\.[cm]?[jt]sx?$/u;
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

function functionLikeName(node) {
  const ownName = node.name
    && (ts.isIdentifier(node.name) || ts.isStringLiteralLike(node.name))
    ? node.name.text
    : undefined;
  if (ts.isMethodDeclaration(node) && ownName && ts.isClassLike(node.parent) && node.parent.name) {
    return `${node.parent.name.text}.${ownName}`;
  }
  if (ts.isMethodDeclaration(node) && ownName && ts.isObjectLiteralExpression(node.parent)) {
    const declaration = node.parent.parent;
    if (ts.isVariableDeclaration(declaration) && ts.isIdentifier(declaration.name)) {
      return `${declaration.name.text}.${ownName}`;
    }
    return undefined;
  }
  if (ownName) return ownName;
  if ((ts.isArrowFunction(node) || ts.isFunctionExpression(node))
    && ts.isVariableDeclaration(node.parent)
    && ts.isIdentifier(node.parent.name)) {
    return node.parent.name.text;
  }
  if ((ts.isArrowFunction(node) || ts.isFunctionExpression(node))
    && ts.isPropertyAssignment(node.parent)
    && (ts.isIdentifier(node.parent.name) || ts.isStringLiteralLike(node.parent.name))) {
    const property = node.parent.name.text;
    const declaration = node.parent.parent.parent;
    return ts.isVariableDeclaration(declaration) && ts.isIdentifier(declaration.name)
      ? `${declaration.name.text}.${property}`
      : undefined;
  }
  if ((ts.isFunctionDeclaration(node) || ts.isArrowFunction(node) || ts.isFunctionExpression(node))
    && ts.isExportAssignment(node.parent)) {
    return "default";
  }
  if (ts.isFunctionDeclaration(node)
    && node.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.DefaultKeyword)) {
    return "default";
  }
  return undefined;
}

function legacyOperationAnalysis(source, path, operationName) {
  if (typeof source !== "string") return undefined;
  const sourceFile = ts.createSourceFile(
    path,
    source,
    ts.ScriptTarget.Latest,
    true,
    webScriptKind(path),
  );
  const matches = [];
  const stringConstants = new Map();
  function findOperation(node) {
    if (ts.isFunctionLike(node) && functionLikeName(node) === operationName) matches.push(node);
    if (ts.isVariableDeclaration(node)
      && ts.isIdentifier(node.name)
      && node.initializer
      && ts.isStringLiteralLike(node.initializer)) {
      stringConstants.set(node.name.text, node.initializer.text);
    }
    ts.forEachChild(node, findOperation);
  }
  findOperation(sourceFile);
  if (matches.length === 0) {
    return { state: "missing", resourceOccurrences: new Map(), persistenceOccurrences: new Map() };
  }
  if (matches.length !== 1) {
    return { state: "ambiguous", resourceOccurrences: new Map(), persistenceOccurrences: new Map() };
  }
  const operation = matches[0];
  const resourceOccurrences = new Map();
  const persistenceOccurrences = new Map();
  function countResource(node) {
    if (ts.isCallExpression(node)
      && (ts.isPropertyAccessExpression(node.expression)
        || ts.isElementAccessExpression(node.expression))) {
      const access = node.expression;
      const name = ts.isPropertyAccessExpression(access)
        ? access.name.text
        : ts.isStringLiteralLike(access.argumentExpression)
          ? access.argumentExpression.text
          : undefined;
      const argument = node.arguments[0];
      if (["from", "rpc"].includes(name)
        && argument
        && (ts.isStringLiteralLike(argument) || ts.isIdentifier(argument))) {
        const resourceName = ts.isStringLiteralLike(argument)
          ? argument.text
          : stringConstants.get(argument.text);
        const receiver = access.expression;
        const storage = name === "from"
          && ts.isPropertyAccessExpression(receiver)
          && receiver.name.text === "storage";
        const resourceKind = storage ? "storage" : name === "rpc" ? "rpc" : "table";
        const resource = resourceName === undefined
          ? `${resourceKind}:*`
          : `${resourceKind}:${resourceName}`;
        resourceOccurrences.set(resource, (resourceOccurrences.get(resource) ?? 0) + 1);
        const standardLibraryFrom = name === "from"
          && ts.isIdentifier(receiver)
          && ["Array", "Buffer"].includes(receiver.text);
        if (!standardLibraryFrom) {
          persistenceOccurrences.set(
            resource,
            (persistenceOccurrences.get(resource) ?? 0) + 1,
          );
        }
      }
    }
    ts.forEachChild(node, countResource);
  }
  countResource(operation);
  return {
    state: "found",
    sourceDigest: `sha256:${createHash("sha256").update(operation.getText(sourceFile)).digest("hex")}`,
    resourceOccurrences,
    persistenceOccurrences,
  };
}

function legacyScopeProof(analysis, scope) {
  if (analysis?.state !== "found") return undefined;
  const resourceKind = scope.resource.split(":", 1)[0];
  return {
    sourceDigest: analysis.sourceDigest,
    occurrences: (analysis.resourceOccurrences.get(scope.resource) ?? 0)
      + (analysis.resourceOccurrences.get(`${resourceKind}:*`) ?? 0),
  };
}

export function legacyOperationProof(source, path, scope) {
  return legacyScopeProof(legacyOperationAnalysis(source, path, scope.operation), scope);
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

  function symbolIsSupabaseNamespace(symbol) {
    if (!symbol) return false;
    if (namespaceSymbols.has(symbol)) return true;
    return (symbol.declarations ?? []).some((declaration) => (
      ts.isNamespaceImport(declaration)
      && isSupabaseModule(moduleSpecifierFor(declaration))
    ));
  }

  function typeSignalsPersistence(type, seen = new Set()) {
    if (!type || seen.has(type)) return false;
    seen.add(type);
    if (ts.isParenthesizedTypeNode(type)) return typeSignalsPersistence(type.type, seen);
    if (ts.isUnionTypeNode(type) || ts.isIntersectionTypeNode(type)) {
      return type.types.some((member) => typeSignalsPersistence(member, seen));
    }
    if (ts.isTypeReferenceNode(type)) {
      if (ts.isQualifiedName(type.typeName)
        && type.typeName.right.text === "SupabaseClient"
        && symbolIsSupabaseNamespace(symbolAt(type.typeName.left))) {
        return true;
      }
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
    if (symbol.flags & ts.SymbolFlags.Alias) {
      const aliased = checker.getAliasedSymbol(symbol);
      if (aliased !== symbol && symbolIsFactory(aliased, seen)) return true;
    }
    for (const declaration of symbol.declarations ?? []) {
      if (ts.isImportSpecifier(declaration)) {
        if (isSupabaseModule(moduleSpecifierFor(declaration))
          && ["createClient", "createServerClient"].includes(importedName(declaration))) {
          return true;
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

  function symbolIsPlatformFetch(symbol, seen = new Set()) {
    if (!symbol || seen.has(symbol)) return false;
    seen.add(symbol);
    if (platformFetchSymbols.has(symbol)) return true;
    if (symbol.flags & ts.SymbolFlags.Alias) {
      const aliased = checker.getAliasedSymbol(symbol);
      if (aliased !== symbol && symbolIsPlatformFetch(aliased, seen)) return true;
    }
    return (symbol.declarations ?? []).some((declaration) => (
      ts.isVariableDeclaration(declaration)
      && Boolean(declaration.initializer)
      && platformFetch(declaration.initializer, seen)
    ));
  }

  function platformFetch(expression, seen = new Set()) {
    const unwrapped = unwrappedExpression(expression);
    if (ts.isIdentifier(unwrapped)) {
      const symbol = symbolAt(unwrapped);
      if (symbolIsPlatformFetch(symbol, seen)) return true;
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

  function symbolCarriesPersistence(symbol, seen = new Set()) {
    if (!symbol || seen.has(symbol)) return false;
    seen.add(symbol);
    if (persistenceSymbols.has(symbol)) return true;
    if (symbol.flags & ts.SymbolFlags.Alias) {
      const aliased = checker.getAliasedSymbol(symbol);
      if (aliased !== symbol && symbolCarriesPersistence(aliased, seen)) return true;
    }
    return (symbol.declarations ?? []).some((declaration) => {
      if ((ts.isVariableDeclaration(declaration) || ts.isParameter(declaration))
        && typeSignalsPersistence(declaration.type)) {
        return true;
      }
      return ts.isVariableDeclaration(declaration)
        && Boolean(declaration.initializer)
        && persistenceExpression(declaration.initializer, seen);
    });
  }

  function persistenceExpression(expression, seen = new Set()) {
    if (!expression) return false;
    const unwrapped = unwrappedExpression(expression);
    if (factoryCall(unwrapped, seen)) return true;
    if (ts.isIdentifier(unwrapped)) return symbolCarriesPersistence(symbolAt(unwrapped), seen);
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
    if ((ts.isPropertySignature(node) || ts.isPropertyDeclaration(node))
      && typeSignalsPersistence(node.type)) {
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
      } else if (ts.isObjectLiteralExpression(left)) {
        for (const property of left.properties) {
          if (!ts.isPropertyAssignment(property)
            || !ts.isIdentifier(unwrappedExpression(property.initializer))) continue;
          const target = symbolAt(unwrappedExpression(property.initializer));
          const name = propertyName(property.name);
          if (name === "createClient" && namespaceExpression(node.right)) {
            changed = add(factorySymbols, target) || changed;
          }
          if (name === "fetch" && platformObject(node.right)) {
            changed = add(platformFetchSymbols, target) || changed;
          }
        }
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

  function literalString(expression, seen = new Set()) {
    const unwrapped = unwrappedExpression(expression);
    if (ts.isStringLiteralLike(unwrapped)) return unwrapped.text;
    if (!ts.isIdentifier(unwrapped)) return undefined;
    let symbol = symbolAt(unwrapped);
    if (!symbol || seen.has(symbol)) return undefined;
    seen.add(symbol);
    if (symbol.flags & ts.SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol);
    for (const declaration of symbol.declarations ?? []) {
      if (ts.isVariableDeclaration(declaration) && declaration.initializer) {
        const value = literalString(declaration.initializer, seen);
        if (value !== undefined) return value;
      }
    }
    return undefined;
  }

  function enclosingOperation(node) {
    let operation;
    for (let current = node.parent; current; current = current.parent) {
      if (!ts.isFunctionLike(current)) continue;
      const name = functionLikeName(current);
      if (name) operation = name;
    }
    return operation;
  }

  function addFinding(findings, resource, node) {
    const operation = enclosingOperation(node) ?? "<unscoped>";
    findings.set(`${resource}\u0000${operation}\u0000${node.pos}`, { resource, operation });
  }

  const persistence = new Map();
  const fetch = new Map();
  function visit(node) {
    if (ts.isCallExpression(node)) {
      if (platformFetch(node.expression)) {
        addFinding(fetch, `url:${literalString(node.arguments[0]) ?? "<dynamic>"}`, node);
      }
      const access = propertyAccess(node.expression);
      if (access && ["from", "rpc"].includes(access.name)) {
        const receiverAccess = propertyAccess(access.receiver);
        const resourceName = literalString(node.arguments[0]) ?? "<dynamic>";
        if (access.name === "from" && receiverAccess?.name === "storage"
          && persistenceExpression(receiverAccess.receiver)) {
          addFinding(persistence, `storage:${resourceName}`, node);
        } else if (persistenceExpression(access.receiver)) {
          addFinding(
            persistence,
            `${access.name === "rpc" ? "rpc" : "table"}:${resourceName}`,
            node,
          );
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

function generatedClientDeepImport(source, path, analysis) {
  const scriptKind = webScriptKind(path);
  const resolvedPath = resolve(path);
  const sourceFile = analysis?.program.getSourceFile(resolvedPath)
    ?? ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, scriptKind);
  const checker = analysis?.program.getTypeChecker();
  const requireLoaderSymbols = new Set();
  let violation = false;
  function forbidden(specifier) {
    return specifier.startsWith("@talli/talli-api-client/");
  }
  function symbolAt(node) {
    return checker?.getSymbolAtLocation(node);
  }
  function requireLoader(expression) {
    const unwrapped = unwrappedExpression(expression);
    if (!ts.isIdentifier(unwrapped)) return false;
    const symbol = symbolAt(unwrapped);
    if (requireLoaderSymbols.has(symbol)) return true;
    return unwrapped.text === "require"
      && (!symbol || (symbol.declarations ?? [])
        .every((declaration) => declaration.getSourceFile().isDeclarationFile));
  }
  function collectRequireAliases(node) {
    let changed = false;
    if (ts.isVariableDeclaration(node)
      && ts.isIdentifier(node.name)
      && node.initializer
      && requireLoader(node.initializer)) {
      const symbol = symbolAt(node.name);
      if (symbol && !requireLoaderSymbols.has(symbol)) {
        requireLoaderSymbols.add(symbol);
        changed = true;
      }
    }
    if (ts.isBinaryExpression(node)
      && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
      && ts.isIdentifier(unwrappedExpression(node.left))
      && requireLoader(node.right)) {
      const symbol = symbolAt(unwrappedExpression(node.left));
      if (symbol && !requireLoaderSymbols.has(symbol)) {
        requireLoaderSymbols.add(symbol);
        changed = true;
      }
    }
    ts.forEachChild(node, (child) => {
      changed = collectRequireAliases(child) || changed;
    });
    return changed;
  }
  let changed;
  do {
    changed = collectRequireAliases(sourceFile);
  } while (changed);

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
      && (node.expression.kind === ts.SyntaxKind.ImportKeyword || requireLoader(node.expression))
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
  if (!["backend-capability", "backend-technical-module", "web-feature"].includes(manifest.kind)) {
    errors.push(`${label}: unsupported kind`);
    return manifest;
  }
  if (!Array.isArray(manifest.forbiddenResponsibilities) || !manifest.forbiddenResponsibilities.length) {
    errors.push(`${label}: forbiddenResponsibilities must be a non-empty array`);
  }
  if (!Array.isArray(manifest.dependencies) || !Array.isArray(manifest.allowedImports)) {
    errors.push(`${label}: dependencies and allowedImports must be arrays`);
  }
  const testPathCategories = new Map();
  for (const [category, testPath] of Object.entries(manifest.tests ?? {})) {
    const categories = testPathCategories.get(testPath) ?? [];
    categories.push(category);
    testPathCategories.set(testPath, categories);
  }
  for (const [testPath, categories] of testPathCategories) {
    if (categories.length > 1) {
      errors.push(
        `${label}: test path ${testPath} has multiple ownership categories ${categories.sort().join(", ")}`,
      );
    }
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

  if (isBackendModule(manifest)) {
    if (!manifest.path.match(/^apps\/backend\/src\/talli_backend\/modules\/[a-z][a-z0-9_]*$/u)) {
      errors.push(`${label}: backend path must be a module directory`);
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
      const declaredExports = new Set(Object.values(manifest.exports ?? {}).flat());
      for (const name of exported) {
        if (name.endsWith("Request") && !declaredExports.has(name)) {
          errors.push(`${label}: public request export ${name} missing from module manifest`);
        }
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
  const pythonImportMap = isBackendModule(manifest)
    ? pythonImports(root, sourceFiles, errors)
    : new Map();
  for (const path of sourceFiles) {
    const source = readFileSync(path, "utf8");
    const specifiers = isBackendModule(manifest)
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
      if (isBackendModule(manifest) && specifier.startsWith("talli_backend.modules.")) {
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
      if (boundary.fetch.size) errors.push(`${label}: direct business fetch is forbidden`);
      if (boundary.persistence.size) {
        errors.push(`${label}: direct web business persistence is forbidden`);
      }
      if (generatedClientDeepImport(source, path, webAnalysis)) {
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
  } else {
    const compositionSource = readFileSync(join(root, manifest.compositionRoot), "utf8");
    const declaredRoutes = new Set(
      (manifest.workflows ?? []).flatMap((workflow) => workflow.routes ?? []),
    );
    for (const match of compositionSource.matchAll(
      /@application\.(?:get|post|patch|delete)\(\s*["']([^"']+)["']/gu,
    )) {
      const route = match[1];
      if (route.startsWith("/api/v1/") && route !== "/api/v1/openapi.json" && !declaredRoutes.has(route)) {
        errors.push(`architecture/backend-system.json: composition route ${route} missing from backend-system.json`);
      }
    }
  }
  const technical = manifest.technicalOwnership ?? {};
  const requiredInfrastructure = ["transactions", "idempotency", "eventDelivery", "migrationRunner", "durableWorker"];
  for (const field of requiredInfrastructure) {
    if (!manifest.infrastructure?.[field]) errors.push(`architecture/backend-system.json: missing infrastructure.${field}`);
  }
  for (const table of technical.tables ?? []) {
    if (!/^[a-z][a-z0-9_]*\.[a-z_]+$/u.test(table)) errors.push(`architecture/backend-system.json: invalid technical table ${table}`);
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
    const statements = source.matchAll(
      /create\s+table\s+(?:if\s+not\s+exists\s+)?([a-z][a-z0-9_]*\.[a-z_]+)|alter\s+table\s+(?:if\s+exists\s+)?([a-z][a-z0-9_]*\.[a-z_]+)\s+set\s+schema\s+([a-z][a-z0-9_]*)|alter\s+table\s+(?:if\s+exists\s+)?([a-z][a-z0-9_]*\.[a-z_]+)\s+rename\s+to\s+([a-z_]+)/giu,
    );
    for (const match of statements) {
      if (match[1]) {
        tables.add(match[1].toLowerCase());
        continue;
      }
      if (match[2] && match[3]) {
        const previous = match[2].toLowerCase();
        if (tables.delete(previous)) {
          tables.add(`${match[3].toLowerCase()}.${previous.split(".")[1]}`);
        }
        continue;
      }
      if (match[4] && match[5]) {
        const previous = match[4].toLowerCase();
        if (tables.delete(previous)) {
          tables.add(`${previous.split(".")[0]}.${match[5].toLowerCase()}`);
        }
      }
    }
  }
  return [...tables].sort();
}

function stagedContractTableDrops(root, retirementIssues, errors) {
  const contractDirectory = join(root, "supabase/contract-migrations");
  if (!existsSync(contractDirectory)) return new Set();
  const retiredTables = new Set();
  for (const path of walk(contractDirectory, (candidate) => candidate.endsWith(".sql"))) {
    const source = readFileSync(path, "utf8");
    const artifactHeader = /^-- CONTRACT RELEASE ARTIFACT:[^\n]*#[0-9]+/mu.exec(source)?.[0];
    const artifactIssue = artifactHeader?.match(/#[0-9]+/u)?.[0];
    if (!retirementIssues.has(artifactIssue)) continue;
    for (const match of source.matchAll(
      /drop\s+table\s+if\s+exists\s+(public\.[a-z_]+)\s*;/giu,
    )) {
      const table = match[1].toLowerCase();
      const tableName = table.slice("public.".length);
      const beforeDrop = source.slice(0, match.index);
      const escapedTable = table.replace(".", "\\.");
      const hasFailClosedPreflight = new RegExp(
        `if\\s+pg_catalog\\.to_regclass\\('${escapedTable}'\\)\\s+is\\s+not\\s+null`
          + `\\s+and\\s+exists\\s*\\(\\s*select\\s+1\\s+from\\s+${escapedTable}\\s*\\)`
          + "\\s+then\\s+raise\\s+exception\\s+'[^']+'\\s*;\\s*end\\s+if\\s*;",
        "isu",
      ).test(beforeDrop);
      const rollbackPath = join(root, "supabase/rollback", relative(contractDirectory, path));
      const rollback = existsSync(rollbackPath) ? readFileSync(rollbackPath, "utf8") : "";
      const hasRollback = new RegExp(
        `create\\s+table\\s+if\\s+not\\s+exists\\s+public\\.${tableName}\\b`,
        "iu",
      ).test(rollback);
      const label = relative(root, path);
      if (!hasFailClosedPreflight) {
        errors.push(`${label}: staged table drop ${table} is missing a fail-closed empty-table preflight`);
      } else if (!hasRollback) {
        errors.push(`${label}: staged table drop ${table} has no matching rollback table restoration`);
      } else {
        retiredTables.add(table);
      }
    }
  }
  return retiredTables;
}

function validateDatabaseCatalog(root, backendSystem, manifests, compatibility, errors, schema) {
  const catalog = readJson(join(root, "architecture/database-catalog.json"), errors);
  validateAgainstSchema(schema, catalog, "architecture/database-catalog.json", errors);
  const retirementIssues = new Set([
    compatibility.migration?.currentIssue,
    ...(compatibility.migration?.completedStages ?? []).flatMap(
      (stage) => stage.removalIssues ?? [],
    ),
  ].filter(Boolean));
  const discovered = new Set(discoverMigrationTables(root));
  for (const retiredTable of stagedContractTableDrops(
    root,
    retirementIssues,
    errors,
  )) discovered.delete(retiredTable);
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
  const capabilityOwners = new Map();
  for (const manifest of manifests.filter((item) => item.kind === "backend-capability")) {
    for (const table of manifest.owns?.tables ?? []) {
      if (capabilityOwners.has(table)) {
        errors.push(`backend capability table has multiple owners ${table}`);
      }
      capabilityOwners.set(table, manifest.owner);
    }
  }
  for (const entry of catalogEntries) {
    if (entry.kind !== "capability-business") continue;
    if (capabilityOwners.get(entry.name) !== entry.owner) {
      errors.push(`architecture/database-catalog.json: capability ownership disagrees for ${entry.name}`);
    }
  }
  for (const [table, owner] of capabilityOwners) {
    const entry = catalogEntries.find((candidate) => candidate.name === table);
    if (entry?.kind !== "capability-business" || entry.owner !== owner) {
      errors.push(`architecture/database-catalog.json: capability table ownership is not catalogued ${table}`);
    }
  }
  const nativeClaims = new Map();
  for (const entry of catalogEntries) {
    if (!entry.name?.startsWith("public.")) continue;
    nativeClaims.set(`table:${entry.name.slice("public.".length)}`, entry);
  }
  const aliasClaims = new Map();
  const conflictedResources = new Set();
  for (const entry of catalogEntries) {
    for (const resource of entry.compatibilityResources ?? []) {
      const native = nativeClaims.get(resource);
      if (native) {
        errors.push(
          `architecture/database-catalog.json: compatibility resource ${resource} on ${entry.name} collides with catalog table ${native.name}`,
        );
        conflictedResources.add(resource);
      }
      const existing = aliasClaims.get(resource);
      if (existing) {
        errors.push(existing === entry
          ? `architecture/database-catalog.json: compatibility resource ${resource} is declared more than once by ${entry.name}`
          : `architecture/database-catalog.json: compatibility resource ${resource} is declared by both ${existing.name} and ${entry.name}`);
        conflictedResources.add(resource);
      } else {
        aliasClaims.set(resource, entry);
      }
    }
  }
  const resourceOwners = new Map();
  for (const [resource, entry] of nativeClaims) {
    if (!conflictedResources.has(resource)) resourceOwners.set(resource, entry.owner);
  }
  for (const [resource, entry] of aliasClaims) {
    if (!conflictedResources.has(resource)) resourceOwners.set(resource, entry.owner);
  }
  return { catalog, resourceOwners };
}

function validateSystemBindings(root, system, manifests, errors) {
  const backendByPublicEntryPoint = new Map(
    manifests
      .filter((manifest) => isBackendModule(manifest))
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
    const registered = adapter.decorators?.some((decorator) => (
      decorator.callable === port.registrationDecorator
      && decorator.arguments?.length === 1
      && decorator.arguments[0] === port.contract
    ));
    if (!registered) {
      errors.push(`architecture/backend-system.json: adapter is not registered for port ${binding.port}`);
    }
  }
}

function compatibilityBaselineDigest(baseline) {
  return `sha256:${createHash("sha256").update(JSON.stringify(stable(baseline))).digest("hex")}`;
}

function textDigest(value) {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function scopeSet(scopes) {
  return new Set((Array.isArray(scopes) ? scopes : []).map((scope) => (
    compatibilityScopeKey(scope.path, scope.rule, scope.resource, scope.operation)
  )));
}

function sameSet(left, right) {
  return left.size === right.size && [...left].every((value) => right.has(value));
}

function validateGateAttestations(label, gates, policy, errors) {
  const {
    registryPath,
    reachableRevision,
    isRevisionAncestor,
    gateEvidenceSchema,
    loadGateEvidence,
    isImmutableEvidence,
    loadGateTranscript,
    sourceAtGateRevision,
  } = policy;
  const revisions = gates.map((gate) => gate.revision);
  const loadedEvidence = [];
  if (gates.length !== 2
    || new Set(revisions).size !== 2
    || revisions.some((revision) => !/^[a-f0-9]{40}$/u.test(revision))) {
    errors.push(`${registryPath}: ${label} requires two distinct immutable gate revisions`);
    return;
  }
  if (reachableRevision && revisions.some((revision) => !reachableRevision(revision))) {
    errors.push(`${registryPath}: ${label} gate revisions must be reachable commits`);
  } else if (isRevisionAncestor && !isRevisionAncestor(revisions[0], revisions[1])) {
    errors.push(`${registryPath}: ${label} gate revisions are not ordered ancestors`);
  }
  for (const gate of gates) {
    const expectedPath = `architecture/evidence/customer-ready-gates/${gate.revision}.json`;
    if (gate.evidencePath !== expectedPath) {
      errors.push(`${registryPath}: gate ${gate.revision} evidence path must be ${expectedPath}`);
    }
    if (isImmutableEvidence && !isImmutableEvidence(gate.evidencePath)) {
      errors.push(`${registryPath}: gate ${gate.revision} evidence must be committed and unmodified`);
    }
    if (!loadGateEvidence) continue;
    const evidence = loadGateEvidence(gate.evidencePath);
    if (!evidence) {
      errors.push(`${registryPath}: gate ${gate.revision} evidence is missing`);
      continue;
    }
    loadedEvidence.push(evidence);
    validateAgainstSchema(gateEvidenceSchema, evidence, gate.evidencePath, errors);
    if (gate.evidenceDigest !== compatibilityBaselineDigest(evidence)) {
      errors.push(`${registryPath}: gate ${gate.revision} evidence digest does not match`);
    }
    if (evidence.revision !== gate.revision) {
      errors.push(`${registryPath}: gate evidence revision does not match ${gate.revision}`);
    }
    const evidenceChecks = Array.isArray(evidence.checks) ? evidence.checks : [];
    if (evidence.verdict !== "pass"
      || !sameSet(new Set(evidenceChecks.map((check) => check.name)), COMPLETE_GATE_CHECKS)
      || evidenceChecks.some((check) => check.exitCode !== 0)) {
      errors.push(`${registryPath}: gate ${gate.revision} does not attest the complete customer-ready gate`);
    }
    const expectedTranscriptPath = `architecture/evidence/customer-ready-gates/${gate.revision}.log`;
    if (evidence.transcriptPath !== expectedTranscriptPath) {
      errors.push(`${registryPath}: gate ${gate.revision} transcript path must be ${expectedTranscriptPath}`);
    }
    if (isImmutableEvidence && !isImmutableEvidence(evidence.transcriptPath)) {
      errors.push(`${registryPath}: gate ${gate.revision} transcript must be committed and unmodified`);
    }
    const transcript = loadGateTranscript?.(evidence.transcriptPath);
    if (typeof transcript !== "string" || evidence.transcriptDigest !== textDigest(transcript)) {
      errors.push(`${registryPath}: gate ${gate.revision} transcript digest does not match`);
    } else if (evidenceChecks.some((check) => !transcript.includes(`[${check.name}] exit=0`))) {
      errors.push(`${registryPath}: gate ${gate.revision} transcript is missing a passing check result`);
    }
    const producer = sourceAtGateRevision?.(gate.revision, evidence.producer);
    if (typeof producer !== "string" || evidence.producerDigest !== textDigest(producer)) {
      errors.push(`${registryPath}: gate ${gate.revision} producer digest does not match its revision`);
    }
  }
  if (loadedEvidence.length === 2
    && loadedEvidence[1].previousPassingRevision !== revisions[0]) {
    errors.push(`${registryPath}: ${label} gates are not consecutive passes`);
  }
}

export function validateCompatibilityRegistry(path, {
  now = new Date(),
  schema,
  releaseState,
  baselinePath,
  baselineSchema,
  expectedBaselineDigest,
  sourceRegistry,
  reachableRevision,
  isRevisionAncestor,
  sourceAtRevision,
  currentSource,
  resourceOwner,
  gateEvidenceSchema,
  loadGateEvidence,
  isImmutableEvidence,
  loadGateTranscript,
  sourceAtGateRevision,
} = {}) {
  const errors = [];
  const registry = readJson(path, errors);
  validateAgainstSchema(schema, registry, path, errors);
  if (registry.schemaVersion !== "2.0" || !Array.isArray(registry.records)) {
    errors.push(`${path}: invalid compatibility registry`);
    return errors;
  }

  const resolvedBaselinePath = baselinePath ?? join(dirname(path), "compatibility-baseline.json");
  const baseline = readJson(resolvedBaselinePath, errors);
  validateAgainstSchema(
    baselineSchema,
    baseline,
    "architecture/compatibility-baseline.json",
    errors,
  );
  if (baseline.sourceRevision !== FROZEN_LEGACY_SOURCE_REVISION) {
    errors.push(`${path}: frozen source revision must remain ${FROZEN_LEGACY_SOURCE_REVISION}`);
  }
  const actualBaselineDigest = expectedBaselineDigest ?? compatibilityBaselineDigest(baseline);
  if (registry.baseline?.digest !== actualBaselineDigest) {
    errors.push(`${path}: baseline digest does not match ${actualBaselineDigest}`);
  }
  if (registry.baseline?.path !== "architecture/compatibility-baseline.json") {
    errors.push(`${path}: baseline path must be architecture/compatibility-baseline.json`);
  }

  if (sourceRegistry !== undefined) {
    const sourceRecords = Array.isArray(sourceRegistry?.exceptions)
      ? sourceRegistry.exceptions
      : [];
    if (sourceRegistry?.schemaVersion !== "1.0" || !sourceRecords.length) {
      errors.push(`${path}: source revision does not contain the pre-existing compatibility registry`);
    } else {
      const sourceById = new Map(sourceRecords.map((record) => [record.id, record]));
      for (const baselineRecord of baseline.records ?? []) {
        const sourceRecord = sourceById.get(baselineRecord.id);
        const prefix = `${baselineRecord.id ?? "legacy facade"}:`;
        if (!sourceRecord) {
          errors.push(`${prefix} has no pre-existing source-revision record`);
          continue;
        }
        if (baselineRecord.removalIssue !== sourceRecord.removalIssue) {
          errors.push(`${prefix} removal issue does not match source revision`);
        }
        if (!sameSet(scopeSet(baselineRecord.scopes), scopeSet(sourceRecord.scopes))) {
          errors.push(`${prefix} frozen scopes do not match source revision`);
        }
        for (const scope of baselineRecord.scopes ?? []) {
          if (!sourceAtRevision) continue;
          const proof = legacyOperationProof(
            sourceAtRevision(scope.path),
            scope.path,
            scope,
          );
          if (!proof
            || proof.sourceDigest !== scope.sourceDigest
            || proof.occurrences !== scope.occurrences) {
            errors.push(`${prefix} source proof does not match ${scope.path} operation:${scope.operation}`);
          }
        }
      }
      for (const sourceRecord of sourceRecords) {
        if (!(baseline.records ?? []).some((record) => record.id === sourceRecord.id)) {
          errors.push(`${sourceRecord.id ?? "legacy facade"}: source-revision record is missing from the frozen baseline`);
        }
      }
    }
  }
  const baselineIds = new Set();
  for (const baselineRecord of baseline.records ?? []) {
    if (baselineIds.has(baselineRecord.id)) {
      errors.push(`${baselineRecord.id ?? "legacy facade"}: duplicate frozen baseline record`);
    }
    baselineIds.add(baselineRecord.id);
  }

  const foundationRecovery = registry.migration?.foundationRecovery;
  if (foundationRecovery?.issue !== "#186") {
    errors.push(`${path}: foundation recovery must remain bound to #186`);
  }
  if (foundationRecovery?.status === "pending") {
    if ((foundationRecovery.gates ?? []).length !== 0) {
      errors.push(`${path}: pending foundation recovery cannot claim gate evidence`);
    }
  } else if (foundationRecovery?.status === "complete") {
    validateGateAttestations(
      "foundation recovery #186",
      Array.isArray(foundationRecovery.gates) ? foundationRecovery.gates : [],
      {
        registryPath: path,
        reachableRevision,
        isRevisionAncestor,
        gateEvidenceSchema,
        loadGateEvidence,
        isImmutableEvidence,
        loadGateTranscript,
        sourceAtGateRevision,
      },
      errors,
    );
  } else {
    errors.push(`${path}: foundation recovery status must be pending or complete`);
  }

  const order = Array.isArray(registry.migration?.order) ? registry.migration.order : [];
  const stageIndexes = new Map();
  const issueOwners = new Map();
  for (const [index, stage] of order.entries()) {
    if (stageIndexes.has(stage.capability)) {
      errors.push(`${path}: duplicate migration capability ${stage.capability}`);
    } else {
      stageIndexes.set(stage.capability, index);
    }
    for (const issue of Array.isArray(stage.removalIssues) ? stage.removalIssues : []) {
      if (issueOwners.has(issue)) errors.push(`${path}: duplicate migration removal issue ${issue}`);
      else issueOwners.set(issue, stage.capability);
    }
  }
  const currentCapability = registry.migration?.currentCapability;
  const currentStageIndex = stageIndexes.get(currentCapability);
  if (currentStageIndex === undefined) {
    errors.push(`${path}: current capability ${currentCapability ?? "(missing)"} is not in migration order`);
  }
  if (issueOwners.get(registry.migration?.currentIssue) !== currentCapability) {
    errors.push(`${path}: current issue ${registry.migration?.currentIssue ?? "(missing)"} does not belong to ${currentCapability ?? "(missing)"}`);
  }
  const exitedCapabilities = new Set(registry.migration?.exitedCapabilities ?? []);
  const completedStages = Array.isArray(registry.migration?.completedStages)
    ? registry.migration.completedStages
    : [];
  if (currentStageIndex !== undefined) {
    const expectedExited = new Set(order.slice(0, currentStageIndex).map((stage) => stage.capability));
    if (!sameSet(exitedCapabilities, expectedExited)) {
      errors.push(`${path}: exitedCapabilities must exactly match stages before ${currentCapability}`);
    }
    const completedCapabilities = new Set(completedStages.map((stage) => stage.capability));
    if (!sameSet(completedCapabilities, expectedExited)
      || completedStages.length !== expectedExited.size) {
      errors.push(`${path}: completedStages must exactly evidence every exited capability`);
    }
  }
  for (const completed of completedStages) {
    const declared = order.find((stage) => stage.capability === completed.capability);
    if (!declared) {
      errors.push(`${path}: completed stage ${completed.capability ?? "(missing)"} is not in migration order`);
      continue;
    }
    if (!sameSet(new Set(completed.removalIssues ?? []), new Set(declared.removalIssues ?? []))) {
      errors.push(`${path}: completed stage ${completed.capability} must record its exact removal issues`);
    }
    validateGateAttestations(
      `completed stage ${completed.capability}`,
      Array.isArray(completed.gates) ? completed.gates : [],
      {
        registryPath: path,
        reachableRevision,
        isRevisionAncestor,
        gateEvidenceSchema,
        loadGateEvidence,
        isImmutableEvidence,
        loadGateTranscript,
        sourceAtGateRevision,
      },
      errors,
    );
  }

  const baselineById = new Map((baseline.records ?? []).map((record) => [record.id, record]));
  const frozenScopeOwners = new Map();
  const frozenScopesByOperation = new Map();
  for (const baselineRecord of baseline.records ?? []) {
    for (const scope of baselineRecord.scopes ?? []) {
      const scopeKey = compatibilityScopeKey(scope.path, scope.rule, scope.resource, scope.operation);
      frozenScopeOwners.set(scopeKey, { record: baselineRecord, scope });
      const operationKey = compatibilityOperationKey(scope.path, scope.operation);
      const operationScopes = frozenScopesByOperation.get(operationKey) ?? [];
      operationScopes.push(scope);
      frozenScopesByOperation.set(operationKey, operationScopes);
    }
  }
  const activeLegacyScopeKeys = new Set(
    registry.records
      .filter((entry) => entry.kind === "legacy-facade")
      .flatMap((entry) => (entry.scopes ?? []).map((scope) => (
        compatibilityScopeKey(scope.path, scope.rule, scope.resource, scope.operation)
      ))),
  );
  const removedFrozenScopes = [...frozenScopeOwners]
    .filter(([scopeKey]) => !activeLegacyScopeKeys.has(scopeKey))
    .map(([, ownedScope]) => ownedScope);
  const removedScopesByOperation = new Map();
  for (const removed of removedFrozenScopes) {
    const operationKey = compatibilityOperationKey(removed.scope.path, removed.scope.operation);
    const operationScopes = removedScopesByOperation.get(operationKey) ?? [];
    operationScopes.push(removed);
    removedScopesByOperation.set(operationKey, operationScopes);
  }
  const currentOperationAnalyses = new Map();
  const currentOperationAnalysis = (scope) => {
    const operationKey = compatibilityOperationKey(scope.path, scope.operation);
    if (currentOperationAnalyses.has(operationKey)) return currentOperationAnalyses.get(operationKey);
    let source;
    try {
      source = currentSource?.(scope.path);
    } catch {
      source = undefined;
    }
    const analysis = legacyOperationAnalysis(source, scope.path, scope.operation);
    currentOperationAnalyses.set(operationKey, analysis);
    return analysis;
  };
  const completedStagesByCapability = new Map(
    completedStages.map((stage) => [stage.capability, stage]),
  );
  const completedGateOperationAnalyses = new Map();
  const completedGateDeletionProven = (capability, scope, prefix) => {
    const completed = completedStagesByCapability.get(capability);
    const gates = completed?.gates ?? [];
    const revision = gates[gates.length - 1]?.revision;
    if (!revision || !sourceAtGateRevision) {
      errors.push(`${prefix} has no completed ${capability} gate source for deletion proof`);
      return false;
    }
    const operationKey = compatibilityOperationKey(scope.path, scope.operation);
    const cacheKey = `${revision}\0${operationKey}`;
    let analysis = completedGateOperationAnalyses.get(cacheKey);
    if (!analysis) {
      let gateSource;
      try {
        gateSource = sourceAtGateRevision(revision, scope.path);
      } catch {
        gateSource = undefined;
      }
      analysis = typeof gateSource === "string"
        ? legacyOperationAnalysis(gateSource, scope.path, scope.operation)
        : { state: "missing", persistenceOccurrences: new Map() };
      completedGateOperationAnalyses.set(cacheKey, analysis);
    }
    if (!analysis || analysis.state === "ambiguous") {
      errors.push(`${prefix} completed ${capability} gate has ambiguous deletion proof`);
      return false;
    }
    const resourceKind = scope.resource.split(":", 1)[0];
    const occurrences = analysis.state === "found"
      ? (analysis.persistenceOccurrences.get(scope.resource) ?? 0)
        + (analysis.persistenceOccurrences.get(`${resourceKind}:*`) ?? 0)
      : 0;
    if (occurrences !== 0) {
      errors.push(
        `${prefix} ${compatibilityScopeLabel(scope)} was not deleted at completed ${capability} gate`,
      );
      return false;
    }
    return true;
  };
  const deletionAuthorizedOperations = new Set();
  for (const [operationKey, removedScopes] of removedScopesByOperation) {
    let operationDeletionProven = true;
    for (const { record, scope } of removedScopes) {
      const prefix = `${record.id ?? "legacy facade"}:`;
      const recordStageIndex = stageIndexes.get(record.capability);
      const scopeResourceOwner = resourceOwner?.(scope.resource);
      const scopeOwnerCapability = scopeResourceOwner?.startsWith("backend:")
        ? scopeResourceOwner.slice("backend:".length)
        : undefined;
      let completedDeletionOwner;
      if (recordStageIndex === undefined) {
        errors.push(`${prefix} capability ${record.capability ?? "(missing)"} is absent from migration order`);
        operationDeletionProven = false;
      } else if (currentStageIndex !== undefined && recordStageIndex < currentStageIndex) {
        if (exitedCapabilities.has(record.capability)) {
          completedDeletionOwner = record.capability;
        }
      } else if (currentStageIndex !== undefined && recordStageIndex > currentStageIndex) {
        const authorizedResourceOwners = new Set([
          currentCapability,
          ...exitedCapabilities,
        ].map((capability) => `backend:${capability}`));
        if (!authorizedResourceOwners.has(scopeResourceOwner)) {
          errors.push(
            `${prefix} future frozen scope resource ${scope.resource} is not owned by active or exited capability`,
          );
          operationDeletionProven = false;
        }
      }
      if (!completedDeletionOwner && exitedCapabilities.has(scopeOwnerCapability)) {
        completedDeletionOwner = scopeOwnerCapability;
      }
      if (completedDeletionOwner
        && !completedGateDeletionProven(completedDeletionOwner, scope, prefix)) {
        operationDeletionProven = false;
      }
      const analysis = currentOperationAnalysis(scope);
      if (!analysis || analysis.state === "ambiguous") {
        errors.push(`${prefix} removed frozen scope lacks current-source deletion proof: ${compatibilityScopeLabel(scope)}`);
        operationDeletionProven = false;
        continue;
      }
      const resourceKind = scope.resource.split(":", 1)[0];
      const occurrences = analysis.state === "found"
        ? (analysis.persistenceOccurrences.get(scope.resource) ?? 0)
          + (analysis.persistenceOccurrences.get(`${resourceKind}:*`) ?? 0)
        : 0;
      if (occurrences !== 0) {
        errors.push(`${prefix} removed frozen scope still exists: ${compatibilityScopeLabel(scope)}`);
        operationDeletionProven = false;
      }
    }
    if (operationDeletionProven) deletionAuthorizedOperations.add(operationKey);
  }
  for (const operationKey of deletionAuthorizedOperations) {
    const frozenOperationScopes = frozenScopesByOperation.get(operationKey) ?? [];
    const analysis = currentOperationAnalysis(frozenOperationScopes[0]);
    if (analysis?.state !== "found") continue;
    const frozenResources = new Set(frozenOperationScopes.map((scope) => scope.resource));
    for (const [resource, occurrences] of analysis.persistenceOccurrences) {
      const knownDynamicKind = resource.endsWith(":*")
        && [...frozenResources].some((frozen) => frozen.startsWith(resource.slice(0, -1)));
      if (occurrences > 0 && !frozenResources.has(resource) && !knownDynamicKind) {
        const { record } = removedScopesByOperation.get(operationKey)[0];
        errors.push(`${record.id}: deletion-affected operation has an added writer outside the frozen baseline: ${resource} in ${operationLabel(operationKey)}`);
      }
    }
  }
  const recordsById = new Map();
  const canonicalImplementations = new Map();
  for (const entry of registry.records) {
    const prefix = `${entry.id ?? "compatibility exception"}:`;
    for (const field of [
      "id",
      "kind",
      "capability",
      "owner",
      "creationIssue",
      "removalIssue",
      "scopes",
      "approvedBy",
      "approvedAt",
      "removalCondition",
    ]) {
      if (!(field in entry)) errors.push(`${prefix} missing ${field}`);
    }
    if (!String(entry.id).startsWith("compat-")) errors.push(`${prefix} id must start compat-`);
    if (!/^#[0-9]+$/u.test(entry.creationIssue ?? "")) errors.push(`${prefix} creationIssue must be an issue`);
    if (!/^#[0-9]+$/u.test(entry.removalIssue ?? "")) errors.push(`${prefix} removalIssue must be an issue`);
    if (!Array.isArray(entry.scopes) || !entry.scopes.length) errors.push(`${prefix} scopes must be non-empty`);
    for (const scope of Array.isArray(entry.scopes) ? entry.scopes : []) {
      if (!SUPPRESSIBLE_COMPATIBILITY_RULES.has(scope.rule)) {
        errors.push(`${prefix} ${scope.rule} is not suppressible`);
      }
    }
    if (!String(entry.approvedBy ?? "").trim()) errors.push(`${prefix} approvedBy must identify the human approver`);
    const approvedAt = rfc3339Timestamp(entry.approvedAt);
    if (approvedAt === undefined) {
      errors.push(`${prefix} approvedAt must be a valid RFC 3339 timestamp`);
    } else if (approvedAt > now.getTime()) {
      errors.push(`${prefix} approvedAt cannot be in the future`);
    }
    if (!String(entry.removalCondition ?? "").trim()) errors.push(`${prefix} removalCondition must be non-empty`);

    if (recordsById.has(entry.id)) errors.push(`${prefix} duplicate record id`);
    else recordsById.set(entry.id, entry);
    const stageIndex = stageIndexes.get(entry.capability);
    if (stageIndex === undefined) {
      errors.push(`${prefix} capability ${entry.capability} is not in migration order`);
    }
    if (entry.kind === "legacy-facade") {
      if (issueOwners.get(entry.removalIssue) !== entry.capability) {
        errors.push(`${prefix} removalIssue ${entry.removalIssue} does not belong to capability ${entry.capability}`);
      }
      const baselineRecord = baselineById.get(entry.id);
      if (!baselineRecord) {
        errors.push(`${prefix} has no frozen baseline record`);
        continue;
      }
      if (entry.decisionIssue !== baseline.decisionIssue) {
        errors.push(`${prefix} decisionIssue must match frozen baseline decision ${baseline.decisionIssue}`);
      }
      if (entry.baselineRevision !== baseline.sourceRevision) {
        errors.push(`${prefix} baselineRevision must match frozen source ${baseline.sourceRevision}`);
      }
      if (entry.canonicalImplementation !== `web:legacy-runtime:${entry.capability}`) {
        errors.push(`${prefix} canonicalImplementation must name the capability's single legacy runtime`);
      }
      for (const field of ["capability", "removalIssue", "canonicalImplementation"]) {
        if (entry[field] !== baselineRecord[field]) {
          errors.push(`${prefix} ${field} differs from the frozen baseline`);
        }
      }
      const priorImplementation = canonicalImplementations.get(entry.capability);
      if (priorImplementation && priorImplementation !== entry.canonicalImplementation) {
        errors.push(`${prefix} capability ${entry.capability} declares a second legacy implementation`);
      } else {
        canonicalImplementations.set(entry.capability, entry.canonicalImplementation);
      }
      const frozenScopes = scopeSet(baselineRecord.scopes);
      for (const scope of Array.isArray(entry.scopes) ? entry.scopes : []) {
        const key = compatibilityScopeKey(scope.path, scope.rule, scope.resource, scope.operation);
        if (!frozenScopes.has(key)) {
          errors.push(`${prefix} scope is outside the frozen baseline: ${compatibilityScopeLabel(scope)}`);
          continue;
        }
        if (currentSource) {
          const frozenScope = baselineRecord.scopes.find((candidate) => (
            compatibilityScopeKey(
              candidate.path,
              candidate.rule,
              candidate.resource,
              candidate.operation,
            ) === key
          ));
          const proof = legacyScopeProof(currentOperationAnalysis(scope), scope);
          if (!proof || proof.occurrences > frozenScope.occurrences) {
            errors.push(`${prefix} scope has an added writer: ${compatibilityScopeLabel(scope)}`);
          } else if (proof.occurrences !== frozenScope.occurrences
            || (proof.sourceDigest !== frozenScope.sourceDigest
              && !deletionAuthorizedOperations.has(compatibilityOperationKey(scope.path, scope.operation)))) {
            errors.push(`${prefix} legacy operation changed: ${scope.path} operation:${scope.operation}`);
          }
        }
      }
      if (stageIndex !== undefined && currentStageIndex !== undefined) {
        if (stageIndex < currentStageIndex || exitedCapabilities.has(entry.capability)) {
          errors.push(`${prefix} capability ${entry.capability} has already exited`);
        } else if (stageIndex === currentStageIndex && registry.migration.status === "exit-review") {
          errors.push(`${entry.capability} cannot exit while legacy-facade ${entry.id} remains`);
        }
      }
    } else if (entry.kind === "active-stage-debt") {
      if (issueOwners.get(entry.creationIssue) !== entry.capability) {
        errors.push(`${prefix} creationIssue ${entry.creationIssue} does not belong to capability ${entry.capability}`);
      }
      if (entry.releaseLimit !== "next-stable-customer-ready-release") {
        errors.push(`${prefix} releaseLimit must be the next stable customer-ready release`);
      }
      const expiry = rfc3339Timestamp(entry.expiresAt);
      if (expiry === undefined) errors.push(`${prefix} expiresAt must be a valid RFC 3339 timestamp`);
      else {
        if (expiry <= now.getTime()) errors.push(`${prefix} expiresAt must be strictly in the future`);
        if (approvedAt !== undefined && expiry > approvedAt + 14 * 24 * 60 * 60 * 1000) {
          errors.push(`${prefix} expiresAt must be no later than fourteen days after approval`);
        }
      }
      const stableRelease = releaseState?.latestStableCustomerReadyRelease;
      const stableReleasedAt = rfc3339Timestamp(stableRelease?.releasedAt);
      if (approvedAt !== undefined
        && stableReleasedAt !== undefined
        && stableReleasedAt > approvedAt
        && stableReleasedAt <= now.getTime()) {
        errors.push(`${prefix} superseded by stable customer-ready release ${stableRelease.id}`);
      }
      const successorIndex = stageIndex === undefined ? undefined : stageIndex + 1;
      const expectedSuccessor = successorIndex === undefined ? undefined : order[successorIndex]?.capability;
      if (entry.successorCapability !== expectedSuccessor) {
        errors.push(`${prefix} successorCapability must be ${expectedSuccessor ?? "absent"}`);
      }
      if (stageIndex !== undefined && currentStageIndex !== undefined) {
        if (currentStageIndex < stageIndex) {
          errors.push(`${prefix} cannot exist before capability ${entry.capability} is active`);
        } else if (currentStageIndex > successorIndex) {
          errors.push(`${prefix} may not survive beyond successor capability ${entry.successorCapability}`);
        } else if (currentStageIndex === successorIndex && registry.migration.status === "exit-review") {
          errors.push(`${entry.successorCapability} cannot exit while predecessor active-stage-debt ${entry.id} remains`);
        }
      }
      for (const field of ["residualRisk", "rollback"]) {
        if (!String(entry[field] ?? "").trim()) errors.push(`${prefix} ${field} must be non-empty`);
      }
    } else {
      errors.push(`${prefix} kind must be legacy-facade or active-stage-debt`);
    }
  }

  const scopeOwners = new Map();
  for (const entry of registry.records) {
    for (const scope of Array.isArray(entry.scopes) ? entry.scopes : []) {
      const key = compatibilityScopeKey(scope.path, scope.rule, scope.resource, scope.operation);
      const previous = scopeOwners.get(key);
      if (previous) {
        errors.push(
          `duplicate compatibility scope ${compatibilityScopeLabel(scope)} across ${previous.removalIssue} and ${entry.removalIssue}`,
        );
      } else if (!previous) {
        scopeOwners.set(key, entry);
      }
    }
  }
  if (foundationRecovery?.status === "pending") {
    if (currentCapability !== "company_access"
      || registry.migration?.currentIssue !== "#138"
      || registry.migration?.status !== "active"
      || exitedCapabilities.size !== 0
      || completedStages.length !== 0) {
      errors.push(`${path}: pending foundation recovery blocks migration-state changes`);
    }
    if (registry.records.some((entry) => entry.kind !== "legacy-facade")) {
      errors.push(`${path}: pending foundation recovery blocks active-stage debt`);
    }
    if (recordsById.size !== baselineById.size
      || [...baselineById].some(([id, baselineRecord]) => {
        const record = recordsById.get(id);
        return !record || !sameSet(scopeSet(record.scopes), scopeSet(baselineRecord.scopes));
      })) {
      errors.push(`${path}: pending foundation recovery requires the untouched frozen facade inventory`);
    }
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

function compatibilityScopeKey(path, rule, resource, operation) {
  return [path, rule, resource, operation].join("\u0000");
}

function compatibilityOperationKey(path, operation) {
  return [path, operation].join("\u0000");
}

function operationLabel(operationKey) {
  const [path, operation] = operationKey.split("\u0000");
  return `${path} operation:${operation}`;
}

function compatibilityScopeLabel(scope) {
  return `${scope.path} ${scope.rule} ${scope.resource} operation:${scope.operation}`;
}

function activeCompatibilityMatches(registry, releaseState, path, rule, resource, operation, now) {
  const stableReleasedAt = rfc3339Timestamp(
    releaseState.latestStableCustomerReadyRelease?.releasedAt,
  );
  const order = registry.migration?.order ?? [];
  const stageIndexes = new Map(order.map((stage, index) => [stage.capability, index]));
  const currentStageIndex = stageIndexes.get(registry.migration?.currentCapability);
  return (registry.records ?? []).filter((entry) => {
    const scoped = Array.isArray(entry.scopes) && entry.scopes.some((scope) => (
      scope.path === path
      && scope.rule === rule
      && scope.resource === resource
      && scope.operation === operation
    ));
    if (!scoped) return false;
    const stageIndex = stageIndexes.get(entry.capability);
    if (entry.kind === "legacy-facade") {
      return stageIndex !== undefined
        && currentStageIndex !== undefined
        && stageIndex >= currentStageIndex;
    }
    return entry.kind === "active-stage-debt"
      && rfc3339Timestamp(entry.expiresAt) > now.getTime()
      && (
      stableReleasedAt === undefined
      || stableReleasedAt <= rfc3339Timestamp(entry.approvedAt)
      || stableReleasedAt > now.getTime()
      );
  });
}

function checkGlobalWebBoundary(root, registry, releaseState, errors, now, webAnalysis) {
  const actualScopes = new Set();
  for (const path of walk(join(root, "apps/web"), (candidate) => /\.[cm]?[jt]sx?$/u.test(candidate))) {
    const scopedPath = relative(root, path);
    const source = readFileSync(path, "utf8");
    const boundary = webBoundaryViolations(source, path, webAnalysis);
    for (const { resource, operation } of boundary.fetch.values()) {
      const rule = "direct-business-fetch";
      actualScopes.add(compatibilityScopeKey(scopedPath, rule, resource, operation));
      const matches = activeCompatibilityMatches(
        registry, releaseState, scopedPath, rule, resource, operation, now,
      );
      if (!matches.length) {
        errors.push(`${scopedPath}: direct business fetch is forbidden for ${resource} in operation:${operation}`);
      } else if (matches.length > 1) {
        errors.push(`${scopedPath}: direct business fetch has ambiguous compatibility for ${resource} in operation:${operation}`);
      }
    }
    for (const { resource, operation } of boundary.persistence.values()) {
      const rule = "direct-web-business-persistence";
      actualScopes.add(compatibilityScopeKey(scopedPath, rule, resource, operation));
      const matches = activeCompatibilityMatches(
        registry, releaseState, scopedPath, rule, resource, operation, now,
      );
      if (!matches.length) {
        errors.push(`${scopedPath}: direct web business persistence is forbidden for ${resource} in operation:${operation}`);
      } else if (matches.length > 1) {
        errors.push(`${scopedPath}: direct web business persistence has ambiguous compatibility for ${resource} in operation:${operation}`);
      }
    }
    if (generatedClientDeepImport(source, path, webAnalysis)) {
      const rule = "generated-client-deep-import";
      const resource = "module:@talli/talli-api-client/*";
      const operation = "module";
      actualScopes.add(compatibilityScopeKey(scopedPath, rule, resource, operation));
      const matches = activeCompatibilityMatches(
        registry,
        releaseState,
        scopedPath,
        rule,
        resource,
        operation,
        now,
      );
      if (!matches.length) {
        errors.push(`${scopedPath}: generated-client deep import is forbidden`);
      } else if (matches.length > 1) {
        errors.push(`${scopedPath}: generated-client deep import has ambiguous compatibility`);
      }
    }
  }
  for (const entry of registry.records ?? []) {
    for (const scope of Array.isArray(entry.scopes) ? entry.scopes : []) {
      const key = compatibilityScopeKey(scope.path, scope.rule, scope.resource, scope.operation);
      if (!actualScopes.has(key)) {
        errors.push(`${entry.id}: registered compatibility scope has no matching finding: ${compatibilityScopeLabel(scope)}`);
      }
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

function gitOutput(root, args) {
  const result = spawnSync("git", ["-C", root, ...args], { encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : undefined;
}

function repositoryForReleaseRefs(root) {
  return gitOutput(root, ["rev-parse", "--show-toplevel"]) ?? CHECKER_REPOSITORY_ROOT;
}

function latestReachableCustomerReadyRelease(root, errors) {
  const repository = repositoryForReleaseRefs(root);
  const tagsOutput = gitOutput(repository, ["tag", "--list", "customer-ready-*"]);
  if (tagsOutput === undefined) {
    errors.push("architecture/release-state.json: unable to inspect customer-ready Git tags");
    return null;
  }
  const candidates = [];
  for (const id of tagsOutput.split("\n").filter(Boolean)) {
    const gitRevision = gitOutput(repository, ["rev-parse", `${id}^{commit}`]);
    if (!gitRevision) {
      errors.push(`architecture/release-state.json: customer-ready Git tag ${id} has no commit target`);
      continue;
    }
    const reachable = spawnSync(
      "git",
      ["-C", repository, "merge-base", "--is-ancestor", gitRevision, "HEAD"],
      { encoding: "utf8" },
    );
    if (reachable.status !== 0) continue;
    const objectType = gitOutput(repository, ["cat-file", "-t", `refs/tags/${id}`]);
    if (objectType !== "tag") {
      errors.push(
        `architecture/release-state.json: customer-ready Git tag ${id} must be an annotated tag object`,
      );
      continue;
    }
    const tagObject = gitOutput(repository, ["cat-file", "tag", `refs/tags/${id}`]);
    const tagIdentity = tagObject?.match(/^tag (.+)$/mu)?.[1];
    if (tagIdentity !== id) {
      errors.push(
        `architecture/release-state.json: customer-ready Git tag ${id} has mismatched tag object identity ${tagIdentity ?? "(missing)"}`,
      );
      continue;
    }
    const releasedAt = gitOutput(
      repository,
      ["for-each-ref", "--format=%(taggerdate:iso-strict)", `refs/tags/${id}`],
    );
    const timestamp = rfc3339Timestamp(releasedAt);
    if (timestamp === undefined) {
      errors.push(`architecture/release-state.json: customer-ready Git tag ${id} has no valid release timestamp`);
      continue;
    }
    candidates.push({ id, releasedAt, gitRevision, timestamp });
  }
  const tagsByTimestamp = new Map();
  for (const candidate of candidates) {
    const ids = tagsByTimestamp.get(candidate.timestamp) ?? [];
    ids.push(candidate.id);
    tagsByTimestamp.set(candidate.timestamp, ids);
  }
  for (const ids of tagsByTimestamp.values()) {
    if (ids.length > 1) {
      const sortedIds = ids.sort();
      errors.push(
        `architecture/release-state.json: ambiguous customer-ready Git tags ${sortedIds.join(", ")} share tagger timestamp`,
      );
      return null;
    }
  }
  candidates.sort((left, right) => right.timestamp - left.timestamp);
  const latest = candidates[0];
  return latest
    ? { id: latest.id, releasedAt: latest.releasedAt, gitRevision: latest.gitRevision }
    : null;
}

export function checkArchitecture({ root, writeEvidence = false, now = new Date() }) {
  const resolvedRoot = rootPath(root);
  const errors = [];
  const webAnalysis = createWebBoundaryAnalysis(resolvedRoot);
  const schemas = Object.fromEntries([
    ["module", "module.schema.json"],
    ["backendSystem", "backend-system.schema.json"],
    ["compatibility", "compatibility.schema.json"],
    ["compatibilityBaseline", "compatibility-baseline.schema.json"],
    ["customerReadyGateEvidence", "customer-ready-gate-evidence.schema.json"],
    ["releaseState", "release-state.schema.json"],
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
  const compatibilityBaselinePath = join(resolvedRoot, "architecture/compatibility-baseline.json");
  const compatibility = readJson(compatibilityPath, []);
  const { resourceOwners: databaseResourceOwners } = validateDatabaseCatalog(
    resolvedRoot,
    backendSystem,
    manifests,
    compatibility,
    errors,
    schemas.databaseCatalog,
  );
  const compatibilityBaseline = readJson(compatibilityBaselinePath, errors);
  const compatibilitySourceRegistry = readGitJson(
    resolvedRoot,
    compatibilityBaseline.sourceRevision,
    "architecture/compatibility.json",
    errors,
  );
  const frozenSourceCache = new Map();
  const gateSourceCache = new Map();
  const sourceAtRevision = (path) => {
    if (frozenSourceCache.has(path)) return frozenSourceCache.get(path);
    const result = spawnSync(
      "git",
      ["-C", resolvedRoot, "show", `${FROZEN_LEGACY_SOURCE_REVISION}:${path}`],
      { encoding: "utf8" },
    );
    const source = result.status === 0 ? result.stdout : undefined;
    frozenSourceCache.set(path, source);
    return source;
  };
  const sourceAtGateRevision = (revision, path) => {
    const key = `${revision}\0${path}`;
    if (gateSourceCache.has(key)) return gateSourceCache.get(key);
    const result = spawnSync("git", ["-C", resolvedRoot, "show", `${revision}:${path}`], {
      encoding: "utf8",
    });
    const source = result.status === 0 ? result.stdout : undefined;
    gateSourceCache.set(key, source);
    return source;
  };
  const releaseState = readJson(join(resolvedRoot, "architecture/release-state.json"), errors);
  validateAgainstSchema(
    schemas.releaseState,
    releaseState,
    "architecture/release-state.json",
    errors,
  );
  const verifiedStableRelease = latestReachableCustomerReadyRelease(resolvedRoot, errors);
  const trackedStableRelease = releaseState.latestStableCustomerReadyRelease;
  if (JSON.stringify(stable(trackedStableRelease)) !== JSON.stringify(stable(verifiedStableRelease))) {
    errors.push(
      `architecture/release-state.json: tracked release does not match the latest reachable customer-ready Git tag${verifiedStableRelease ? ` ${verifiedStableRelease.id}` : " (none)"}`,
    );
  }
  const stableReleasedAt = rfc3339Timestamp(verifiedStableRelease?.releasedAt);
  if (verifiedStableRelease && stableReleasedAt > now.getTime()) {
    errors.push("architecture/release-state.json: stable release cannot be in the future");
  }
  const verifiedReleaseState = {
    ...releaseState,
    latestStableCustomerReadyRelease: verifiedStableRelease,
  };
  errors.push(...validateCompatibilityRegistry(
    compatibilityPath,
    {
      now,
      schema: schemas.compatibility,
      releaseState: verifiedReleaseState,
      baselinePath: compatibilityBaselinePath,
      baselineSchema: schemas.compatibilityBaseline,
      sourceRegistry: compatibilitySourceRegistry,
      reachableRevision: (revision) => isReachableGitRevision(resolvedRoot, revision),
      isRevisionAncestor: (ancestor, descendant) => (
        spawnSync(
          "git",
          ["-C", resolvedRoot, "merge-base", "--is-ancestor", ancestor, descendant],
        ).status === 0
      ),
      sourceAtRevision,
      currentSource: (path) => readFileSync(join(resolvedRoot, path), "utf8"),
      resourceOwner: (resource) => {
        if (!/^table:[a-z_]+$/u.test(resource)) return undefined;
        return databaseResourceOwners.get(resource);
      },
      gateEvidenceSchema: schemas.customerReadyGateEvidence,
      loadGateEvidence: (path) => (
        existsSync(join(resolvedRoot, path))
          ? readJson(join(resolvedRoot, path), errors)
          : undefined
      ),
      isImmutableEvidence: (path) => isCommittedUnmodified(resolvedRoot, path),
      loadGateTranscript: (path) => (
        existsSync(join(resolvedRoot, path))
          ? readFileSync(join(resolvedRoot, path), "utf8")
          : undefined
      ),
      sourceAtGateRevision,
    },
  ));
  checkGlobalWebBoundary(resolvedRoot, compatibility, verifiedReleaseState, errors, now, webAnalysis);
  const sharedKernel = readJson(join(resolvedRoot, "architecture/shared-kernel.json"), errors);
  validateAgainstSchema(schemas.sharedKernel, sharedKernel, "architecture/shared-kernel.json", errors);
  if (!Array.isArray(sharedKernel.allowedPublicPackages) || !Array.isArray(sharedKernel.forbidden)) {
    errors.push("architecture/shared-kernel.json: missing minimal shared-kernel policy");
  }
  checkSharedKernel(resolvedRoot, sharedKernel, errors);
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
