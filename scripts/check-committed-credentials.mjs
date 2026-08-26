import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

const repositoryRoot = resolve(
  process.argv[2] ?? fileURLToPath(new URL("..", import.meta.url)),
);
const credentialPattern = [
  ["BEGIN ", "(RSA |EC )?", "PRIVATE KEY"].join(""),
  ["go", "keyring", "base64:"].join("-"),
  ["eyJ", "hbGciOi", "[A-Za-z0-9_-]+\\."].join(""),
].join("|");
const result = spawnSync(
  "git",
  [
    "-C",
    repositoryRoot,
    "grep",
    "-I",
    "-n",
    "-E",
    credentialPattern,
    "--",
    ".",
    ":!docs/**",
    ":!tests/**",
  ],
  { encoding: "utf8" },
);

if (result.status === 0) {
  process.stdout.write(result.stdout);
  process.stderr.write(result.stderr);
  process.exitCode = 1;
} else if (result.status !== 1) {
  process.stderr.write(result.stderr || "Credential scan could not inspect the repository.\n");
  process.exitCode = result.status ?? 1;
}
