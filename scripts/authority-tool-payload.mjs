// Fixed, credential-free annual-accounts subprocess until its #153 migration.
import { buildAnnualAccountsPayload } from "../apps/web/app/lib/annual-accounts.ts";
import { renderAnnualAccountsXml } from "../apps/web/app/lib/annual-accounts-xml.ts";

export function authorityToolPayload(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)
    || Object.keys(input).some((key) => !["operation", "input"].includes(key))) throw new Error("payload_invalid");
  const value = input.input;
  switch (input.operation) {
    case "annual_accounts": {
      const payload = buildAnnualAccountsPayload({ incomeYear: value.incomeYear,
        annualData: value.annualData, ledgerEntries: value.ledgerEntries ?? [] });
      return { ...renderAnnualAccountsXml({ payload, companyOrgNumber: value.companyOrgNumber,
        companyName: value.companyName, contactEmail: value.contactEmail,
        approvalDate: value.approvalDate, confirmingRepresentative: value.confirmingRepresentative }),
      feedback: payload.feedback };
    }
    default: throw new Error("payload_operation_invalid");
  }
}

if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  try {
    let size = 0;
    const chunks = [];
    for await (const chunk of process.stdin) {
      size += chunk.length;
      if (size > 8 * 1024 * 1024) throw new Error("payload_too_large");
      chunks.push(chunk);
    }
    const result = authorityToolPayload(JSON.parse(Buffer.concat(chunks).toString("utf8")));
    process.stdout.write(JSON.stringify(result));
  } catch {
    process.stderr.write("authority_tool_payload_failed\n");
    process.exitCode = 1;
  }
}
