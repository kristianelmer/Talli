/** Existing JS cross-output fixtures execute Accounts' canonical Python policy. */
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

const root = fileURLToPath(new URL("../..", import.meta.url));
const driver = fileURLToPath(new URL("./annual_accounts_public_driver.py", import.meta.url));
function invoke(operation, input) {
  const python = process.env.TALLI_PYTHON_BIN || resolve(root, "apps/backend/.venv/bin/python");
  const result = spawnSync(python, [driver], {
    cwd: root, input: JSON.stringify({ operation, input }), encoding: "utf8",
    timeout: 30_000, maxBuffer: 8 * 1024 * 1024,
    env: { PATH: process.env.PATH ?? "", LANG: "en_US.UTF-8", PYTHONPATH: resolve(root, "apps/backend/src") },
  });
  if (result.error || result.status !== 0) throw new Error("Annual Accounts public test driver failed", { cause: result.error });
  const response = JSON.parse(result.stdout);
  if (response.error) throw new Error(response.error);
  return response.value;
}
export const buildAnnualAccountsPayload = input => invoke("payload", input);
export const renderAnnualAccountsXml = input => invoke("render", input);
export const assessAnnualAccountsReadiness = input => invoke("readiness", input);
export const buildAnnualAccountsAuthorityTestRunFromEvidence = input => invoke("evidence", {
  ...input, recordedAt: input.recordedAt ?? new Date().toISOString(),
});
