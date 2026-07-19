import { readFile, stat } from "node:fs/promises";

import {
  MaskinportenTokenError,
  requestMaskinportenToken,
  summarizeMaskinportenToken,
} from "../app/lib/maskinporten.ts";

function required(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

async function main() {
  const environment = required("TALLI_MASKINPORTEN_ENVIRONMENT");
  if (environment !== "test" && environment !== "production") {
    throw new Error("TALLI_MASKINPORTEN_ENVIRONMENT must be test or production.");
  }
  const privateKeyPath = required("TALLI_MASKINPORTEN_PRIVATE_KEY_PATH");
  const keyStats = await stat(privateKeyPath);
  if (!keyStats.isFile()) throw new Error("Maskinporten private-key path must be a regular file.");
  if ((keyStats.mode & 0o077) !== 0) {
    throw new Error("Maskinporten private-key file must not be readable or writable by group/others.");
  }

  const token = await requestMaskinportenToken({
    environment,
    clientId: required("TALLI_MASKINPORTEN_CLIENT_ID"),
    keyId: required("TALLI_MASKINPORTEN_KEY_ID"),
    privateKeyPem: await readFile(privateKeyPath, "utf8"),
    scope: required("TALLI_MASKINPORTEN_SCOPE"),
    systemUserOrgNumber: required("TALLI_MASKINPORTEN_SYSTEM_USER_ORG"),
    systemUserExternalRef: process.env.TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF?.trim() || undefined,
  });

  console.log(JSON.stringify({ ok: true, ...summarizeMaskinportenToken(token) }));
}

main().catch((error) => {
  const output = error instanceof MaskinportenTokenError
    ? { ok: false, code: error.code, status: error.status, message: error.message }
    : { ok: false, code: "local_configuration_error", status: null, message: error instanceof Error ? error.message : "Unknown error." };
  console.error(JSON.stringify(output));
  process.exitCode = 1;
});
