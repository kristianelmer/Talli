import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import type { FilingPreviewRow } from "./supabase/server";
import { resolveTalliPythonBinary } from "./python-runtime.ts";

export type Rf1086SubmissionResult = {
  filing: string;
  company_id: string;
  income_year: number;
  status:
    | "ready"
    | "authority_confirmed"
    | "preview_confirmed"
    | "submitting"
    | "submitted"
    | "feedback_ready"
    | "receipt_stored"
    | "failed_retryable"
    | "failed_blocked";
  authority_confirmed_by: string | null;
  authority_confirmed_at: string | null;
  preview_confirmed_by: string | null;
  preview_confirmed_at: string | null;
  calls: {
    endpoint: string;
    body_hash: string;
    idempotency_key: string;
    status: "prepared" | "sent" | "accepted" | "failed";
    created_at: string;
  }[];
  receipt_id: string | null;
  feedback_document_ids: string[];
  failure_code: string | null;
  failure_message: string | null;
};

export type Rf1086SubmissionFeedbackItem = {
  severity: "accepted" | "error" | "warning";
  code: string;
  message: string;
  documentId: string | null;
};

export type Rf1086ReceiptMetadata = {
  authority: "simulation" | "skatteetaten";
  receiptId: string;
  status: "receipt_stored";
  receivedAt: string;
  feedbackDocumentIds: string[];
};

export type Rf1086SubmittedPayloadReference = {
  previewId: string;
  payloadHash: string;
  hovedskjemaHash: string | null;
  underskjemaHashes: Record<string, string>;
  callCount: number;
  storedAt: string;
};

export type Rf1086SubmittedPayloadSnapshot = {
  filing: string;
  companyId: string;
  incomeYear: number;
  payloadHash: string;
  hovedskjemaXml: string | null;
  underskjemaXml: Record<string, string>;
};

export type Rf1086SubmissionConfirmations = {
  authorityConfirmed: boolean;
  previewConfirmed: boolean;
};

export type Rf1086SubmissionAdapterMode = "simulation" | "production";
export type Rf1086SubmissionAdapterRequest = {
  mode: Rf1086SubmissionAdapterMode;
  preview: FilingPreviewRow;
  userId: string;
  confirmations: Rf1086SubmissionConfirmations;
};

export class Rf1086ProductionAdapterDisabledError extends Error {
  readonly code = "rf1086_production_adapter_disabled";

  constructor() {
    super("RF-1086 produksjonsadapter er deaktivert uten eksplisitt miljøgate.");
    this.name = "Rf1086ProductionAdapterDisabledError";
  }
}

export type Rf1086ProductionEnvironment = {
  environment: "production";
  clientId: string;
  keyId: string;
  privateKeyPem: string;
  scope: "skatteetaten:innrapporteringaksjonaerregisteroppgave";
};

type Rf1086ProductionEnvironmentInput = Record<string, string | undefined>;

const RF1086_PRODUCTION_SCOPE = "skatteetaten:innrapporteringaksjonaerregisteroppgave" as const;

function productionIdentifier(value: string | undefined, label: string) {
  const normalized = value?.trim() ?? "";
  if (!normalized || normalized !== value || /\s/u.test(normalized)) {
    throw new Error(`${label} is required for RF-1086 production.`);
  }
  if (/test|tt02/iu.test(normalized)) {
    throw new Error(`${label} must not reference a test credential.`);
  }
  return normalized;
}

export function rf1086ProductionEnvironment(
  environment: Rf1086ProductionEnvironmentInput = process.env,
): Rf1086ProductionEnvironment | null {
  const flag = environment.TALLI_RF1086_PRODUCTION_ENABLED;
  if (flag === undefined || flag === "" || flag === "false") return null;
  if (flag !== "true") {
    throw new Error("TALLI_RF1086_PRODUCTION_ENABLED must be the exact string true or false.");
  }

  const privateKeyPem = environment.TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM ?? "";
  if (
    !/^-----BEGIN (?:RSA )?PRIVATE KEY-----[\s\S]+-----END (?:RSA )?PRIVATE KEY-----\s*$/u
      .test(privateKeyPem)
  ) {
    throw new Error("RF-1086 production private key must be inline PEM, never a file path or test key reference.");
  }
  const scope = environment.TALLI_PROD_RF1086_SCOPE;
  if (scope !== RF1086_PRODUCTION_SCOPE) {
    throw new Error(`RF-1086 production scope must be exactly ${RF1086_PRODUCTION_SCOPE}.`);
  }

  return {
    environment: "production",
    clientId: productionIdentifier(
      environment.TALLI_PROD_MASKINPORTEN_CLIENT_ID,
      "Production Maskinporten client id",
    ),
    keyId: productionIdentifier(
      environment.TALLI_PROD_MASKINPORTEN_KEY_ID,
      "Production Maskinporten key id",
    ),
    privateKeyPem,
    scope,
  };
}

