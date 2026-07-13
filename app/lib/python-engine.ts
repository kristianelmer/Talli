import { spawn } from "node:child_process";

export type PythonEngineResult = {
  status: number;
  stdout: string;
  stderr: string;
};

export class PythonEngineError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "PythonEngineError";
    this.code = code;
  }
}

export function pythonEngineInvocation() {
  const configuredExecutable = process.env.TALLI_PYTHON_BIN?.trim();
  if (configuredExecutable) {
    return { command: configuredExecutable, prefixArgs: [] as string[] };
  }
  if (process.env.NODE_ENV === "production") {
    return { command: "python3", prefixArgs: [] as string[] };
  }
  return { command: "uv", prefixArgs: ["run", "python"] };
}

function boundedInteger(value: string | undefined, fallback: number, minimum: number, maximum: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= minimum && parsed <= maximum ? parsed : fallback;
}

// Node recommends the asynchronous spawn API for long-running work because the
// synchronous variants block the event loop.
// Source: https://nodejs.org/api/child_process.html#child_processspawncommand-args-options
export function runPythonCli(commandArgs: string[], input: unknown): Promise<PythonEngineResult> {
  const invocation = pythonEngineInvocation();
  const timeoutMs = boundedInteger(process.env.TALLI_PYTHON_TIMEOUT_MS, 30_000, 1_000, 120_000);
  const maxOutputBytes = boundedInteger(process.env.TALLI_PYTHON_MAX_OUTPUT_BYTES, 20_000_000, 1_000_000, 50_000_000);

  return new Promise((resolve, reject) => {
    const child = spawn(
      invocation.command,
      [...invocation.prefixArgs, "-m", "holding_cli.main", ...commandArgs],
      {
        env: process.env,
        stdio: ["pipe", "pipe", "pipe"],
      },
    );
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    let outputBytes = 0;
    let settled = false;

    const finishWithError = (error: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      child.kill("SIGKILL");
      reject(error);
    };
    const collect = (target: Buffer[], chunk: Buffer) => {
      outputBytes += chunk.byteLength;
      if (outputBytes > maxOutputBytes) {
        finishWithError(new PythonEngineError("RF-1086 engine output exceeded the configured limit.", "python_engine_output_limit"));
        return;
      }
      target.push(chunk);
    };
    const timeout = setTimeout(() => {
      finishWithError(new PythonEngineError("RF-1086 engine timed out.", "python_engine_timeout"));
    }, timeoutMs);

    child.stdout.on("data", (chunk: Buffer) => collect(stdout, chunk));
    child.stderr.on("data", (chunk: Buffer) => collect(stderr, chunk));
    child.on("error", (error) => {
      finishWithError(new PythonEngineError(`RF-1086 engine could not start: ${error.message}`, "python_engine_start_failed"));
    });
    child.on("close", (status) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve({
        status: status ?? 1,
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8"),
      });
    });

    child.stdin.on("error", (error) => {
      finishWithError(new PythonEngineError(`RF-1086 engine input failed: ${error.message}`, "python_engine_input_failed"));
    });
    child.stdin.end(JSON.stringify(input));
  });
}
