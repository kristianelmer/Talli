import path from "node:path";

import { createRf1086FileJournal } from "../app/lib/rf1086-file-journal.ts";
import { inspectRf1086AuthorityProgress } from "../app/lib/rf1086-authority-orchestration.ts";
import {
  loadPrivateMaskinportenKey,
  loadPrivateRf1086Tt02Preview,
  runRf1086Tt02Step,
  validateRf1086Tt02PreviewTarget,
} from "../app/lib/rf1086-tt02-runner.ts";

function usage(): never {
  throw new Error(
    "Usage: rf1086-tt02.ts <inspect|step> --preview <private-json> --journal <private-dir> --customer-org <9 digits> [--client-id <uuid> --key-id <uuid> --private-key <pem> --execute-test] [--confirm]",
  );
}

function parseArguments(values: string[]) {
  const action = values.shift();
  if (action !== "inspect" && action !== "step") usage();
  const options = new Map<string, string | true>();
  const booleanFlags = new Set(["--execute-test", "--confirm"]);
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
    "--preview",
    "--journal",
    "--customer-org",
    "--client-id",
    "--key-id",
    "--private-key",
    "--execute-test",
    "--confirm",
  ]);
  if ([...options.keys()].some((key) => !allowed.has(key))) usage();
  return { action, options };
}

function required(options: Map<string, string | true>, name: string) {
  const value = options.get(name);
  if (typeof value !== "string") usage();
  return value;
}

async function main() {
  const { action, options } = parseArguments(process.argv.slice(2));
  const previewPath = path.resolve(required(options, "--preview"));
  const journalPath = path.resolve(required(options, "--journal"));
  const customerOrgNumber = required(options, "--customer-org");
  const preview = await loadPrivateRf1086Tt02Preview(previewPath);
  const summary = validateRf1086Tt02PreviewTarget(preview, customerOrgNumber);
  const journal = createRf1086FileJournal(journalPath);
  const progress = await inspectRf1086AuthorityProgress({ preview, environment: "test", journal });

  if (action === "inspect") {
    process.stdout.write(`${JSON.stringify({ environment: "test", summary, progress }, null, 2)}\n`);
    return;
  }
  if (options.get("--execute-test") !== true) {
    throw new Error("TT02 write is disabled unless --execute-test is supplied.");
  }
  const privateKeyPem = await loadPrivateMaskinportenKey(path.resolve(required(options, "--private-key")));
  const output = await runRf1086Tt02Step({
    preview,
    journal,
    clientId: required(options, "--client-id"),
    keyId: required(options, "--key-id"),
    customerOrgNumber,
    privateKeyPem,
    allowConfirm: options.get("--confirm") === true,
  });
  process.stdout.write(`${JSON.stringify({ environment: "test", ...output }, null, 2)}\n`);
}

main().catch((error) => {
  const code = error && typeof error === "object" && "code" in error ? String(error.code) : "rf1086_tt02_runner_failed";
  const message = error instanceof Error ? error.message : "TT02 runner failed.";
  process.stderr.write(`${JSON.stringify({ code, message })}\n`);
  process.exitCode = 1;
});
