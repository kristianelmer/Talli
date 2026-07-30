import { existsSync } from "node:fs";
import { resolve } from "node:path";

type PythonRuntimeOptions = {
  env?: Record<string, string | undefined>;
  cwd?: string;
  exists?: (path: string) => boolean;
};

export function resolveTalliPythonBinary(options: PythonRuntimeOptions = {}) {
  const env = options.env ?? process.env;
  const cwd = options.cwd ?? process.cwd();
  const exists = options.exists ?? existsSync;
  const configured = env.TALLI_PYTHON_BIN?.trim();
  if (configured) {
    return configured;
  }

  const candidates = [resolve(cwd, ".venv/bin/python"), resolve(cwd, ".venv/Scripts/python.exe")];
  const localRuntime = candidates.find((candidate) => exists(candidate));
  if (localRuntime) {
    return localRuntime;
  }
  throw new Error(
    "TALLI_PYTHON_BIN must point to a Python runtime with the Talli project dependencies installed.",
  );
}
