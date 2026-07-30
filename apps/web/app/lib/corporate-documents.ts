import { spawn } from "node:child_process";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { createHash } from "node:crypto";

import { resolveTalliPythonBinary } from "./python-runtime.ts";

export const MAX_CORPORATE_PDF_BYTES = 10 * 1024 * 1024;
export const MAX_CORPORATE_RENDER_STDOUT_BYTES = 10 * 1024 * 1024;
export const MAX_CORPORATE_RENDER_STDERR_BYTES = 64 * 1024;
export const CORPORATE_RENDER_TIMEOUT_MS = 15_000;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const ISSUE_CODE_PATTERN = /^[a-z0-9_]{1,120}$/;

export type CorporateArtifactKind =
  | "dividend_board_proposal"
  | "dividend_general_meeting_minutes"
  | "annual_board_minutes"
  | "annual_general_meeting_minutes";

export type CorporateDecisionInput = {
  request_id: string;
  company_id: string;
  organization_number: string;
  legal_name: string;
  income_year: number;
  decision_kind: "owner_dividend" | "annual_close";
  annual_close_source_id: string;
  source_hash: string;
  template_family: "norwegian_simple_as";
  template_version: "corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1";
  annual_basis_year: number;
  financial_totals: {
    result_after_tax_ore: number;
    equity_ore: number;
    available_distribution_ore: number;
    cash_ore: number;
  };
  board_meeting: {
    meeting_date: string;
    meeting_time: string;
    place: string;
    treatment_method: "physical" | "video" | "written";
  };
  board_participants: Array<{
    participant_id: string;
    name: string;
    role: "chair" | "member";
  }>;
  general_meeting: {
    meeting_date: string;
    meeting_time: string;
    place: string;
    meeting_form: "physical" | "video";
    chair_name: string;
    co_signer_name: string;
  };
  shareholders: Array<{
    shareholder_id: string;
    name: string;
    share_count: number;
    represented_share_count: number;
    vote: "for" | "against" | "abstain";
  }>;
  total_company_shares: number;
  one_share_class_confirmed: boolean;
  dividend: {
    amount_ore: number;
    payment_date: string;
    liquidity_after_payment_ore: number;
    allocations: Array<{ shareholder_id: string; amount_ore: number }>;
  } | null;
  annual_result_allocation_ore: number;
  confirmations: {
    latest_approved_annual_accounts: boolean;
    supported_dividend_basis: boolean;
    full_board_participation: boolean;
    full_share_representation: boolean;
    unanimous_board: boolean;
    unanimous_shareholders: boolean;
    proportional_allocation: boolean;
    prudent_equity_and_liquidity: boolean;
  };
};

export type RenderedCorporateArtifact = {
  artifactKind: CorporateArtifactKind;
  filename: string;
  templateVersion: string;
  decisionHash: string;
  contentSha256: string;
  byteLength: number;
  pdfBytes: Uint8Array;
};

export type CorporateRenderIssue = {
  code: string;
  message: string;
  details?: number;
};

export type CorporateRenderResult =
  | {
      status: "rendered";
      decisionHash: string;
      artifacts: RenderedCorporateArtifact[];
    }
  | {
      status: "blocked";
      issues: CorporateRenderIssue[];
    };

type SpawnProcess = typeof spawn;

export type CorporateRendererOptions = {
  cwd?: string;
  env?: Record<string, string | undefined>;
  pythonBinary?: string;
  spawnProcess?: SpawnProcess;
  timeoutMs?: number;
  maxStdoutBytes?: number;
  maxStderrBytes?: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stableJsonValue(value: unknown): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value) || !Number.isSafeInteger(value)) {
      throw new Error("Corporate decision numbers must be finite safe integers.");
    }
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(stableJsonValue);
  }
  if (isRecord(value)) {
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(value).sort()) {
      const child = value[key];
      if (child === undefined) {
        throw new Error("Corporate decision input cannot contain undefined values.");
      }
      sorted[key] = stableJsonValue(child);
    }
    return sorted;
  }
  throw new Error("Corporate decision input contains an unsupported value.");
}

function validateDecisionIdentity(input: CorporateDecisionInput) {
  if (!UUID_PATTERN.test(input.request_id)
    || !UUID_PATTERN.test(input.company_id)
    || !UUID_PATTERN.test(input.annual_close_source_id)
    || !SHA256_PATTERN.test(input.source_hash)
    || !/^\d{9}$/.test(input.organization_number)
    || !Number.isInteger(input.income_year)
    || input.income_year < 2000
    || input.income_year > 2100) {
    throw new Error("Corporate decision identity is invalid.");
  }
}

