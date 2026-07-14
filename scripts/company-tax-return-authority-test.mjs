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
  exchangeMaskinportenForAltinnToken,
  renderCompanyTaxReturnEnvelope,
  renderCompanyTaxReturnValidationEnvelope,
  summarizeCompanyTaxReturnValidation,
  waitForCompanyTaxReturnFeedback,
  waitForCompanyTaxReturnValidation,
} from "../app/lib/company-tax-return-authority-client.ts";
import { requestMaskinportenToken } from "../app/lib/maskinporten.ts";

process.umask(0o077);

const COMPANY_TAX_SCOPES = [
  "skatteetaten:formueinntekt/skattemelding",
  "altinn:instances.read",
  "altinn:instances.write",
];
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

function optional(name) {
  return process.env[name]?.trim() || undefined;
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

async function existingEvidence(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

function assertRequiredScopes(scope) {
  const actual = [...new Set(scope.split(" ").filter(Boolean))].sort();
  const expected = [...COMPANY_TAX_SCOPES].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`The company-tax authority rehearsal requires exactly ${COMPANY_TAX_SCOPES.join(" ")}.`);
  }
}

function assertSamePreparedCase(evidence, expected) {
  if (!evidence) return;
  const validationEnvelopeHash = evidence.payloadHashes?.validationEnvelope
    ?? evidence.payloadHashes?.envelope;
  if (
    evidence.environment !== "test"
    || evidence.productionEnabled !== false
    || evidence.companyOrgNumber !== expected.companyOrgNumber
    || evidence.incomeYear !== expected.incomeYear
    || evidence.payloadHashes?.skattemelding !== expected.payloadHashes.skattemelding
    || evidence.payloadHashes?.naeringsspesifikasjon !== expected.payloadHashes.naeringsspesifikasjon
    || validationEnvelopeHash !== expected.payloadHashes.validationEnvelope
  ) {
    throw new Error("Existing company-tax evidence belongs to a different payload; choose a new evidence path.");
  }
}

function assertResumableEvidence(evidence, systemUserOrgNumber) {
  if (!evidence || evidence.environment !== "test" || evidence.productionEnabled !== false) {
    throw new Error("Resume mode requires existing test-only company-tax evidence.");
  }
  if (evidence.companyOrgNumber !== systemUserOrgNumber || !/^\d{9}$/u.test(evidence.companyOrgNumber)) {
    throw new Error("Resume evidence organization must equal the Maskinporten system-user organization.");
  }
  if (!Number.isInteger(evidence.incomeYear) || !evidence.instance?.id) {
    throw new Error("Resume evidence is missing company-tax year or instance id.");
  }
  if (!["awaiting_person_confirmation", "submitted_and_receipted"].includes(evidence.status)) {
    throw new Error("Resume evidence is not awaiting person confirmation.");
  }
}

function safeSummary(evidence) {
  return {
    ok: ["awaiting_person_confirmation", "submitted_and_receipted"].includes(evidence.status),
    status: evidence.status,
    environment: evidence.environment,
    companyOrgNumber: evidence.companyOrgNumber,
    incomeYear: evidence.incomeYear,
    instanceId: evidence.instance?.id ?? null,
    validationResult: evidence.authorityValidation?.result ?? null,
    confirmationUrl: evidence.confirmationUrl ?? null,
    receiptReference: evidence.receipt?.reference ?? null,
    archiveReference: evidence.submission?.archiveReference ?? null,
    evidenceFile: evidence.evidenceFile,
  };
}

