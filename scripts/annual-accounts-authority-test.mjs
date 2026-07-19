import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

import { buildAnnualAccountsPayload } from "../app/lib/annual-accounts.ts";
import { renderAnnualAccountsXml } from "../app/lib/annual-accounts-xml.ts";
import {
  AnnualAccountsAuthorityError,
  createAnnualAccountsAuthorityClient,
  exchangeMaskinportenForAnnualAccountsAltinnToken,
} from "../app/lib/annual-accounts-authority-client.ts";
import { requestMaskinportenToken } from "../app/lib/maskinporten.ts";

process.umask(0o077);

const ANNUAL_ACCOUNTS_SCOPE = "altinn:instances.read altinn:instances.write";

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

async function assertWellFormedXml(documents) {
  const directory = await mkdtemp(join(tmpdir(), "talli-annual-accounts-"));
  try {
    for (const [filename, xml] of Object.entries(documents)) {
      const path = join(directory, filename);
      await writeFile(path, xml, { mode: 0o600 });
      const result = spawnSync("xmllint", ["--noout", path], { encoding: "utf8" });
      if (result.error) throw result.error;
      if (result.status !== 0) {
        throw new Error(`Local RR0002 XML is not well formed: ${(result.stderr || result.stdout).trim().slice(0, 1000)}`);
      }
    }
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

function assertSamePreparedCase(evidence, expected) {
  if (!evidence) return;
  if (
    evidence.environment !== "test"
    || evidence.companyOrgNumber !== expected.companyOrgNumber
    || evidence.incomeYear !== expected.incomeYear
    || evidence.payloadHashes?.mainForm !== expected.payloadHashes.mainForm
    || evidence.payloadHashes?.companyAccounts !== expected.payloadHashes.companyAccounts
  ) {
    throw new Error("Existing annual-accounts evidence belongs to a different payload; choose a new evidence path.");
  }
}

function safeSummary(evidence) {
  return {
    ok: evidence.status === "locked_for_person_signing"
      || evidence.status === "submitted_and_archived",
    status: evidence.status,
    environment: evidence.environment,
    companyOrgNumber: evidence.companyOrgNumber,
    incomeYear: evidence.incomeYear,
    instanceId: evidence.instance?.id ?? null,
    validationIssueCodes: evidence.validation?.issues?.map((item) => item.code) ?? [],
    signingUrl: evidence.signingUrl ?? null,
    signed: evidence.signed === true,
    submitted: evidence.submitted === true,
    receiptReference: evidence.submission?.receipt?.reference ?? null,
    archiveReference: evidence.submission?.archiveReference ?? null,
    evidenceFile: evidence.evidenceFile,
  };
}

async function main() {
  if (required("TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE") !== "true") {
    throw new Error("TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE must be exactly true.");
  }
  if (required("TALLI_MASKINPORTEN_ENVIRONMENT") !== "test") {
    throw new Error("The annual-accounts authority rehearsal refuses every environment except test.");
  }
  const scope = required("TALLI_MASKINPORTEN_SCOPE");
  if (scope !== ANNUAL_ACCOUNTS_SCOPE) {
    throw new Error(`The annual-accounts authority rehearsal requires scope ${ANNUAL_ACCOUNTS_SCOPE}.`);
  }

  const casePath = resolve(required("TALLI_ANNUAL_ACCOUNTS_CASE_PATH"));
  const evidencePath = resolve(required("TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH"));
  const caseData = JSON.parse(await readFile(casePath, "utf8"));
  if (caseData.synthetic !== true || caseData.environment !== "test") {
    throw new Error("Annual-accounts authority rehearsal requires an explicitly synthetic test case.");
  }
  const companyOrgNumber = String(caseData.company?.orgNumber ?? "");
  const companyName = String(caseData.company?.name ?? "");
  const incomeYear = Number(caseData.company?.incomeYear);
  const systemUserOrgNumber = required("TALLI_MASKINPORTEN_SYSTEM_USER_ORG");
  if (!/^\d{9}$/u.test(companyOrgNumber) || !Number.isInteger(incomeYear)) {
    throw new Error("Annual-accounts authority case identity is invalid.");
  }
  if (companyOrgNumber !== systemUserOrgNumber) {
    throw new Error("Annual-accounts case organization must equal the Maskinporten system-user organization.");
  }

  const payload = buildAnnualAccountsPayload({
    incomeYear,
    annualData: caseData.annualData,
    ledgerEntries: caseData.ledgerEntries ?? [],
  });
  const documents = renderAnnualAccountsXml({
    payload,
    companyOrgNumber,
    companyName,
    contactEmail: required("TALLI_ANNUAL_ACCOUNTS_CONTACT_EMAIL"),
    approvalDate: required("TALLI_ANNUAL_ACCOUNTS_APPROVAL_DATE"),
    confirmingRepresentative: required("TALLI_ANNUAL_ACCOUNTS_CONFIRMING_REPRESENTATIVE"),
  });
  await assertWellFormedXml({
    "hovedskjema.xml": documents.mainFormXml,
    "selskapsregnskap.xml": documents.companyAccountsXml,
  });
  const payloadHashes = {
    mainForm: sha256(documents.mainFormXml),
    companyAccounts: sha256(documents.companyAccountsXml),
  };

  const prior = await existingEvidence(evidencePath);
  assertSamePreparedCase(prior, { companyOrgNumber, incomeYear, payloadHashes });
  if (prior?.status === "submitted_and_archived") {
    prior.codeCommit = gitCommit();
    prior.evidenceFile = basename(evidencePath);
    delete prior.evidencePath;
    await writeJsonAtomic(evidencePath, prior);
    console.log(JSON.stringify(safeSummary(prior)));
    return;
  }

  const evidence = prior ?? {
    schemaVersion: 1,
    status: "prepared",
    environment: "test",
    productionEnabled: false,
    authority: "Brønnøysundregistrene RR0002 via Altinn TT02",
    companyOrgNumber,
    companyName,
    incomeYear,
    scope,
    systemUserResource: "app_brg_aarsregnskap-vanlig-202406",
    systemUserRequestId: process.env.TALLI_ANNUAL_ACCOUNTS_SYSTEM_USER_REQUEST_ID?.trim() || null,
    systemUserExternalRef: required("TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF"),
    caseFixture: basename(casePath),
    evidenceFile: basename(evidencePath),
    codeCommit: gitCommit(),
    payloadHashes,
    payloadFeedbackCodes: payload.feedback.map((item) => item.code).sort(),
    localXmlValidation: { status: "well_formed" },
    instance: null,
    validation: null,
    signingUrl: null,
    signed: false,
    submitted: false,
    submission: null,
    secretsStored: false,
    preparedAt: new Date().toISOString(),
    error: null,
  };
  evidence.codeCommit = gitCommit();
  evidence.evidenceFile = basename(evidencePath);
  delete evidence.evidencePath;
  await writeJsonAtomic(evidencePath, evidence);

  const privateKeyPath = resolve(required("TALLI_MASKINPORTEN_PRIVATE_KEY_PATH"));
  const keyStats = await stat(privateKeyPath);
  if (!keyStats.isFile() || (keyStats.mode & 0o077) !== 0) {
    throw new Error("Maskinporten private-key file must be a mode-0600 regular file.");
  }
  const maskinportenToken = await requestMaskinportenToken({
    environment: "test",
    clientId: required("TALLI_MASKINPORTEN_CLIENT_ID"),
    keyId: required("TALLI_MASKINPORTEN_KEY_ID"),
    privateKeyPem: await readFile(privateKeyPath, "utf8"),
    scope,
    systemUserOrgNumber,
    systemUserExternalRef: evidence.systemUserExternalRef,
  });
  const altinnToken = await exchangeMaskinportenForAnnualAccountsAltinnToken({
    environment: "test",
    maskinportenAccessToken: maskinportenToken.accessToken,
  });
  const client = createAnnualAccountsAuthorityClient({
    environment: "test",
    altinnAccessToken: altinnToken,
  });

  try {
    if (evidence.status === "locked_for_person_signing") {
      const submission = await client.getSubmissionEvidence({
        instanceId: evidence.instance.id,
      });
      evidence.submission = submission;
      evidence.signed = submission.signed;
      evidence.submitted = submission.submitted;
      evidence.status = submission.submitted
        ? "submitted_and_archived"
        : "locked_for_person_signing";
      evidence.submittedAt = submission.submitted
        ? submission.processEndedAt
        : null;
      evidence.error = null;
      await writeJsonAtomic(evidencePath, evidence);
      console.log(JSON.stringify(safeSummary(evidence)));
      return;
    }

    if (!evidence.instance) {
      const created = await client.createInstance({ companyOrgNumber });
      evidence.instance = {
        id: created.id,
        dataIds: created.dataIds,
        createdProcessTask: created.processTask,
        mainFormUploaded: false,
        companyAccountsUploaded: false,
        locked: false,
      };
      evidence.status = "instance_created";
      await writeJsonAtomic(evidencePath, evidence);
    }
    if (!evidence.instance.mainFormUploaded) {
      await client.uploadMainForm({
        instanceId: evidence.instance.id,
        dataId: evidence.instance.dataIds.mainForm,
        xml: documents.mainFormXml,
      });
      evidence.instance.mainFormUploaded = true;
      evidence.status = "main_form_uploaded";
      await writeJsonAtomic(evidencePath, evidence);
    }
    if (!evidence.instance.companyAccountsUploaded) {
      await client.uploadCompanyAccounts({
        instanceId: evidence.instance.id,
        dataId: evidence.instance.dataIds.companyAccounts,
        xml: documents.companyAccountsXml,
      });
      evidence.instance.companyAccountsUploaded = true;
      evidence.status = "company_accounts_uploaded";
      await writeJsonAtomic(evidencePath, evidence);
    }
    const validation = await client.validateInstance({ instanceId: evidence.instance.id });
    evidence.validation = validation;
    evidence.validatedAt = new Date().toISOString();
    if (validation.hasErrors) {
      evidence.status = "validation_failed";
      await writeJsonAtomic(evidencePath, evidence);
      throw new Error(`Altinn RR0002 validation failed: ${validation.issues.map((item) => item.code).join(", ")}.`);
    }
    evidence.status = "validated";
    await writeJsonAtomic(evidencePath, evidence);

    if (!evidence.instance.locked) {
      const locked = await client.lockForSigning({ instanceId: evidence.instance.id });
      evidence.instance.locked = true;
      evidence.instance.lockedProcessTask = locked.processTask;
      evidence.status = "locked";
      await writeJsonAtomic(evidencePath, evidence);
    }
    const handoff = await client.getSigningHandoff({ instanceId: evidence.instance.id });
    evidence.signingUrl = handoff.signingUrl;
    evidence.signed = false;
    evidence.submitted = false;
    evidence.status = "locked_for_person_signing";
    evidence.lockedAt = new Date().toISOString();
    evidence.error = null;
    await writeJsonAtomic(evidencePath, evidence);
    console.log(JSON.stringify(safeSummary(evidence)));
  } catch (error) {
    if (evidence.status !== "validation_failed") {
      evidence.status = error instanceof AnnualAccountsAuthorityError && error.retryable
        ? "failed_retryable"
        : "failed_blocked";
    }
    evidence.error = error instanceof AnnualAccountsAuthorityError
      ? {
        code: error.code,
        status: error.status,
        correlationId: error.correlationId,
        retryable: error.retryable,
        validationCodes: error.validationCodes,
        message: error.message,
      }
      : {
        code: "ANNUAL_ACCOUNTS_LOCAL_OR_RESPONSE_ERROR",
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
  const output = error instanceof AnnualAccountsAuthorityError
    ? {
      ok: false,
      code: error.code,
      status: error.status,
      correlationId: error.correlationId,
      retryable: error.retryable,
      validationCodes: error.validationCodes,
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