export function canonicalDecisionJson(input: CorporateDecisionInput): string {
  validateDecisionIdentity(input);
  return JSON.stringify(stableJsonValue(input));
}

export function corporateDecisionHash(input: CorporateDecisionInput): string {
  return createHash("sha256").update(canonicalDecisionJson(input), "utf8").digest("hex");
}

function requiredArtifactKinds(input: CorporateDecisionInput): CorporateArtifactKind[] {
  return input.decision_kind === "owner_dividend"
    ? ["dividend_board_proposal", "dividend_general_meeting_minutes"]
    : ["annual_board_minutes", "annual_general_meeting_minutes"];
}

function parseStrictBase64(value: unknown): Uint8Array {
  if (typeof value !== "string"
    || value.length === 0
    || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw new Error("Corporate renderer returned invalid base64 PDF data.");
  }
  const bytes = Buffer.from(value, "base64");
  if (bytes.toString("base64") !== value) {
    throw new Error("Corporate renderer returned non-canonical base64 PDF data.");
  }
  return new Uint8Array(bytes);
}

function parseBlockedResult(payload: Record<string, unknown>): CorporateRenderResult {
  if (!Array.isArray(payload.issues) || payload.issues.length < 1 || payload.issues.length > 20) {
    throw new Error("Corporate renderer returned an invalid blocked result.");
  }
  const issues = payload.issues.map((issue): CorporateRenderIssue => {
    if (!isRecord(issue)
      || typeof issue.code !== "string"
      || !ISSUE_CODE_PATTERN.test(issue.code)
      || typeof issue.message !== "string"
      || issue.message.trim().length === 0
      || issue.message.length > 1000
      || (issue.details !== undefined && (!Number.isInteger(issue.details) || Number(issue.details) < 0))) {
      throw new Error("Corporate renderer returned an invalid blocked result.");
    }
    return {
      code: issue.code,
      message: issue.message,
      ...(issue.details === undefined ? {} : { details: Number(issue.details) }),
    };
  });
  return { status: "blocked", issues };
}

function parseRenderedArtifact(
  value: unknown,
  input: CorporateDecisionInput,
  expectedDecisionHash: string,
): RenderedCorporateArtifact {
  if (!isRecord(value)
    || typeof value.artifactKind !== "string"
    || typeof value.filename !== "string"
    || value.filename.length < 5
    || value.filename.length > 200
    || value.filename.includes("/")
    || value.filename.includes("\\")
    || !value.filename.toLowerCase().endsWith(".pdf")
    || value.templateVersion !== input.template_version
    || value.decisionHash !== expectedDecisionHash
    || typeof value.contentSha256 !== "string"
    || !SHA256_PATTERN.test(value.contentSha256)
    || !Number.isInteger(value.byteLength)
    || Number(value.byteLength) < 1
    || Number(value.byteLength) > MAX_CORPORATE_PDF_BYTES) {
    throw new Error("Corporate renderer returned invalid artifact metadata.");
  }
  const bytes = parseStrictBase64(value.pdfBase64);
  if (bytes.byteLength !== value.byteLength) {
    throw new Error("Corporate renderer PDF byte length does not match metadata.");
  }
  if (Buffer.from(bytes).subarray(0, 5).toString("ascii") !== "%PDF-") {
    throw new Error("Corporate renderer output has an invalid PDF signature.");
  }
  const contentHash = createHash("sha256").update(bytes).digest("hex");
  if (contentHash !== value.contentSha256) {
    throw new Error("Corporate renderer PDF content hash does not match metadata.");
  }
  return {
    artifactKind: value.artifactKind as CorporateArtifactKind,
    filename: value.filename,
    templateVersion: value.templateVersion,
    decisionHash: value.decisionHash,
    contentSha256: value.contentSha256,
    byteLength: value.byteLength,
    pdfBytes: bytes,
  };
}

export function parseCorporateRenderResult(
  stdout: string,
  expected: CorporateDecisionInput,
): CorporateRenderResult {
  if (Buffer.byteLength(stdout, "utf8") > MAX_CORPORATE_RENDER_STDOUT_BYTES) {
    throw new Error("Corporate renderer exceeded the stdout output limit.");
  }
  let payload: unknown;
  try {
    payload = JSON.parse(stdout);
  } catch {
    throw new Error("Corporate renderer did not return valid JSON.");
  }
  if (!isRecord(payload)) {
    throw new Error("Corporate renderer returned an invalid result.");
  }
  if (payload.status === "blocked") {
    return parseBlockedResult(payload);
  }
  if (payload.status !== "rendered" || !Array.isArray(payload.artifacts)) {
    throw new Error("Corporate renderer returned an invalid result.");
  }
  const decisionHash = corporateDecisionHash(expected);
  if (payload.decisionHash !== decisionHash) {
    throw new Error("Corporate renderer decision hash does not match the Node hash.");
  }
  const artifacts = payload.artifacts.map((artifact) =>
    parseRenderedArtifact(artifact, expected, decisionHash));
  const actualKinds = artifacts.map(({ artifactKind }) => artifactKind).sort();
  const expectedKinds = requiredArtifactKinds(expected).sort();
  if (actualKinds.length !== expectedKinds.length
    || actualKinds.some((kind, index) => kind !== expectedKinds[index])) {
    throw new Error("Corporate renderer did not return the exact required artifact kinds.");
  }
  return { status: "rendered", decisionHash, artifacts };
}

