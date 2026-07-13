import { lstat, readFile } from "node:fs/promises";
import path from "node:path";

import {
  inspectCurrentCompanyTaxReturnTt02,
  runNoActivityCompanyTaxReturnTt02Calculation,
} from "../app/lib/company-tax-return-tt02-runner.ts";
import { createCompanyTaxReturnTt02FileJournal } from "../app/lib/company-tax-return-tt02-journal.ts";
import { loadPrivateMaskinportenKey } from "../app/lib/rf1086-tt02-runner.ts";

const MAX_FIXTURE_BYTES = 10 * 1024 * 1024;

function usage(): never {
  throw new Error(
    "Usage: company-tax-return-tt02.ts <inspect-current|calculate-no-activity> [--tax-return <xml>] --customer-org <9 digits> --income-year 2025 --client-id <uuid> --key-id <uuid> --private-key <pem> --journal <private-directory> --execute-test",
  );
}

function parseArguments(values: string[]) {
  const action = values.shift();
  if (action !== "inspect-current" && action !== "calculate-no-activity") usage();
  const options = new Map<string, string | true>();
  while (values.length) {
    const flag = values.shift() as string;
    if (!flag.startsWith("--") || options.has(flag)) usage();
    if (flag === "--execute-test") {
      options.set(flag, true);
      continue;
    }
    const value = values.shift();
    if (!value || value.startsWith("--")) usage();
    options.set(flag, value);
  }
  const allowed = new Set([
    "--tax-return",
    "--customer-org",
    "--income-year",
    "--client-id",
    "--key-id",
    "--private-key",
    "--journal",
    "--execute-test",
  ]);
  if ([...options.keys()].some((key) => !allowed.has(key))) usage();
  if ((action === "calculate-no-activity") !== options.has("--tax-return")) usage();
  return { action, options };
}

function required(options: Map<string, string | true>, name: string) {
  const value = options.get(name);
  if (typeof value !== "string") usage();
  return value;
}

async function readFixture(filePathInput: string) {
  const filePath = path.resolve(filePathInput);
  const metadata = await lstat(filePath);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size < 1 || metadata.size > MAX_FIXTURE_BYTES) {
    throw new Error("TT02 tax-return fixture must be a bounded regular file.");
  }
  return readFile(filePath, "utf8");
}

async function main() {
  const { action, options } = parseArguments(process.argv.slice(2));
  if (options.get("--execute-test") !== true) {
    throw new Error("TT02 external calculation is disabled unless --execute-test is supplied.");
  }
  const incomeYear = Number(required(options, "--income-year"));
  const journal = createCompanyTaxReturnTt02FileJournal(path.resolve(required(options, "--journal")));
  const credentials = {
    clientId: required(options, "--client-id"),
    keyId: required(options, "--key-id"),
    customerOrgNumber: required(options, "--customer-org"),
    incomeYear,
    privateKeyPem: await loadPrivateMaskinportenKey(path.resolve(required(options, "--private-key"))),
    journal,
  };
  const output = action === "inspect-current"
    ? await inspectCurrentCompanyTaxReturnTt02(credentials)
    : await runNoActivityCompanyTaxReturnTt02Calculation({
        ...credentials,
        contractTaxReturnXml: await readFixture(required(options, "--tax-return")),
      });
  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
}

main().catch((error) => {
  const code = error && typeof error === "object" && "code" in error
    ? String(error.code)
    : "company_tax_return_tt02_runner_failed";
  const message = error instanceof Error ? error.message : "TT02 company-tax-return runner failed.";
  process.stderr.write(`${JSON.stringify({ code, message })}\n`);
  process.exitCode = 1;
});
