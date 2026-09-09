// Fixed, credential-free subprocess for the frozen #152/#153 statutory generators.
import { buildAnnualAccountsPayload } from "../apps/web/app/lib/annual-accounts.ts";
import { renderAnnualAccountsXml } from "../apps/web/app/lib/annual-accounts-xml.ts";
import { buildCompanyTaxReturnPayload } from "../apps/web/app/lib/company-tax-return.ts";
import { renderCompanyTaxReturnXml } from "../apps/web/app/lib/company-tax-return-xml.ts";
import { renderCompanyTaxReturnEnvelope, renderCompanyTaxReturnValidationEnvelope,
  summarizeCompanyTaxReturnValidation } from "../apps/web/app/lib/company-tax-return-authority-payload.ts";

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
    case "company_tax": {
      const payload = buildCompanyTaxReturnPayload(value);
      const blocking = payload.feedback.filter((item) => item.level === "block");
      if (blocking.length) throw new Error("payload_blocked");
      return { ...renderCompanyTaxReturnXml(payload.fields), feedback: payload.feedback };
    }
    case "company_tax_envelope": return { envelopeXml: renderCompanyTaxReturnEnvelope(value) };
    case "company_tax_validation_envelope": return { envelopeXml: renderCompanyTaxReturnValidationEnvelope(value) };
    case "company_tax_validation_summary": return summarizeCompanyTaxReturnValidation(value.resultXml);
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
