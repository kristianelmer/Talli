import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:net";

const READINESS_STATE = Symbol("owned-process-readiness");

export async function allocateLoopbackPort() {
  const listener = createServer();
  listener.listen(0, "127.0.0.1");
  await once(listener, "listening");
  const address = listener.address();
  if (!address || typeof address === "string") {
    throw new Error("loopback_port_allocation_failed");
  }
  listener.close();
  await once(listener, "close");
  return address.port;
}

export function startOwnedProcess({ command, args, cwd, env, readinessProof }) {
  const process = spawn(command, args, {
    cwd,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  process[READINESS_STATE] = {
    buffer: "",
    matched: false,
    proof: readinessProof,
  };
  const inspectOutput = (chunk) => {
    const state = process[READINESS_STATE];
    state.buffer = `${state.buffer}${chunk.toString()}`.slice(-4_096);
    if (typeof state.proof === "string" && state.buffer.includes(state.proof)) {
      state.matched = true;
    }
  };
  process.stdout?.on("data", inspectOutput);
  process.stderr?.on("data", inspectOutput);
  process.stdout?.resume();
  process.stderr?.resume();
  return process;
}

export async function waitForOwnedReadiness({
  process,
  url,
  fetchImpl = fetch,
  timeoutMs = 30_000,
  pollMs = 250,
}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    assertProcessAlive(process);
    let response;
    try {
      response = await fetchImpl(url, { cache: "no-store" });
    } catch {
      // Bounded local process startup polling.
    }
    if (response?.ok && process[READINESS_STATE]?.matched) {
      await delay(0);
      assertProcessAlive(process);
      if (process[READINESS_STATE]?.matched) return;
    }
    await delay(pollMs);
  }
  assertProcessAlive(process);
  throw new Error("owned_process_readiness_deadline_exceeded");
}

export async function stopOwnedProcess(
  process,
  { terminateTimeoutMs = 5_000, killTimeoutMs = 1_000 } = {},
) {
  if (!process || hasExited(process)) return;

  const exited = once(process, "exit");
  process.kill("SIGTERM");
  const stopped = await exitsBefore(exited, terminateTimeoutMs);
  if (!stopped && !hasExited(process)) {
    process.kill("SIGKILL");
    const killed = await exitsBefore(exited, killTimeoutMs);
    if (!killed && !hasExited(process)) {
      throw new Error("owned_process_kill_deadline_exceeded");
    }
  }
}

function assertProcessAlive(process) {
  if (hasExited(process)) {
    throw new Error("owned_process_exited_before_readiness");
  }
}

function hasExited(process) {
  return process.exitCode !== null || process.signalCode !== null;
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function exitsBefore(exited, timeoutMs) {
  let timer;
  try {
    return await Promise.race([
      exited.then(() => true),
      new Promise((resolve) => {
        timer = setTimeout(() => resolve(false), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}
