import path from "node:path";

import { createAnnualAccountsFileJournal } from "../app/lib/annual-accounts-file-journal.ts";
import { inspectAnnualAccountsProgress } from "../app/lib/annual-accounts-orchestration.ts";
import {
  loadPrivateAnnualAccountsMaskinportenKey,
  loadPrivateAnnualAccountsTt02Input,
  runAnnualAccountsTt02Step,
  validateAnnualAccountsTt02Target,
  verifyAnnualAccountsTt02SignedInstance,
} from "../app/lib/annual-accounts-tt02-runner.ts";

function usage(): never {
  throw new Error(
    "Usage: annual-accounts-tt02.ts <inspect|step|verify-signed> --input <private-json> --journal <private-dir> --customer-org <9 digits> --income-year <year> [--client-id <uuid> --key-id <uuid> --private-key <pem> --execute-test] [--lock for step only]",
  );
}

function parseArguments(values: string[]) {
  const action = values.shift();
  if (action !== "inspect" && action !== "step" && action !== "verify-signed") usage();
  const options = new Map<string, string | true>();
  const booleanFlags = new Set(["--execute-test", "--lock"]);
  while (values.length) {
    const flag = values.shift() as string;
    if (!flag.startsWith("--") || options.has(flag)) usage();
    if (booleanFlags.has(flag)) {
      options.set(flag, true);
      continue;
    }
    const value = values.shift();
    if (!value || value.startsWith("--")) usage();
    options.set(flag, value);
  }
  const allowed = new Set([
    "--input",
    "--journal",
    "--customer-org",
    "--income-year",
    "--client-id",
    "--key-id",
    "--private-key",
    "--execute-test",
    "--lock",
  ]);
  if ([...options.keys()].some((key) => !allowed.has(key))) usage();
  if (
    action === "inspect" &&
    ["--client-id", "--key-id", "--private-key", "--execute-test", "--lock"].some((key) => options.has(key))
  ) {
    usage();
  }
  if (action !== "step" && options.has("--lock")) usage();
  return { action, options };
}

function required(options: Map<string, string | true>, name: string) {
  const value = options.get(name);
  if (typeof value !== "string") usage();
  return value;
}

async function main() {
  const { action, options } = parseArguments(process.argv.slice(2));
  const inputPath = path.resolve(required(options, "--input"));
  const journalPath = path.resolve(required(options, "--journal"));
  const customerOrgNumber = required(options, "--customer-org");
  const incomeYear = Number(required(options, "--income-year"));
  const loaded = await loadPrivateAnnualAccountsTt02Input(inputPath);
  const summary = validateAnnualAccountsTt02Target(loaded, customerOrgNumber, incomeYear);
  const journal = createAnnualAccountsFileJournal(journalPath);
  const progress = await inspectAnnualAccountsProgress({ documents: loaded.documents, journal });

  if (action === "inspect") {
    process.stdout.write(`${JSON.stringify({ environment: "test", summary, progress }, null, 2)}\n`);
    return;
  }
  if (options.get("--execute-test") !== true) {
    throw new Error("TT02 annual-accounts access is disabled unless --execute-test is supplied.");
  }
  const credentials = {
    loaded,
    journal,
    clientId: required(options, "--client-id"),
    keyId: required(options, "--key-id"),
    customerOrgNumber,
    incomeYear,
    privateKeyPem: await loadPrivateAnnualAccountsMaskinportenKey(
      path.resolve(required(options, "--private-key")),
    ),
  };
  const output = action === "verify-signed"
    ? await verifyAnnualAccountsTt02SignedInstance(credentials)
    : await runAnnualAccountsTt02Step({
      ...credentials,
      allowLock: options.get("--lock") === true,
    });
  process.stdout.write(`${JSON.stringify({ environment: "test", ...output }, null, 2)}\n`);
}

main().catch((error) => {
  const code = error && typeof error === "object" && "code" in error
    ? String(error.code)
    : "annual_accounts_tt02_runner_failed";
  const message = error instanceof Error ? error.message : "TT02 annual-accounts runner failed.";
  process.stderr.write(`${JSON.stringify({ code, message })}\n`);
  process.exitCode = 1;
});
