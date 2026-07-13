import { spawn } from "node:child_process";

const projectId = "talli-local";
const network = `${projectId}-network`;
const excludedServices = [
  "studio",
  "realtime",
  "imgproxy",
  "mailpit",
  "postgres-meta",
  "edge-runtime",
  "logflare",
  "vector",
  "supavisor",
].join(",");

const secretPatterns = [
  /(ANON_KEY|SERVICE_ROLE_KEY|JWT_SECRET|SECRET_KEY|PUBLISHABLE_KEY|DB_URL)=\S+/giu,
  /((?:anon|service_role|secret|publishable) key\s*:\s*)\S+/giu,
  /\b(?:sb_(?:secret|publishable)_[A-Za-z0-9_-]+|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b/gu,
];

function redact(value) {
  return secretPatterns.reduce(
    (result, pattern) => result.replace(pattern, "$1=[redacted]"),
    value,
  );
}

function run(command, args, { display = false, allowFailure = false, env = {} } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      env: { ...process.env, SUPABASE_TELEMETRY_DISABLED: "1", ...env },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout = `${stdout}${chunk}`.slice(-200_000);
      if (display) process.stdout.write(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr = `${stderr}${chunk}`.slice(-20_000);
    });
    child.on("error", reject);
    child.on("close", (status) => {
      if (status === 0 || allowFailure) {
        resolve({ status, stdout: stdout.trim(), stderr: stderr.trim() });
        return;
      }
      reject(new Error(redact(`${command} failed with status ${status}\n${stdout}\n${stderr}`.trim())));
    });
  });
}

function parseStatusEnv(output) {
  const values = {};
  for (const line of output.split(/\r?\n/u)) {
    const match = line.match(/^([A-Z][A-Z0-9_]*)=(.*)$/u);
    if (!match) continue;
    const [, key, rawValue] = match;
    let value = rawValue.trim();
    if (value.startsWith('"') && value.endsWith('"')) {
      value = JSON.parse(value);
    } else if (value.startsWith("'") && value.endsWith("'")) {
      value = value.slice(1, -1).replaceAll("'\\''", "'");
    }
    values[key] = value;
  }
  return values;
}

async function cleanup() {
  await run(
    "supabase",
    ["stop", "--no-backup", "--project-id", projectId],
    { allowFailure: true },
  );
  await run("docker", ["network", "rm", network], { allowFailure: true });
}

console.log("Preparing an isolated local Supabase migration/RLS/storage rehearsal...");
await cleanup();

let passed = false;
try {
  await run("docker", [
    "network",
    "create",
    "--opt",
    "com.docker.network.bridge.host_binding_ipv4=127.0.0.1",
    network,
  ]);
  await run("supabase", [
    "start",
    "--network-id",
    network,
    "--exclude",
    excludedServices,
  ], { env: { COMPOSE_PARALLEL_LIMIT: "1" } });

  const status = await run("supabase", ["status", "--output", "env"]);
  const local = parseStatusEnv(status.stdout);
  for (const key of ["API_URL", "ANON_KEY", "SERVICE_ROLE_KEY"]) {
    if (!local[key]) throw new Error(`Supabase status did not return ${key}`);
  }

  console.log("Local services are ready; exercising all migrations and tenant/storage policies...");
  await run("npm", ["run", "test:supabase"], {
    display: true,
    env: {
      SUPABASE_URL: local.API_URL,
      SUPABASE_ANON_KEY: local.ANON_KEY,
      SUPABASE_SERVICE_ROLE_KEY: local.SERVICE_ROLE_KEY,
    },
  });
  passed = true;
} finally {
  await cleanup();
}
if (passed) {
  console.log("Local Supabase rehearsal passed; disposable services and data were removed.");
}