function restrictedRendererEnvironment(source: Record<string, string | undefined>): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {
    LANG: source.LANG?.trim() || "C.UTF-8",
    LC_ALL: source.LC_ALL?.trim() || "C.UTF-8",
    NODE_ENV: source.NODE_ENV === "development" || source.NODE_ENV === "test"
      ? source.NODE_ENV
      : "production",
    PYTHONUNBUFFERED: "1",
  };
  for (const key of ["PATH", "PYTHONPATH", "SSL_CERT_FILE", "SSL_CERT_DIR", "TZ"] as const) {
    const value = source[key]?.trim();
    if (value) environment[key] = value;
  }
  return environment;
}

export async function renderCorporateDocuments(
  input: CorporateDecisionInput,
  options: CorporateRendererOptions = {},
): Promise<CorporateRenderResult> {
  const cwd = options.cwd ?? process.cwd();
  const sourceEnvironment = options.env ?? process.env;
  const pythonBinary = options.pythonBinary
    ?? resolveTalliPythonBinary({ cwd, env: sourceEnvironment });
  const spawnProcess = options.spawnProcess ?? spawn;
  const maxStdoutBytes = options.maxStdoutBytes ?? MAX_CORPORATE_RENDER_STDOUT_BYTES;
  const maxStderrBytes = options.maxStderrBytes ?? MAX_CORPORATE_RENDER_STDERR_BYTES;
  const timeoutMs = options.timeoutMs ?? CORPORATE_RENDER_TIMEOUT_MS;
  const stdin = canonicalDecisionJson(input);

  return await new Promise<CorporateRenderResult>((resolve, reject) => {
    let child: ChildProcessWithoutNullStreams;
    try {
      child = spawnProcess(
        pythonBinary,
        ["-m", "holding_cli.main", "render-corporate-documents", "--stdin-json"],
        {
          cwd,
          env: restrictedRendererEnvironment(sourceEnvironment),
          shell: false,
          stdio: ["pipe", "pipe", "pipe"],
          windowsHide: true,
        },
      ) as ChildProcessWithoutNullStreams;
    } catch (error) {
      reject(error);
      return;
    }

    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];
    let stdoutBytes = 0;
    let stderrBytes = 0;
    let settled = false;

    const timer = setTimeout(() => {
      fail(new Error("Corporate renderer timed out."));
    }, timeoutMs);

    function fail(error: Error) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.kill("SIGKILL");
      reject(error);
    }

    child.stdout.on("data", (chunk: Buffer | string) => {
      if (settled) return;
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      stdoutBytes += bytes.length;
      if (stdoutBytes > maxStdoutBytes) {
        fail(new Error("Corporate renderer exceeded the stdout output limit."));
        return;
      }
      stdoutChunks.push(bytes);
    });
    child.stderr.on("data", (chunk: Buffer | string) => {
      if (settled) return;
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      stderrBytes += bytes.length;
      if (stderrBytes > maxStderrBytes) {
        fail(new Error("Corporate renderer exceeded the stderr output limit."));
        return;
      }
      stderrChunks.push(bytes);
    });
    child.on("error", (error) => fail(error));
    child.on("close", (exitCode, signal) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const stdout = Buffer.concat(stdoutChunks).toString("utf8");
      let result: CorporateRenderResult;
      try {
        result = parseCorporateRenderResult(stdout, input);
      } catch (error) {
        reject(error);
        return;
      }
      if (result.status === "blocked" && (exitCode === 0 || exitCode === 1)) {
        resolve(result);
        return;
      }
      if (result.status === "rendered" && exitCode === 0) {
        resolve(result);
        return;
      }
      reject(new Error(
        `Corporate renderer exited unexpectedly (${exitCode ?? signal ?? "unknown"}; stderr ${stderrBytes} bytes).`,
      ));
    });
    child.stdin.on("error", (error) => fail(error));
    child.stdin.end(stdin, "utf8");
  });
}
