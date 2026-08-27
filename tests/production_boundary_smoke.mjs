import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { readdirSync, readFileSync } from "node:fs";
import { createServer as createHttpServer } from "node:http";
import { createRequire } from "node:module";
import { createServer as createTcpServer } from "node:net";
import { resolve } from "node:path";
import test from "node:test";

import { assertValueMatchesSchema } from "../scripts/check-openapi-contract.mjs";
import { createBaselineTalliApiClient } from "./fixtures/talli-api-client-v1.0.0.mjs";

const repositoryRoot = resolve(import.meta.dirname, "..");
const requireFromWebPackage = createRequire(
  new URL("../apps/web/package.json", import.meta.url),
);
const nextCli = requireFromWebPackage.resolve("next/dist/bin/next");
const baseline = JSON.parse(
  readFileSync(
    resolve(repositoryRoot, "contracts/openapi/baselines/talli-v1.0.0.json"),
    "utf8",
  ),
);

async function availablePort() {
  const server = createTcpServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.notEqual(typeof address, "string");
  const port = address.port;
  server.close();
  await once(server, "close");
  return port;
}

function startProcess(command, args, env = {}) {
  const output = [];
  const child = spawn(command, args, {
    cwd: repositoryRoot,
    env: { ...process.env, ...env },
    stdio: ["ignore", "pipe", "pipe"],
  });
  for (const stream of [child.stdout, child.stderr]) {
    stream.on("data", (chunk) => {
      output.push(chunk.toString());
      if (output.length > 80) output.shift();
    });
  }
  child.diagnostics = () => output.join("");
  return child;
}

async function waitFor(url, expectedStatus, process, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (process.exitCode !== null || process.signalCode !== null) {
      throw new Error(`process exited before ${url}\n${process.diagnostics()}`);
    }
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (response.status === expectedStatus) return response;
    } catch {
      // The local production process may still be binding its socket.
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
  }
  throw new Error(`timed out waiting for ${url}\n${process.diagnostics()}`);
}

async function stopProcess(process) {
  if (process.exitCode !== null || process.signalCode !== null) return;
  const stopped = once(process, "exit");
  process.kill("SIGTERM");
  const timeout = new Promise((resolveTimeout) =>
    setTimeout(() => resolveTimeout("timeout"), 5_000),
  );
  if ((await Promise.race([stopped, timeout])) === "timeout") {
    process.kill("SIGKILL");
    await once(process, "exit");
  }
}

async function startBaselineBackendFixture(port) {
  const server = createHttpServer((request, response) => {
    if (request.url === "/api/v1/system-boundary/tracer") {
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(
        JSON.stringify({
          apiVersion: "v1",
          service: "talli-backend",
          status: "AVAILABLE",
        }),
      );
      return;
    }
    response.writeHead(404, { "Content-Type": "text/plain" });
    response.end("not found");
  });
  server.listen(port, "127.0.0.1");
  await once(server, "listening");
  return server;
}

async function stopServer(server) {
  if (!server?.listening) return;
  server.close();
  await once(server, "close");
}

test("built artifacts support both deployment orders and isolate backend failure", async () => {
  const wheels = readdirSync(resolve(repositoryRoot, "apps/backend/dist")).filter(
    (name) => name.endsWith(".whl"),
  );
  assert.equal(wheels.length, 1, "build:backend must produce exactly one wheel");
  const wheel = resolve(repositoryRoot, "apps/backend/dist", wheels[0]);
  const backendPort = await availablePort();
  const webPort = await availablePort();
  const backend = startProcess(
    resolve(repositoryRoot, "apps/backend/.venv/bin/python"),
    [
      "-m",
      "uvicorn",
      "talli_backend.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(backendPort),
    ],
    { PYTHONPATH: wheel },
  );
  let web;
  let baselineBackend;

  try {
    await waitFor(
      `http://127.0.0.1:${backendPort}/health/live`,
      200,
      backend,
    );
    const baselineResponse = await fetch(
      `http://127.0.0.1:${backendPort}/api/v1/system-boundary/tracer`,
    );
    assert.equal(baselineResponse.status, 200);
    assertValueMatchesSchema(
      baseline,
      baseline.paths["/api/v1/system-boundary/tracer"].get.responses["200"].content[
        "application/json"
      ].schema,
      await baselineResponse.json(),
      "SystemBoundaryStatus",
    );
    const baselineClient = createBaselineTalliApiClient({
      baseUrl: `http://127.0.0.1:${backendPort}`,
    });
    assert.deepEqual(await baselineClient.systemBoundaryGetTracerStatus(), {
      apiVersion: "v1",
      service: "talli-backend",
      status: "AVAILABLE",
    });
    // The pinned previously deployed client consumes the new backend.

    web = startProcess(
      process.execPath,
      [
        nextCli,
        "start",
        "apps/web",
        "-p",
        String(webPort),
      ],
      {
        NODE_ENV: "production",
        TALLI_BACKEND_URL: `http://127.0.0.1:${backendPort}`,
      },
    );
    await waitFor(`http://127.0.0.1:${webPort}/health/live`, 200, web);
    assert.equal(
      (await fetch(`http://127.0.0.1:${webPort}/health/ready`)).status,
      200,
    );
    const successPage = await (
      await fetch(`http://127.0.0.1:${webPort}/system-boundary`)
    ).text();
    assert.match(successPage, /Forbindelsen virker/);

    await stopProcess(backend);
    baselineBackend = await startBaselineBackendFixture(backendPort);
    const baselinePage = await (
      await fetch(`http://127.0.0.1:${webPort}/system-boundary`)
    ).text();
    assert.match(baselinePage, /Forbindelsen virker/);
    // The new web can consume the explicitly pinned prior backend contract.

    await stopServer(baselineBackend);
    baselineBackend = undefined;
    assert.equal(
      (await fetch(`http://127.0.0.1:${webPort}/health/live`)).status,
      200,
    );
    assert.equal(
      (await fetch(`http://127.0.0.1:${webPort}/health/ready`)).status,
      200,
    );
    const failurePage = await (
      await fetch(`http://127.0.0.1:${webPort}/system-boundary`)
    ).text();
    assert.match(failurePage, /Tjenesten er midlertidig utilgjengelig/);
    assert.doesNotMatch(failurePage, /ECONNREFUSED|127\.0\.0\.1/);
  } finally {
    await Promise.all([
      stopProcess(backend),
      web ? stopProcess(web) : undefined,
      stopServer(baselineBackend),
    ]);
  }
});
