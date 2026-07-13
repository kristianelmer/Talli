import { spawn } from "node:child_process";

const image = process.env.TALLI_SMOKE_IMAGE ?? "talli:smoke";
const container = `talli-smoke-${process.pid}`;

function run(command, args, { capture = false } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: capture ? ["ignore", "pipe", "inherit"] : "inherit",
    });
    let stdout = "";
    if (capture) child.stdout.on("data", (chunk) => { stdout += chunk.toString("utf8"); });
    child.on("error", reject);
    child.on("close", (status) => {
      if (status === 0) resolve(stdout.trim());
      else reject(new Error(`${command} exited with status ${status}`));
    });
  });
}

async function waitFor(url, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (response.ok) return response.json();
      lastError = new Error(`${url} returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw lastError ?? new Error(`${url} did not become ready`);
}

try {
  await run("docker", ["build", "--pull", "--tag", image, "."]);
  await run("docker", [
    "run",
    "--detach",
    "--rm",
    "--name",
    container,
    "--read-only",
    "--tmpfs",
    "/tmp:rw,noexec,nosuid,size=64m",
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges:true",
    "--publish",
    "127.0.0.1::3000",
    "--env",
    "SUPABASE_URL=https://smoke.invalid",
    "--env",
    "SUPABASE_ANON_KEY=smoke-publishable-key",
    image,
  ]);
  const portOutput = await run("docker", ["port", container, "3000/tcp"], { capture: true });
  const port = portOutput.match(/:(\d+)$/u)?.[1];
  if (!port) throw new Error(`Could not determine published port from: ${portOutput}`);

  const baseUrl = `http://127.0.0.1:${port}`;
  await waitFor(`${baseUrl}/api/health`);
  const readiness = await waitFor(`${baseUrl}/api/ready`);
  if (readiness.status !== "ready") throw new Error(`Unexpected readiness: ${JSON.stringify(readiness)}`);

  await run("docker", [
    "exec",
    container,
    "sh",
    "-c",
    "test \"$(id -u)\" = 1000",
  ]);
  await run("docker", [
    "exec",
    container,
    "/app/.venv/bin/python",
    "-c",
    "import pydantic, reportlab, holding_cli.main, holding_core.corporate_documents, holding_core.rf1086",
  ]);
  await run("docker", [
    "exec",
    container,
    "sh",
    "-c",
    "test ! -e /app/.env && test ! -e /app/.env.local",
  ]);
} finally {
  await run("docker", ["rm", "--force", container]).catch(() => {});
}