export function assertRf1086SimulationConfirmations(confirmations: Rf1086SubmissionConfirmations) {
  if (!confirmations.authorityConfirmed) {
    throw new Error("Bekreft at du har rett til å sende inn på vegne av selskapet.");
  }
  if (!confirmations.previewConfirmed) {
    throw new Error("Bekreft at endelig forhåndsvisning er kontrollert.");
  }
}

export function rf1086PayloadHash(preview: FilingPreviewRow) {
  return createHash("sha256")
    .update(
      JSON.stringify({
        filing: preview.filing,
        company_id: preview.company_id,
        income_year: preview.income_year,
        hovedskjema_xml: preview.hovedskjema_xml,
        underskjema_xml: preview.underskjema_xml,
      }),
    )
    .digest("hex");
}

export function rf1086SubmissionIdempotencyKey(preview: FilingPreviewRow) {
  return `rf1086:${preview.company_id}:${preview.income_year}:${rf1086PayloadHash(preview).slice(0, 16)}`;
}

export function rf1086SubmissionFeedbackItems(result: Rf1086SubmissionResult): Rf1086SubmissionFeedbackItem[] {
  if (result.failure_code || result.failure_message) {
    return [
      {
        severity: result.status === "failed_blocked" || result.status === "failed_retryable" ? "error" : "warning",
        code: result.failure_code ?? "RF1086_FEEDBACK",
        message: result.failure_message ?? "RF-1086 innsending har tilbakemelding uten meldingstekst.",
        documentId: null,
      },
    ];
  }
  if (result.status === "receipt_stored") {
    return result.feedback_document_ids.map((documentId) => ({
      severity: "accepted",
      code: "RF1086_ACCEPTED",
      message: "RF-1086 er akseptert i simuleringsadapter og kvittering er lagret.",
      documentId,
    }));
  }
  return [];
}

export function rf1086ReceiptMetadata(result: Rf1086SubmissionResult): Rf1086ReceiptMetadata | null {
  if (result.status !== "receipt_stored" || !result.receipt_id) {
    return null;
  }
  return {
    authority: "simulation",
    receiptId: result.receipt_id,
    status: "receipt_stored",
    receivedAt: new Date().toISOString(),
    feedbackDocumentIds: result.feedback_document_ids,
  };
}

export function rf1086SubmittedPayloadReference(
  preview: FilingPreviewRow,
  result: Rf1086SubmissionResult,
): Rf1086SubmittedPayloadReference {
  const hashXml = (xml: string | null) => (xml ? createHash("sha256").update(xml).digest("hex") : null);
  return {
    previewId: preview.id,
    payloadHash: rf1086PayloadHash(preview),
    hovedskjemaHash: hashXml(preview.hovedskjema_xml),
    underskjemaHashes: Object.fromEntries(
      Object.entries(preview.underskjema_xml).map(([key, xml]) => [key, createHash("sha256").update(xml).digest("hex")]),
    ),
    callCount: result.calls.length,
    storedAt: new Date().toISOString(),
  };
}

export function rf1086SubmittedPayloadSnapshot(preview: FilingPreviewRow): Rf1086SubmittedPayloadSnapshot {
  return {
    filing: preview.filing,
    companyId: preview.company_id,
    incomeYear: preview.income_year,
    payloadHash: rf1086PayloadHash(preview),
    hovedskjemaXml: preview.hovedskjema_xml,
    underskjemaXml: preview.underskjema_xml,
  };
}

export function productionRf1086AdapterEnabled(
  environment: Rf1086ProductionEnvironmentInput = process.env,
) {
  try {
    return rf1086ProductionEnvironment(environment) !== null;
  } catch {
    return false;
  }
}

export function runRf1086SubmissionAdapter(request: Rf1086SubmissionAdapterRequest): Rf1086SubmissionResult {
  if (request.mode === "production") {
    throw new Rf1086ProductionAdapterDisabledError();
  }
  return simulateRf1086Submission(request.preview, request.userId, request.confirmations);
}

function sortedJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortedJsonValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, sortedJsonValue(child)]),
    );
  }
  return value;
}

function simulationBodyHash(body: unknown) {
  return createHash("sha256").update(JSON.stringify(sortedJsonValue(body))).digest("hex");
}

