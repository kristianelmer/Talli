import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:net";

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

export function startOwnedProcess({ command, args, cwd, env }) {
  const process = spawn(command, args, {
    cwd,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
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
    try {
      const response = await fetchImpl(url, { cache: "no-store" });
      if (response.ok) {
        await delay(0);
        assertProcessAlive(process);
        return;
      }
    } catch {
      // Bounded local process startup polling.
    }
    await delay(pollMs);
  }
  assertProcessAlive(process);
  throw new Error("owned_process_readiness_deadline_exceeded");
}

export async function stopOwnedProcess(process) {
  if (hasExited(process)) return;

  const exited = once(process, "exit");
  process.kill("SIGTERM");
  const stopped = await Promise.race([
    exited.then(() => true),
    delay(5_000).then(() => false),
  ]);
  if (!stopped && !hasExited(process)) {
    process.kill("SIGKILL");
    await exited;
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
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, milliseconds);
    timer.unref?.();
  });
}
