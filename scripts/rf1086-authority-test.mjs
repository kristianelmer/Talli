import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, rename, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

import { requestMaskinportenToken } from "../app/lib/maskinporten.ts";
import {
  Rf1086AuthorityError,
  createRf1086AuthorityClient,
} from "../app/lib/rf1086-authority-client.ts";
import { resolveTalliPythonBinary } from "../app/lib/python-runtime.ts";

process.umask(0o077);

const RF1086_SCOPE = "skatteetaten:innrapporteringaksjonaerregisteroppgave";

function required(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function runPython(args) {
  const result = spawnSync(resolveTalliPythonBinary(), ["-m", "holding_cli.main", ...args], {
    cwd: process.cwd(),
    encoding: "utf8",
    maxBuffer: 8 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Local RF-1086 command failed (${args[0]}): ${(result.stderr || result.stdout).trim().slice(0, 1000)}`);
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

function assertSamePreparedCase(evidence, expected) {
  if (!evidence) return;
  if (
    evidence.environment !== "test"
    || evidence.companyOrgNumber !== expected.companyOrgNumber
    || evidence.incomeYear !== expected.incomeYear
    || evidence.payloadHashes?.hovedskjema !== expected.payloadHashes.hovedskjema
    || JSON.stringify(evidence.payloadHashes?.underskjema) !== JSON.stringify(expected.payloadHashes.underskjema)
  ) {
    throw new Error("Existing RF-1086 evidence belongs to a different payload; choose a new evidence path.");
  }
}

function acceptedSummary(evidence) {
  return {
    ok: true,
    status: evidence.status,
    environment: evidence.environment,
    companyOrgNumber: evidence.companyOrgNumber,
    incomeYear: evidence.incomeYear,
    hovedskjemaId: evidence.hovedskjema?.hovedskjemaId,
    receiptReference: evidence.confirmation?.oppgavegiversLeveranseReferanse,
    dialogId: evidence.confirmation?.dialogId,
    archiveReference: evidence.confirmation?.forsendelseId,
    archivedDocumentCount: evidence.archive?.totalItems,
    evidencePath: evidence.evidencePath,
  };
}

async function delay(milliseconds) {
  await new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}

async function main() {
  if (required("TALLI_RF1086_APPROVED_TEST_WRITE") !== "true") {
    throw new Error("TALLI_RF1086_APPROVED_TEST_WRITE must be exactly true for an authority test write.");
  }
  if (required("TALLI_MASKINPORTEN_ENVIRONMENT") !== "test") {
    throw new Error("The RF-1086 authority test command refuses every environment except test.");
  }
  const scope = required("TALLI_MASKINPORTEN_SCOPE");
  if (scope !== RF1086_SCOPE) throw new Error(`The RF-1086 authority test requires scope ${RF1086_SCOPE}.`);

  const casePath = resolve(required("TALLI_RF1086_CASE_PATH"));
  const evidencePath = resolve(required("TALLI_RF1086_EVIDENCE_PATH"));
  const caseData = JSON.parse(await readFile(casePath, "utf8"));
  const companyOrgNumber = String(caseData.company?.org_number ?? "");
  const incomeYear = Number(caseData.company?.income_year);
  const systemUserOrgNumber = required("TALLI_MASKINPORTEN_SYSTEM_USER_ORG");
  if (companyOrgNumber !== systemUserOrgNumber) {
    throw new Error("RF-1086 case organization must equal the Maskinporten system-user organization.");
  }
  if (!Number.isInteger(incomeYear)) throw new Error("RF-1086 case income year is invalid.");
  const events = Array.isArray(caseData.events) ? caseData.events : [];
  if (events.some((event) => event?.type !== "formation")) {
    throw new Error("RF-1086 authority rehearsal is limited to no-activity or formation cases.");
  }

  const outputDirectory = join(dirname(evidencePath), "xml");
  await mkdir(outputDirectory, { recursive: true, mode: 0o700 });
  runPython(["simulate-aksjonaerregister", "--case", casePath, "--out", outputDirectory]);
  const filenames = (await readdir(outputDirectory)).sort();
  const hovedskjemaPath = join(outputDirectory, "1086H.xml");
  const underskjemaFiles = filenames.filter((filename) => filename.startsWith("1086U-") && filename.endsWith(".xml"));
  if (!underskjemaFiles.length) throw new Error("Generated RF-1086 payload has no underskjema.");
  runPython([
    "validate-rf1086-xml",
    "--hovedskjema",
    hovedskjemaPath,
    "--underskjema",
    ...underskjemaFiles.map((filename) => join(outputDirectory, filename)),
  ]);

  const hovedskjemaXml = await readFile(hovedskjemaPath, "utf8");
  const underskjemaXml = Object.fromEntries(await Promise.all(underskjemaFiles.map(async (filename) => [
    filename.slice("1086U-".length, -".xml".length),
    await readFile(join(outputDirectory, filename), "utf8"),
  ])));
  const payloadHashes = {
    hovedskjema: sha256(hovedskjemaXml),
    underskjema: Object.fromEntries(Object.entries(underskjemaXml).map(([id, xml]) => [id, sha256(xml)])),
  };

  const prior = await existingEvidence(evidencePath);
  assertSamePreparedCase(prior, { companyOrgNumber, incomeYear, payloadHashes });
  if (prior?.status === "accepted") {
    console.log(JSON.stringify(acceptedSummary(prior)));
    return;
  }

  const idempotencyKeys = prior?.idempotencyKeys ?? {
    hovedskjema: randomUUID(),
    underskjema: Object.fromEntries(Object.keys(underskjemaXml).sort().map((id) => [id, randomUUID()])),
    bekreft: randomUUID(),
  };
  const evidence = {
    schemaVersion: 1,
    status: "prepared",
    environment: "test",
    authority: "Skatteetaten RF-1086 API",
    companyOrgNumber,
    companyName: String(caseData.company?.name ?? ""),
    incomeYear,
    scope,
    evidencePath,
    preparedAt: prior?.preparedAt ?? new Date().toISOString(),
    payloadHashes,
    idempotencyKeys,
    hovedskjema: prior?.hovedskjema ?? null,
    underskjema: prior?.underskjema ?? {},
    confirmation: prior?.confirmation ?? null,
    archive: prior?.archive ?? null,
    error: null,
  };
  await writeJsonAtomic(evidencePath, evidence);

  const privateKeyPath = required("TALLI_MASKINPORTEN_PRIVATE_KEY_PATH");
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
    systemUserExternalRef: process.env.TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF?.trim() || undefined,
  });
  const client = createRf1086AuthorityClient({ environment: "test", accessToken: token.accessToken });

  try {
    if (!evidence.hovedskjema) {
      const result = await client.postHovedskjema({ incomeYear, xml: hovedskjemaXml, idempotencyKey: idempotencyKeys.hovedskjema });
      evidence.hovedskjema = { hovedskjemaId: result.hovedskjemaId, call: result.call };
      evidence.status = "hovedskjema_accepted";
      await writeJsonAtomic(evidencePath, evidence);
    }

    for (const [shareholderId, xml] of Object.entries(underskjemaXml).sort(([left], [right]) => left.localeCompare(right))) {
      if (evidence.underskjema[shareholderId]) continue;
      const result = await client.postUnderskjema({
        incomeYear,
        hovedskjemaId: evidence.hovedskjema.hovedskjemaId,
        xml,
        idempotencyKey: idempotencyKeys.underskjema[shareholderId],
      });
      evidence.underskjema[shareholderId] = { call: result.call };
      evidence.status = "underskjema_accepted";
      await writeJsonAtomic(evidencePath, evidence);
    }

    if (!evidence.confirmation) {
      const result = await client.confirm({
        incomeYear,
        hovedskjemaId: evidence.hovedskjema.hovedskjemaId,
        underskjemaCount: Object.keys(underskjemaXml).length,
        idempotencyKey: idempotencyKeys.bekreft,
      });
      evidence.confirmation = {
        oppgavegiversLeveranseReferanse: result.oppgavegiversLeveranseReferanse,
        dialogId: result.dialogId,
        forsendelseId: result.forsendelseId,
        call: result.call,
      };
      evidence.status = "confirmed";
      await writeJsonAtomic(evidencePath, evidence);
    }

    let archive;
    for (let attempt = 1; attempt <= 5; attempt += 1) {
      try {
        const result = await client.listDocuments({
          incomeYear,
          referenceId: evidence.confirmation.forsendelseId,
          page: 0,
          size: 50,
        });
        if (result.totalItems > 0 && result.documents.length > 0) {
          archive = {
            lookupReferenceType: "forsendelseId",
            lookupReferenceId: evidence.confirmation.forsendelseId,
            totalItems: result.totalItems,
            totalPages: result.totalPages,
            currentPage: result.currentPage,
            documentHashes: result.documents.map((document) => sha256(document)),
            call: result.call,
          };
          break;
        }
      } catch (error) {
        const eventualArchive = error instanceof Rf1086AuthorityError
          && error.status === 404
          && error.code === "GLD_021"
          && error.specificationCodes.includes("GLD_1017");
        if (!eventualArchive || attempt === 5) throw error;
      }
      if (attempt < 5) await delay(2_000);
    }
    if (!archive) throw new Error("RF-1086 archive returned no documents after confirmation.");

    evidence.archive = archive;
    evidence.status = "accepted";
    evidence.acceptedAt = new Date().toISOString();
    await writeJsonAtomic(evidencePath, evidence);
    console.log(JSON.stringify(acceptedSummary(evidence)));
  } catch (error) {
    evidence.status = error instanceof Rf1086AuthorityError && error.retryable ? "failed_retryable" : "failed_blocked";
    evidence.error = error instanceof Rf1086AuthorityError
      ? { code: error.code, status: error.status, correlationId: error.correlationId, retryable: error.retryable, message: error.message }
      : { code: "RF1086_LOCAL_OR_RESPONSE_ERROR", status: null, correlationId: null, retryable: false, message: error instanceof Error ? error.message : "Unknown error." };
    await writeJsonAtomic(evidencePath, evidence);
    throw error;
  }
}

main().catch((error) => {
  const output = error instanceof Rf1086AuthorityError
    ? { ok: false, code: error.code, status: error.status, correlationId: error.correlationId, retryable: error.retryable, message: error.message }
    : { ok: false, code: "local_configuration_or_payload_error", status: null, message: error instanceof Error ? error.message : "Unknown error." };
  console.error(JSON.stringify(output));
  process.exitCode = 1;
});
