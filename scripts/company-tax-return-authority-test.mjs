import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

import { buildCompanyTaxReturnPayload } from "../app/lib/company-tax-return.ts";
import { renderCompanyTaxReturnXml } from "../app/lib/company-tax-return-xml.ts";
import {
  CompanyTaxReturnAuthorityError,
  createCompanyTaxReturnAuthorityClient,
  renderCompanyTaxReturnValidationEnvelope,
  summarizeCompanyTaxReturnValidation,
} from "../app/lib/company-tax-return-authority-client.ts";
import { requestMaskinportenToken } from "../app/lib/maskinporten.ts";

process.umask(0o077);

const COMPANY_TAX_SCOPE = "skatteetaten:formueinntekt/skattemelding";
const REQUIRED_SCHEMAS = [
  "skattemeldingUpersonlig_v5_ekstern.xsd",
  "naeringsspesifikasjon_v6_ekstern.xsd",
  "skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd",
];

function required(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function gitCommit() {
  const result = spawnSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : "unknown";
}

function validateDocument(schemaPath, documentPath) {
  const result = spawnSync("xmllint", ["--noout", "--schema", schemaPath, documentPath], {
    encoding: "utf8",
    maxBuffer: 2 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Local company-tax XML validation failed: ${(result.stderr || result.stdout).trim().slice(0, 1000)}`);
  }
}

async function writeJsonAtomic(path, value) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  await rename(temporary, path);
}

async function validateLocally(xsdDirectory, documents) {
  const directory = await mkdtemp(join(tmpdir(), "talli-company-tax-authority-"));
  try {
    const documentPaths = {
      "skattemeldingUpersonlig_v5_ekstern.xsd": join(directory, "skattemelding.xml"),
      "naeringsspesifikasjon_v6_ekstern.xsd": join(directory, "naeringsspesifikasjon.xml"),
      "skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd": join(directory, "envelope.xml"),
    };
    await Promise.all([
      writeFile(documentPaths[REQUIRED_SCHEMAS[0]], documents.skattemeldingXml, { mode: 0o600 }),
      writeFile(documentPaths[REQUIRED_SCHEMAS[1]], documents.naeringsspesifikasjonXml, { mode: 0o600 }),
      writeFile(documentPaths[REQUIRED_SCHEMAS[2]], documents.envelopeXml, { mode: 0o600 }),
    ]);
    for (const schema of REQUIRED_SCHEMAS) {
      validateDocument(join(xsdDirectory, schema), documentPaths[schema]);
    }
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

async function main() {
  if (required("TALLI_COMPANY_TAX_APPROVED_TEST_VALIDATION") !== "true") {
    throw new Error("TALLI_COMPANY_TAX_APPROVED_TEST_VALIDATION must be exactly true.");
  }
  if (required("TALLI_MASKINPORTEN_ENVIRONMENT") !== "test") {
    throw new Error("The company-tax authority rehearsal refuses every environment except test.");
  }
  const scope = required("TALLI_MASKINPORTEN_SCOPE");
  if (scope !== COMPANY_TAX_SCOPE) {
    throw new Error(`The company-tax authority rehearsal requires scope ${COMPANY_TAX_SCOPE}.`);
  }

  const casePath = resolve(required("TALLI_COMPANY_TAX_CASE_PATH"));
  const evidencePath = resolve(required("TALLI_COMPANY_TAX_EVIDENCE_PATH"));
  const xsdDirectory = resolve(required("TALLI_SKATTE_XSD_DIR"));
  const caseData = JSON.parse(await readFile(casePath, "utf8"));
  const companyOrgNumber = String(caseData.company?.orgNumber ?? "");
  const companyName = String(caseData.company?.name ?? "");
  const incomeYear = Number(caseData.company?.incomeYear);
  const systemUserOrgNumber = required("TALLI_MASKINPORTEN_SYSTEM_USER_ORG");
  if (!/^\d{9}$/u.test(companyOrgNumber) || !Number.isInteger(incomeYear)) {
    throw new Error("Company-tax authority case identity is invalid.");
  }
  if (companyOrgNumber !== systemUserOrgNumber) {
    throw new Error("Company-tax case organization must equal the Maskinporten system-user organization.");
  }
  if (caseData.annualData?.no_activity_confirmed !== true
    || caseData.holdingActions?.length !== 0
    || caseData.ledgerEntries?.some((entry) => entry?.entry_type !== "opening_balance")) {
    throw new Error("Company-tax authority rehearsal is currently limited to the approved no-activity case.");
  }

  const payload = buildCompanyTaxReturnPayload({
    companyOrgNumber,
    incomeYear,
    annualData: caseData.annualData,
    ledgerEntries: caseData.ledgerEntries ?? [],
    holdingActions: caseData.holdingActions ?? [],
  });
  const blockingCodes = payload.feedback.filter((item) => item.level === "block").map((item) => item.code);
  if (blockingCodes.length) {
    throw new Error(`Company-tax payload is blocked: ${blockingCodes.join(", ")}`);
  }
  const documents = renderCompanyTaxReturnXml(payload.fields);
  const envelopeXml = renderCompanyTaxReturnValidationEnvelope({
    ...documents,
    companyOrgNumber,
    incomeYear,
    createdBy: "Talli",
  });
  await validateLocally(xsdDirectory, { ...documents, envelopeXml });

  const privateKeyPath = resolve(required("TALLI_MASKINPORTEN_PRIVATE_KEY_PATH"));
  const keyStats = await stat(privateKeyPath);
  if (!keyStats.isFile() || (keyStats.mode & 0o077) !== 0) {
    throw new Error("Maskinporten private-key file must be a mode-0600 regular file.");
  }
  const token = await requestMaskinportenToken({
    environment: "test",
    clientId: required("TALLI_MASKINPORTEN_CLIENT_ID"),
    keyId: required("TALLI_MASKINPORTEN_KEY_ID"),
    privateKeyPem: await readFile(privateKeyPath, "utf8"),
    scope,
    systemUserOrgNumber,
    systemUserExternalRef: required("TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF"),
  });
  const client = createCompanyTaxReturnAuthorityClient({
    environment: "test",
    taxAccessToken: token.accessToken,
  });
  const response = await client.validateTest({ companyOrgNumber, incomeYear, envelopeXml });
  const validation = summarizeCompanyTaxReturnValidation(response.resultXml);
  const evidence = {
    schemaVersion: 1,
    status: validation.result === "validertOK" ? "validated" : "rejected",
    environment: "test",
    authority: "Skatteetaten skattemelding v2 validertest",
    companyOrgNumber,
    companyName,
    incomeYear,
    scope,
    caseFixture: basename(casePath),
    codeCommit: gitCommit(),
    payloadHashes: {
      skattemelding: sha256(documents.skattemeldingXml),
      naeringsspesifikasjon: sha256(documents.naeringsspesifikasjonXml),
      envelope: sha256(envelopeXml),
    },
    payloadFeedbackCodes: payload.feedback.map((item) => item.code).sort(),
    localSchemaValidation: { status: "passed", schemas: REQUIRED_SCHEMAS },
    authorityValidation: validation,
    responseBytes: Buffer.byteLength(response.resultXml, "utf8"),
    secretsStored: false,
    validatedAt: new Date().toISOString(),
  };
  await writeJsonAtomic(evidencePath, evidence);
  console.log(JSON.stringify({
    ok: validation.result === "validertOK",
    status: evidence.status,
    environment: evidence.environment,
    companyOrgNumber,
    incomeYear,
    result: validation.result,
    deviationCodes: validation.deviationCodes,
    guidanceCodes: validation.guidanceCodes,
    evidencePath,
  }));
  if (validation.result !== "validertOK") {
    throw new Error("Skatteetaten validertest did not accept the company-tax payload.");
  }
}

main().catch((error) => {
  const output = error instanceof CompanyTaxReturnAuthorityError
    ? {
      ok: false,
      code: error.code,
      status: error.status,
      correlationId: error.correlationId,
      retryable: error.retryable,
      message: error.message,
    }
    : {
      ok: false,
      code: "local_configuration_or_payload_error",
      status: null,
      message: error instanceof Error ? error.message : "Unknown error.",
    };
  console.error(JSON.stringify(output));
  process.exitCode = 1;
});
