import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { loadEnvFile } from "node:process";

const command = process.argv[2];
if (!["build", "dev", "start"].includes(command)) {
  throw new Error("Expected one of: build, dev, start");
}

if (existsSync(".env")) {
  loadEnvFile(".env");
}

const requireFromWebPackage = createRequire(
  new URL("../package.json", import.meta.url),
);
const nextCli = requireFromWebPackage.resolve("next/dist/bin/next");

const child = spawn(
  process.execPath,
  [nextCli, command, "apps/web"],
  {
    env: process.env,
    stdio: "inherit",
  },
);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exitCode = code ?? 1;
  }
});