function uuidV5Url(value: string) {
  const namespaceUrl = Buffer.from("6ba7b8119dad11d180b400c04fd430c8", "hex");
  const bytes = createHash("sha1").update(Buffer.concat([namespaceUrl, Buffer.from(value, "utf8")])).digest().subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function simulationCall(
  preview: FilingPreviewRow,
  endpoint: string,
  body: unknown,
): Rf1086SubmissionResult["calls"][number] {
  const bodyHash = simulationBodyHash(body);
  const raw = `${preview.company_id}:${preview.income_year}:${preview.filing}:${endpoint}:${bodyHash}`;
  return {
    endpoint,
    body_hash: bodyHash,
    idempotency_key: uuidV5Url(raw),
    status: "prepared",
    created_at: new Date().toISOString(),
  };
}

/**
 * Deterministic in-process simulation. This records the same request plan and
 * simulated receipt as the legacy Python adapter without requiring a Python
 * subprocess in the deployed Vercel function.
 */
export function simulateRf1086Submission(
  preview: FilingPreviewRow,
  userId: string,
  confirmations: Rf1086SubmissionConfirmations,
): Rf1086SubmissionResult {
  assertRf1086SimulationConfirmations(confirmations);
  if (preview.status !== "ready") {
    throw new Error("RF-1086 må være klar før simulert innsending kan arkiveres.");
  }
  if (!preview.hovedskjema_xml) {
    throw new Error("RF-1086 forhåndsvisning mangler hovedskjema XML.");
  }
  const confirmedAt = new Date().toISOString();
  const baseEndpoint = `/api/aksjonaerregister/v1/${preview.income_year}`;
  const hovedskjemaId = `simulated-${preview.id}`;
  const calls = [
    simulationCall(preview, `${baseEndpoint}/1086H`, {
      content_type: "application/xml",
      xml: preview.hovedskjema_xml,
    }),
    ...Object.entries(preview.underskjema_xml)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([shareholderId, xml]) => simulationCall(preview, `${baseEndpoint}/${hovedskjemaId}/1086U`, {
        shareholder_id: shareholderId,
        content_type: "application/xml",
        xml,
      })),
    simulationCall(
      preview,
      `${baseEndpoint}/${hovedskjemaId}/bekreft?antall_underskjema=${Object.keys(preview.underskjema_xml).length}`,
      { antall_underskjema: Object.keys(preview.underskjema_xml).length },
    ),
    simulationCall(
      preview,
      `${baseEndpoint}/forsendelser/simulated-forsendelse-${preview.id}/dokumenter?page=0&size=50`,
      { page: 0, size: 50 },
    ),
  ];
  return {
    filing: preview.filing,
    company_id: preview.company_id,
    income_year: preview.income_year,
    status: "receipt_stored",
    authority_confirmed_by: userId,
    authority_confirmed_at: confirmedAt,
    preview_confirmed_by: userId,
    preview_confirmed_at: confirmedAt,
    calls,
    receipt_id: `sim-rf1086-${preview.company_id}-${preview.income_year}-${preview.id.slice(0, 8)}`,
    feedback_document_ids: [`sim-feedback-${preview.id.slice(0, 8)}`],
    failure_code: null,
    failure_message: null,
  };
}

export function simulateRf1086SubmissionWithPython(
  preview: FilingPreviewRow,
  userId: string,
  confirmations: Rf1086SubmissionConfirmations,
): Rf1086SubmissionResult {
  assertRf1086SimulationConfirmations(confirmations);
  if (preview.status !== "ready") {
    throw new Error("RF-1086 må være klar før simulert innsending kan arkiveres.");
  }
  if (!preview.hovedskjema_xml) {
    throw new Error("RF-1086 forhåndsvisning mangler hovedskjema XML.");
  }

  const python = resolveTalliPythonBinary();
  const result = spawnSync(python, ["-m", "holding_cli.main", "simulate-rf1086-submission", "--stdin-json"], {
    input: JSON.stringify({
      preview_id: preview.id,
      company_id: preview.company_id,
      income_year: preview.income_year,
      filing: preview.filing,
      hovedskjema_xml: preview.hovedskjema_xml,
      underskjema_xml: preview.underskjema_xml,
      user_id: userId,
      authority_confirmed: confirmations.authorityConfirmed,
      preview_confirmed: confirmations.previewConfirmed,
    }),
    encoding: "utf8",
    env: process.env,
  });
  if (result.error) {
    throw result.error;
  }
  const stdout = result.stdout.trim();
  if (!stdout) {
    throw new Error(result.stderr.trim() || "RF-1086 submission simulation produced no output.");
  }
  const parsed = JSON.parse(stdout) as Rf1086SubmissionResult;
  if (result.status !== 0 || parsed.status === "failed_blocked") {
    throw new Error(parsed.failure_message || result.stderr.trim() || "RF-1086 submission simulation failed.");
  }
  return parsed;
}