async function waitForCleanEnvelope(client, instanceId, attempts = 30) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const scan = await client.getEnvelopeScan({ instanceId });
    if (scan.fileScanResult === "Clean") return scan;
    if (attempt < attempts) await new Promise((resolveDelay) => setTimeout(resolveDelay, 2_000));
  }
  throw new CompanyTaxReturnAuthorityError(
    "Company tax envelope did not become clean within the polling window.",
    { code: "COMPANY_TAX_ENVELOPE_SCAN_TIMEOUT", retryable: true },
  );
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
  if (required("TALLI_COMPANY_TAX_APPROVED_TEST_WRITE") !== "true") {
    throw new Error("TALLI_COMPANY_TAX_APPROVED_TEST_WRITE must be exactly true.");
  }
  if (required("TALLI_MASKINPORTEN_ENVIRONMENT") !== "test") {
    throw new Error("The company-tax authority rehearsal refuses every environment except test.");
  }
  const mode = required("TALLI_COMPANY_TAX_REHEARSAL_MODE");
  if (mode !== "prepare" && mode !== "resume") {
    throw new Error("TALLI_COMPANY_TAX_REHEARSAL_MODE must be prepare or resume.");
  }
  const scope = required("TALLI_MASKINPORTEN_SCOPE");
  assertRequiredScopes(scope);
  const evidencePath = resolve(required("TALLI_COMPANY_TAX_EVIDENCE_PATH"));
  const systemUserOrgNumber = required("TALLI_MASKINPORTEN_SYSTEM_USER_ORG");
  const systemUserExternalRef = optional("TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF");
  if (!/^\d{9}$/u.test(systemUserOrgNumber)) {
    throw new Error("Maskinporten system-user organization must contain 9 digits.");
  }
  const prior = await existingEvidence(evidencePath);
  let evidence;

  if (mode === "prepare") {
    const casePath = resolve(required("TALLI_COMPANY_TAX_CASE_PATH"));
    const xsdDirectory = resolve(required("TALLI_SKATTE_XSD_DIR"));
    const caseData = JSON.parse(await readFile(casePath, "utf8"));
    const companyOrgNumber = String(caseData.company?.orgNumber ?? "");
    const companyName = String(caseData.company?.name ?? "");
    const incomeYear = Number(caseData.company?.incomeYear);
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
    const validationEnvelopeXml = renderCompanyTaxReturnValidationEnvelope({
      ...documents,
      companyOrgNumber,
      incomeYear,
      createdBy: "Talli",
    });
    await validateLocally(xsdDirectory, { ...documents, envelopeXml: validationEnvelopeXml });
    const payloadHashes = {
      skattemelding: sha256(documents.skattemeldingXml),
      naeringsspesifikasjon: sha256(documents.naeringsspesifikasjonXml),
      validationEnvelope: sha256(validationEnvelopeXml),
    };
    assertSamePreparedCase(prior, { companyOrgNumber, incomeYear, payloadHashes });
    if (prior?.status === "submitted_and_receipted") {
      prior.codeCommit = gitCommit();
      prior.evidenceFile = basename(evidencePath);
      await writeJsonAtomic(evidencePath, prior);
      console.log(JSON.stringify(safeSummary(prior)));
      return;
    }

    evidence = prior ?? {
      schemaVersion: 2,
      status: "prepared",
      environment: "test",
      productionEnabled: false,
      authority: "Skatteetaten company tax via Altinn TT02",
      companyOrgNumber,
      companyName,
      incomeYear,
      scope,
      systemUserResource: "app_skd_formueinntekt-skattemelding-v2",
      systemUserExternalRef: systemUserExternalRef ?? null,
      caseFixture: basename(casePath),
      evidenceFile: basename(evidencePath),
      codeCommit: gitCommit(),
      payloadHashes,
      payloadFeedbackCodes: payload.feedback.map((item) => item.code).sort(),
      localSchemaValidation: { status: "passed", schemas: REQUIRED_SCHEMAS },
      preflightValidation: null,
      authorityValidation: null,
      instance: null,
      confirmationUrl: null,
      receipt: null,
      submission: null,
      secretsStored: false,
      preparedAt: new Date().toISOString(),
      error: null,
    };
    if (evidence.schemaVersion === 1) {
      evidence.preflightValidation = evidence.authorityValidation ?? null;
      evidence.authorityValidation = null;
    }
    evidence.schemaVersion = 2;
    evidence.authority = "Skatteetaten company tax via Altinn TT02";
    evidence.scope = scope;
    evidence.systemUserResource = "app_skd_formueinntekt-skattemelding-v2";
    evidence.systemUserExternalRef = systemUserExternalRef ?? null;
    evidence.evidenceFile = basename(evidencePath);
    evidence.codeCommit = gitCommit();
    evidence.payloadHashes = {
      ...evidence.payloadHashes,
      ...payloadHashes,
    };
    delete evidence.evidencePath;
    await writeJsonAtomic(evidencePath, evidence);
    evidence.__prepareContext = { documents, payload, xsdDirectory };
  } else {
    assertResumableEvidence(prior, systemUserOrgNumber);
    evidence = prior;
    if (evidence.status === "submitted_and_receipted") {
      evidence.codeCommit = gitCommit();
      evidence.evidenceFile = basename(evidencePath);
      await writeJsonAtomic(evidencePath, evidence);
      console.log(JSON.stringify(safeSummary(evidence)));
      return;
    }
  }

  const privateKeyPath = resolve(required("TALLI_MASKINPORTEN_PRIVATE_KEY_PATH"));
  const keyStats = await stat(privateKeyPath);
  if (!keyStats.isFile() || (keyStats.mode & 0o077) !== 0) {
    throw new Error("Maskinporten private-key file must be a mode-0600 regular file.");
  }

  try {
    const token = await requestMaskinportenToken({
      environment: "test",
      clientId: required("TALLI_MASKINPORTEN_CLIENT_ID"),
      keyId: required("TALLI_MASKINPORTEN_KEY_ID"),
      privateKeyPem: await readFile(privateKeyPath, "utf8"),
      scope,
      systemUserOrgNumber,
      systemUserExternalRef,
    });
    const altinnToken = await exchangeMaskinportenForAltinnToken({
      environment: "test",
      maskinportenAccessToken: token.accessToken,
    });
    const client = createCompanyTaxReturnAuthorityClient({
      environment: "test",
      taxAccessToken: token.accessToken,
      altinnAccessToken: altinnToken,
    });

    if (mode === "resume") {
      const receipt = await waitForCompanyTaxReturnFeedback(client, {
        instanceId: evidence.instance.id,
      });
      const instance = await client.getInstance({ instanceId: evidence.instance.id });
      evidence.receipt = {
        dataId: receipt.dataId,
        dataType: receipt.dataType,
        contentType: receipt.contentType,
        byteLength: receipt.sizeBytes,
        contentSha256: sha256(receipt.receiptXml),
        reference: receipt.reference,
      };
      evidence.submission = {
        submitted: true,
        processTask: instance.processTask,
        processEndedAt: instance.processEndedAt,
        archived: instance.archived,
        archivedAt: instance.archivedAt,
        archiveReference: receipt.archiveReference,
      };
      evidence.status = "submitted_and_receipted";
      evidence.receiptRetrievedAt = new Date().toISOString();
      evidence.error = null;
      evidence.codeCommit = gitCommit();
      await writeJsonAtomic(evidencePath, evidence);
      console.log(JSON.stringify(safeSummary(evidence)));
      return;
    }

    const { documents, payload, xsdDirectory } = evidence.__prepareContext;
    delete evidence.__prepareContext;
    if (evidence.status === "awaiting_person_confirmation" || evidence.instance?.confirmationPrepared) {
      const prepared = await client.advanceToConfirmation({ instanceId: evidence.instance.id });
      evidence.instance.confirmationPrepared = true;
      evidence.instance.processTask = prepared.processTask;
      evidence.status = "awaiting_person_confirmation";
      evidence.confirmationUrl = client.getOwnerConfirmationUrl({ instanceId: evidence.instance.id });
      evidence.error = null;
      await writeJsonAtomic(evidencePath, evidence);
      console.log(JSON.stringify(safeSummary(evidence)));
      return;
    }

    const current = await client.fetchCurrent({
      incomeYear: evidence.incomeYear,
      companyOrgNumber: evidence.companyOrgNumber,
    });
    const envelopeXml = renderCompanyTaxReturnEnvelope({
      ...documents,
      currentDocumentReference: current.documentReference,
      companyOrgNumber: evidence.companyOrgNumber,
      incomeYear: evidence.incomeYear,
      createdBy: "Talli",
    });
    await validateLocally(xsdDirectory, { ...documents, envelopeXml });
    const submissionEnvelopeHash = sha256(envelopeXml);
    if (evidence.payloadHashes.submissionEnvelope
      && evidence.payloadHashes.submissionEnvelope !== submissionEnvelopeHash) {
      throw new Error("Current company-tax reference changed for an existing prepared instance.");
    }
    evidence.payloadHashes.submissionEnvelope = submissionEnvelopeHash;
    evidence.currentDocumentReferenceHash = sha256(current.documentReference);
    await writeJsonAtomic(evidencePath, evidence);

    if (!evidence.instance) {
      const created = await client.createInstance({
        incomeYear: evidence.incomeYear,
        companyOrgNumber: evidence.companyOrgNumber,
      });
      evidence.instance = {
        id: created.id,
        envelopeUploaded: false,
        envelopeDataId: null,
        validationJobId: null,
        confirmationPrepared: false,
        processTask: "data",
      };
      evidence.status = "instance_created";
      await writeJsonAtomic(evidencePath, evidence);
    }

    if (!evidence.instance.envelopeUploaded) {
      const instance = await client.getInstance({ instanceId: evidence.instance.id });
      const existing = instance.data.filter(
        (element) => element.dataType === "skattemeldingOgNaeringsspesifikasjon",
      );
      if (existing.length > 1) {
        throw new Error("Company-tax instance contains duplicate submission envelopes.");
      }
      if (existing.length === 1) {
        evidence.instance.envelopeUploaded = true;
        evidence.instance.envelopeDataId = existing[0].id;
      } else {
        const uploaded = await client.uploadEnvelope({
          instanceId: evidence.instance.id,
          envelopeXml,
        });
        evidence.instance.envelopeUploaded = true;
        evidence.instance.envelopeDataId = uploaded.dataId;
      }
      evidence.status = "envelope_uploaded";
      await writeJsonAtomic(evidencePath, evidence);
    }
    await waitForCleanEnvelope(client, evidence.instance.id);
    evidence.instance.fileScanResult = "Clean";
    evidence.status = "envelope_clean";
    await writeJsonAtomic(evidencePath, evidence);

    if (!evidence.instance.validationJobId) {
      const job = await client.startValidation({
        incomeYear: evidence.incomeYear,
        companyOrgNumber: evidence.companyOrgNumber,
        instanceId: evidence.instance.id,
      });
      evidence.instance.validationJobId = job.jobId;
      evidence.instance.validationJobStatus = job.status;
      evidence.status = "validation_started";
      await writeJsonAtomic(evidencePath, evidence);
    }
    const result = await waitForCompanyTaxReturnValidation(client, {
      incomeYear: evidence.incomeYear,
      companyOrgNumber: evidence.companyOrgNumber,
      jobId: evidence.instance.validationJobId,
    });
    const validation = summarizeCompanyTaxReturnValidation(result.resultXml);
    evidence.authorityValidation = validation;
    evidence.validationResponseBytes = Buffer.byteLength(result.resultXml, "utf8");
    evidence.validatedAt = new Date().toISOString();
    if (validation.result !== "validertOK") {
      evidence.status = "validation_failed";
      await writeJsonAtomic(evidencePath, evidence);
      throw new Error("Skatteetaten Altinn validation did not accept the company-tax payload.");
    }
    evidence.status = "validated";
    await writeJsonAtomic(evidencePath, evidence);

    const prepared = await client.advanceToConfirmation({ instanceId: evidence.instance.id });
    evidence.instance.confirmationPrepared = true;
    evidence.instance.processTask = prepared.processTask;
    evidence.status = "awaiting_person_confirmation";
    evidence.confirmationUrl = client.getOwnerConfirmationUrl({ instanceId: evidence.instance.id });
    evidence.confirmationPreparedAt = new Date().toISOString();
    evidence.error = null;
    await writeJsonAtomic(evidencePath, evidence);
    console.log(JSON.stringify(safeSummary(evidence)));
  } catch (error) {
    delete evidence.__prepareContext;
    if (evidence.status !== "awaiting_person_confirmation") {
      evidence.status = error instanceof CompanyTaxReturnAuthorityError && error.retryable
        ? "failed_retryable"
        : "failed_blocked";
    }
    evidence.error = error instanceof CompanyTaxReturnAuthorityError
      ? {
        code: error.code,
        status: error.status,
        correlationId: error.correlationId,
        retryable: error.retryable,
        message: error.message,
      }
      : {
        code: "COMPANY_TAX_LOCAL_OR_RESPONSE_ERROR",
        status: null,
        correlationId: null,
        retryable: false,
        message: error instanceof Error ? error.message : "Unknown error.",
      };
    await writeJsonAtomic(evidencePath, evidence);
    throw error;
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
