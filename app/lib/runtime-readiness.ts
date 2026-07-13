import { constants } from "node:fs";
import { access } from "node:fs/promises";
import path from "node:path";

const schemaFiles = [
  "aksjonaerregisteroppgaveHovedskjema.xsd",
  "aksjonaerregisteroppgaveUnderskjema.xsd",
] as const;

type RuntimeCheck = {
  status: "ok" | "failed";
  reason?: string;
};

export type RuntimeReadiness = {
  status: "ready" | "not_ready";
  checks: {
    configuration: RuntimeCheck;
    python: RuntimeCheck;
    schemas: RuntimeCheck;
  };
};

export type RuntimeReadinessOptions = {
  env?: NodeJS.ProcessEnv;
  root?: string;
};

async function canAccess(target: string, mode: number) {
  try {
    await access(target, mode);
    return true;
  } catch {
    return false;
  }
}

export async function evaluateRuntimeReadiness(
  options: RuntimeReadinessOptions = {},
): Promise<RuntimeReadiness> {
  const env = options.env ?? process.env;
  const root = options.root ?? process.cwd();
  const configuration = env.SUPABASE_URL && env.SUPABASE_ANON_KEY
    ? { status: "ok" as const }
    : { status: "failed" as const, reason: "missing_supabase_configuration" };

  const pythonBin = env.TALLI_PYTHON_BIN?.trim();
  const python = pythonBin && path.isAbsolute(pythonBin) && await canAccess(pythonBin, constants.X_OK)
    ? { status: "ok" as const }
    : { status: "failed" as const, reason: "python_runtime_unavailable" };

  const schemaRoot = path.join(root, "docs", "filing");
  const schemasAvailable = (
    await Promise.all(schemaFiles.map((file) => canAccess(path.join(schemaRoot, file), constants.R_OK)))
  ).every(Boolean);
  const schemas = schemasAvailable
    ? { status: "ok" as const }
    : { status: "failed" as const, reason: "rf1086_schemas_unavailable" };

  const checks = { configuration, python, schemas };
  return {
    status: Object.values(checks).every((check) => check.status === "ok") ? "ready" : "not_ready",
    checks,
  };
}
