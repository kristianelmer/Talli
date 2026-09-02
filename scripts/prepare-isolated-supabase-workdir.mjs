import { cpSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { basename, join, resolve } from "node:path";

const target = resolve(process.argv[2] ?? "");
if (!basename(target).startsWith("talli-supabase-local.")) {
  throw new Error("Expected an isolated talli-supabase-local.* workdir.");
}

const allocatePort = () => new Promise((resolvePort, reject) => {
  const server = createServer();
  server.unref();
  server.once("error", reject);
  server.listen(0, "127.0.0.1", () => {
    const address = server.address();
    if (!address || typeof address === "string") {
      server.close();
      reject(new Error("Could not allocate an isolated Supabase port."));
      return;
    }
    server.close((error) => error ? reject(error) : resolvePort(address.port));
  });
});

const ports = await Promise.all(Array.from({ length: 8 }, allocatePort));
const source = realpathSync(resolve("supabase"));
cpSync(source, join(target, "supabase"), { recursive: true });

const configPath = join(target, "supabase", "config.toml");
let config = readFileSync(configPath, "utf8");
const replacements = new Map([
  ['project_id = "talli"', `project_id = "tallig${process.pid}"`],
  ["port = 54321", `port = ${ports[0]}`],
  ["port = 54322", `port = ${ports[1]}`],
  ["shadow_port = 54320", `shadow_port = ${ports[2]}`],
  ["port = 54329", `port = ${ports[3]}`],
  ["port = 54323", `port = ${ports[4]}`],
  ["port = 54324", `port = ${ports[5]}`],
  ["inspector_port = 8083", `inspector_port = ${ports[6]}`],
  ["port = 54327", `port = ${ports[7]}`],
]);
for (const [original, replacement] of replacements) {
  if (!config.includes(original)) {
    throw new Error(`Missing expected Supabase config value: ${original}`);
  }
  config = config.replace(original, replacement);
}
writeFileSync(configPath, config);
