import { createHash } from "node:crypto";
import { XMLParser, XMLValidator } from "fast-xml-parser";

const ORG_NUMBER_PATTERN = /^\d{9}$/u;
const UNSAFE_XML_PATTERN = /<!\s*(?:DOCTYPE|ENTITY)\b/iu;
const FORBIDDEN_XML_TEXT_PATTERN = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/u;
const DEFAULT_TIMEOUT_MS = 20_000;
const DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024;
const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024;
const MAX_AUTHORITY_DOCUMENTS = 32;
const MAX_FEEDBACK_ITEMS = 2_000;
const MAX_LOCKED_FIELDS = 10_000;
const MAX_XML_ELEMENTS = 100_000;
const MAX_XML_DEPTH = 256;
const REQUEST_NAMESPACE = "no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:request:v2";
const RESPONSE_NAMESPACE = "no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:response:v2";
const DRAFT_RESPONSE_NAMESPACE = "no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:forespoersel:response:v2";
const RESPONSE_ROOT = "skattemeldingOgNaeringsspesifikasjonResponse";
const DRAFT_RESPONSE_ROOT = "skattemeldingOgNaeringsspesifikasjonforespoerselResponse";

export const COMPANY_TAX_RETURN_VALIDATION_BASE_URLS = {
  test: "https://api-test.sits.no/api/skattemelding/v2",
  production: "https://api.skatteetaten.no/api/skattemelding/v2",
} as const;

export const COMPANY_TAX_RETURN_VALIDATION_SCOPE = "skatteetaten:formueinntekt/skattemelding";

export type CompanyTaxReturnAuthorityEnvironment = keyof typeof COMPANY_TAX_RETURN_VALIDATION_BASE_URLS;
export type CompanyTaxReturnValidationMode = "filing" | "calculation-only";
export type CompanyTaxReturnValidationResultCode = "validertOK" | "validertMedFeil";
export type CompanyTaxReturnFeedbackLevel = "error" | "warning" | "info";
export type CompanyTaxReturnFeedbackSource = "validation" | "calculation" | "guidance";

export type CompanyTaxReturnAuthorityTransportRequest = {
  method: "GET" | "POST";
  url: string;
  headers: Readonly<Record<string, string>>;
  body?: string;
  timeoutMs: number;
  maxResponseBytes: number;
};

export type CompanyTaxReturnAuthorityTransportResponse = {
  status: number;
  headers: Readonly<Record<string, string>>;
  body: Uint8Array;
};

export type CompanyTaxReturnAuthorityTransport = (
  request: CompanyTaxReturnAuthorityTransportRequest,
) => Promise<CompanyTaxReturnAuthorityTransportResponse>;

export type CompanyTaxReturnValidationInput = {
  organizationNumber: string;
  incomeYear: number;
  taxReturnXml: string;
  businessSpecificationXml: string;
  currentTaxReturnDocumentId?: string;
  createdBy?: string;
};

export type CompanyTaxReturnValidationFeedback = {
  level: CompanyTaxReturnFeedbackLevel;
  source: CompanyTaxReturnFeedbackSource;
  code: string;
  message: string;
  occurrenceId?: string;
  path?: string;
  receivedValue?: string;
  calculatedValue?: string;
  difference?: string;
  strategy?: string;
};

export type CompanyTaxReturnCalculatedDocument = {
  type:
    | "naeringsspesifikasjonEtterBeregning"
    | "skattemeldingUpersonligEtterBeregning"
    | "beregnetSkattUpersonlig"
    | "beregnetSkattUpersonligSvalbard"
    | "summertSkattegrunnlagForVisningUpersonlig"
    | "summertSkattegrunnlagForVisningUpersonligSvalbard"
    | "beregnetSkattUpersonligPetroleum"
    | "summertSkattegrunnlagForVisningUpersonligPetroleum";
  encoding: "utf-8";
  xml: string;
  sha256: string;
  byteLength: number;
};

export type CompanyTaxReturnValidationResult = {
  result: CompanyTaxReturnValidationResultCode;
  calculationOnly: boolean;
  validForSubmission: boolean;
  reasons: string[];
  feedback: CompanyTaxReturnValidationFeedback[];
  documents: CompanyTaxReturnCalculatedDocument[];
};

export type CompanyTaxReturnCurrentDocument = {
  id: string;
  encoding: "utf-8";
  xml: string;
};

export type CompanyTaxReturnCurrentDraft = {
  taxReturn: CompanyTaxReturnCurrentDocument & {
    type: "skattemeldingUpersonligUtkast" | "skattemeldingUpersonligFastsatt";
  };
  businessSpecification: CompanyTaxReturnCurrentDocument | null;
  lockedFields: Array<{
    document: "skattemeldingUpersonlig" | "naeringsspesifikasjon";
    occurrenceId?: string;
    value?: string;
    path?: string;
    information?: string;
  }>;
};

export type CompanyTaxReturnAuthorityClient = {
  readonly environment: CompanyTaxReturnAuthorityEnvironment;
  getCurrentDraft(input: { organizationNumber: string; incomeYear: number }): Promise<CompanyTaxReturnCurrentDraft>;
  validateForFiling(input: CompanyTaxReturnValidationInput & { currentTaxReturnDocumentId: string }): Promise<CompanyTaxReturnValidationResult>;
  calculateWithoutCurrentDraft(input: Omit<CompanyTaxReturnValidationInput, "currentTaxReturnDocumentId">): Promise<CompanyTaxReturnValidationResult>;
};

export class CompanyTaxReturnAuthorityError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly status?: number;

  constructor(code: string, message: string, options: { retryable?: boolean; status?: number } = {}) {
    super(message);
    this.name = "CompanyTaxReturnAuthorityError";
    this.code = code;
    this.retryable = options.retryable ?? false;
    this.status = options.status;
  }
}

type ClientOptions = {
  environment: CompanyTaxReturnAuthorityEnvironment;
  accessToken: string;
  transport?: CompanyTaxReturnAuthorityTransport;
  timeoutMs?: number;
  maxResponseBytes?: number;
};

const parser = new XMLParser({
  ignoreAttributes: false,
  removeNSPrefix: false,
  parseTagValue: false,
  trimValues: true,
  // Authority XML is rejected before parsing if it declares a DOCTYPE or
  // custom entity. Processing here is therefore limited to XML's predefined
  // character entities (for example &amp; in provider guidance).
  processEntities: true,
});

const calculatedDocumentTypes = new Set<CompanyTaxReturnCalculatedDocument["type"]>([
  "naeringsspesifikasjonEtterBeregning",
  "skattemeldingUpersonligEtterBeregning",
  "beregnetSkattUpersonlig",
  "beregnetSkattUpersonligSvalbard",
  "summertSkattegrunnlagForVisningUpersonlig",
  "summertSkattegrunnlagForVisningUpersonligSvalbard",
  "beregnetSkattUpersonligPetroleum",
  "summertSkattegrunnlagForVisningUpersonligPetroleum",
]);

function authorityError(code: string, message: string, retryable = false, status?: number) {
  return new CompanyTaxReturnAuthorityError(code, message, {
    retryable,
    ...(status === undefined ? {} : { status }),
  });
}

function assertEnvironment(value: unknown): asserts value is CompanyTaxReturnAuthorityEnvironment {
  if (value !== "test" && value !== "production") {
    throw authorityError(
      "company_tax_return_environment_invalid",
      "Company-tax-return authority environment must be test or production.",
    );
  }
}

function assertAccessToken(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length < 8 || value.length > 16_384 || /\s/u.test(value)) {
    throw authorityError(
      "company_tax_return_access_token_invalid",
      "Company-tax-return authority requires a bounded short-lived system-user bearer token.",
    );
  }
}

function assertBoundedInteger(value: unknown, minimum: number, maximum: number, code: string, label: string) {
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw authorityError(code, `${label} is outside the supported range.`);
  }
  return value as number;
}

function assertIncomeYear(value: unknown) {
  return assertBoundedInteger(
    value,
    1000,
    9999,
    "company_tax_return_income_year_invalid",
    "Company-tax-return income year",
  );
}

function assertOrganizationNumber(value: unknown) {
  if (typeof value !== "string" || !ORG_NUMBER_PATTERN.test(value) || !hasValidOrganizationNumberChecksum(value)) {
    throw authorityError(
      "company_tax_return_organization_number_invalid",
      "Company-tax-return organization number must contain nine digits.",
    );
  }
  return value;
}

function hasValidOrganizationNumberChecksum(value: string) {
  const weights = [3, 2, 7, 6, 5, 4, 3, 2] as const;
  const sum = weights.reduce((total, weight, index) => total + Number(value[index]) * weight, 0);
  const remainder = 11 - (sum % 11);
  const expected = remainder === 11 ? 0 : remainder;
  return expected !== 10 && expected === Number(value[8]);
}

function assertInputText(value: unknown, maximum: number, code: string, label: string) {
  if (
    typeof value !== "string" ||
    value.length < 1 ||
    value.length > maximum ||
    FORBIDDEN_XML_TEXT_PATTERN.test(value)
  ) {
    throw authorityError(code, `${label} must be non-empty, bounded XML-safe text.`);
  }
  return value;
}

function escapeXmlText(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function assertSafeXml(value: unknown, label: string) {
  if (typeof value !== "string" || !value.trimStart().startsWith("<")) {
    throw authorityError("company_tax_return_xml_invalid", `${label} must be a non-empty XML document.`);
  }
  if (new TextEncoder().encode(value).byteLength > MAX_DOCUMENT_BYTES) {
    throw authorityError("company_tax_return_xml_too_large", `${label} exceeds the configured size limit.`);
  }
  if (UNSAFE_XML_PATTERN.test(value)) {
    throw authorityError("company_tax_return_xml_unsafe", `${label} cannot contain document-type or entity declarations.`);
  }
  assertXmlComplexity(value, "company_tax_return_xml_too_complex", `${label} is too structurally complex.`);
  if (XMLValidator.validate(value, { allowBooleanAttributes: false }) !== true) {
    throw authorityError("company_tax_return_xml_invalid", `${label} is not well-formed XML.`);
  }
  return value;
}

function assertXmlComplexity(xml: string, code: string, message: string) {
  const markup = xml
    .replace(/<!--[\s\S]*?-->/gu, "")
    .replace(/<!\[CDATA\[[\s\S]*?\]\]>/gu, "")
    .replace(/<\?[\s\S]*?\?>/gu, "");
  const tags = markup.match(/<[^>]+>/gu) ?? [];
  let depth = 0;
  let elementCount = 0;
  for (const tag of tags) {
    if (tag.startsWith("</")) {
      depth = Math.max(0, depth - 1);
      continue;
    }
    if (tag.startsWith("<!")) continue;
    elementCount += 1;
    if (!tag.endsWith("/>")) depth += 1;
    if (elementCount > MAX_XML_ELEMENTS || depth > MAX_XML_DEPTH) throw authorityError(code, message);
  }
}

export function buildCompanyTaxReturnValidationEnvelope(
  input: CompanyTaxReturnValidationInput & { mode: CompanyTaxReturnValidationMode },
) {
  const organizationNumber = assertOrganizationNumber(input.organizationNumber);
  const incomeYear = assertIncomeYear(input.incomeYear);
  const taxReturnXml = assertSafeXml(input.taxReturnXml, "Company tax return");
  const businessSpecificationXml = assertSafeXml(
    input.businessSpecificationXml,
    "Company business specification",
  );
  const createdBy = assertInputText(
    input.createdBy ?? "Talli",
    4_000,
    "company_tax_return_created_by_invalid",
    "Company-tax-return creator",
  );
  if (input.mode !== "filing" && input.mode !== "calculation-only") {
    throw authorityError("company_tax_return_validation_mode_invalid", "Company-tax-return validation mode is invalid.");
  }
  let reference = "";
  if (input.mode === "filing") {
    if (!input.currentTaxReturnDocumentId) {
      throw authorityError(
        "company_tax_return_current_document_required",
        "Filing validation requires the current Skatteetaten tax-return document reference.",
      );
    }
    const documentId = assertInputText(
      input.currentTaxReturnDocumentId,
      4_000,
      "company_tax_return_current_document_invalid",
      "Current tax-return document reference",
    );
    reference = `
  <dokumentreferanseTilGjeldendeDokument>
    <dokumenttype>skattemeldingUpersonlig</dokumenttype>
    <dokumentidentifikator>${escapeXmlText(documentId)}</dokumentidentifikator>
  </dokumentreferanseTilGjeldendeDokument>`;
  }
  const encodedTaxReturn = Buffer.from(taxReturnXml, "utf8").toString("base64");
  const encodedBusinessSpecification = Buffer.from(businessSpecificationXml, "utf8").toString("base64");
  return `<?xml version="1.0" encoding="UTF-8"?>
<skattemeldingOgNaeringsspesifikasjonRequest xmlns="${REQUEST_NAMESPACE}">
  <dokumenter>
    <dokument>
      <type>skattemeldingUpersonlig</type>
      <encoding>utf-8</encoding>
      <content>${encodedTaxReturn}</content>
    </dokument>
    <dokument>
      <type>naeringsspesifikasjon</type>
      <encoding>utf-8</encoding>
      <content>${encodedBusinessSpecification}</content>
    </dokument>
  </dokumenter>${reference}
  <inntektsaar>${incomeYear}</inntektsaar>
  <innsendingsinformasjon>
    <innsendingstype>komplett</innsendingstype>
    <opprettetAv>${escapeXmlText(createdBy)}</opprettetAv>
    <tin>${organizationNumber}</tin>
    <innsendingsformaal>egenfastsetting</innsendingsformaal>
  </innsendingsinformasjon>
</skattemeldingOgNaeringsspesifikasjonRequest>`;
}

function headerValue(headers: Readonly<Record<string, string>>, name: string) {
  return Object.entries(headers).find(([key]) => key.toLowerCase() === name.toLowerCase())?.[1];
}

function normalizedContentType(headers: Readonly<Record<string, string>>) {
  return headerValue(headers, "content-type")?.split(";", 1)[0]?.trim().toLowerCase();
}

function assertRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid");
  return value as Record<string, unknown>;
}

function asArray(value: unknown, maximum: number) {
  if (value === undefined || value === null) return [];
  const result = Array.isArray(value) ? value : [value];
  if (result.length > maximum) throw new Error("invalid");
  return result;
}

function requiredText(value: unknown, maximum = 4_000) {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum) throw new Error("invalid");
  return value;
}

function optionalText(value: unknown, maximum = 4_000) {
  if (value === undefined || value === null || value === "") return undefined;
  return requiredText(value, maximum);
}

function decodeAuthorityXml(value: unknown, label: string) {
  const encoded = requiredText(value, Math.ceil((MAX_DOCUMENT_BYTES * 4) / 3) + 8).replace(/[\t\n\r ]/gu, "");
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u.test(encoded)) {
    throw new Error("invalid");
  }
  const bytes = Buffer.from(encoded, "base64");
  if (bytes.byteLength > MAX_DOCUMENT_BYTES || bytes.toString("base64") !== encoded) throw new Error("invalid");
  let xml: string;
  try {
    xml = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error("invalid");
  }
  try {
    assertSafeXml(xml, label);
  } catch {
    throw new Error("invalid");
  }
  return { xml, sha256: createHash("sha256").update(bytes).digest("hex"), byteLength: bytes.byteLength };
}

function assertSafeAuthorityResponseXml(xml: string) {
  if (UNSAFE_XML_PATTERN.test(xml)) {
    throw authorityError(
      "company_tax_return_response_unsafe",
      "Company-tax-return authority returned unsafe XML.",
    );
  }
  assertXmlComplexity(
    xml,
    "company_tax_return_response_too_complex",
    "Company-tax-return authority returned structurally excessive XML.",
  );
  if (XMLValidator.validate(xml, { allowBooleanAttributes: false }) !== true) {
    throw authorityError(
      "company_tax_return_response_invalid",
      "Company-tax-return authority returned malformed XML.",
    );
  }
}

function parseRoot(xml: string, rootName: string, namespace: string) {
  assertSafeAuthorityResponseXml(xml);
  try {
    const parsed = assertRecord(parser.parse(xml));
    const root = assertRecord(parsed[rootName]);
    if (root["@_xmlns"] !== namespace) throw new Error("invalid");
    return root;
  } catch (error) {
    if (error instanceof CompanyTaxReturnAuthorityError) throw error;
    throw authorityError(
      "company_tax_return_response_invalid",
      "Company-tax-return authority returned XML outside the expected schema.",
    );
  }
}

function parseCalculatedDocuments(value: unknown): CompanyTaxReturnCalculatedDocument[] {
  if (value === undefined || value === null) return [];
  const container = assertRecord(value);
  return asArray(container.dokument, MAX_AUTHORITY_DOCUMENTS).map((candidate) => {
    const document = assertRecord(candidate);
    const type = requiredText(document.type, 100);
    if (!calculatedDocumentTypes.has(type as CompanyTaxReturnCalculatedDocument["type"])) throw new Error("invalid");
    if (document.encoding !== "utf-8") throw new Error("invalid");
    const decoded = decodeAuthorityXml(document.content, "Calculated company-tax-return document");
    return {
      type: type as CompanyTaxReturnCalculatedDocument["type"],
      encoding: "utf-8" as const,
      ...decoded,
    };
  });
}

function parseDeviationFeedback(
  value: unknown,
  source: "calculation" | "validation",
): CompanyTaxReturnValidationFeedback[] {
  if (value === undefined || value === null) return [];
  const container = assertRecord(value);
  return asArray(container.avvik, MAX_FEEDBACK_ITEMS).map((candidate) => {
    const deviation = assertRecord(candidate);
    const information = optionalText(deviation.oevrigInformasjon);
    return {
      level: source === "validation" ? "error" as const : "warning" as const,
      source,
      code: requiredText(deviation.avvikstype, 256),
      message:
        information ??
        (source === "validation"
          ? "Skatteetatens validering fant et avvik."
          : "Beregnet verdi avviker fra mottatt verdi."),
      occurrenceId: optionalText(deviation.forekomstidentifikator),
      receivedValue: optionalText(deviation.mottattVerdi),
      calculatedValue: optionalText(deviation.beregnetVerdi),
      difference: optionalText(deviation.avvikIVerdi),
      path: optionalText(deviation.sti),
    };
  });
}

function parseGuidanceFeedback(value: unknown): CompanyTaxReturnValidationFeedback[] {
  if (value === undefined || value === null) return [];
  const container = assertRecord(value);
  return asArray(container.veiledning, MAX_FEEDBACK_ITEMS).map((candidate) => {
    const guidance = assertRecord(candidate);
    return {
      level: "info" as const,
      source: "guidance" as const,
      code: requiredText(guidance.veiledningstype, 256),
      message: optionalText(guidance.hjelpetekst) ?? "Skatteetaten har gitt veiledning til skattemeldingen.",
      occurrenceId: optionalText(guidance.forekomstidentifikator),
      strategy: optionalText(guidance.betjeningsstrategi),
      path: optionalText(guidance.sti),
    };
  });
}

function parseValidationResponse(xml: string, calculationOnly: boolean): CompanyTaxReturnValidationResult {
  try {
    const root = parseRoot(xml, RESPONSE_ROOT, RESPONSE_NAMESPACE);
    const result = requiredText(root.resultatAvValidering, 64);
    if (result !== "validertOK" && result !== "validertMedFeil") throw new Error("invalid");
    const reasons = asArray(root.aarsakTilValidertMedFeil, MAX_FEEDBACK_ITEMS).map((value) => requiredText(value));
    const feedback = [
      ...parseDeviationFeedback(root.avvikEtterBeregning, "calculation"),
      ...parseGuidanceFeedback(root.veiledningEtterKontroll),
      ...parseDeviationFeedback(root.avvikVedValidering, "validation"),
      ...reasons.map((reason) => ({
        level: "error" as const,
        source: "validation" as const,
        code: "company_tax_return_validation_failed",
        message: reason,
      })),
    ];
    if (feedback.length > MAX_FEEDBACK_ITEMS) throw new Error("invalid");
    const documents = parseCalculatedDocuments(root.dokumenter);
    return {
      result,
      calculationOnly,
      validForSubmission:
        !calculationOnly && result === "validertOK" && !feedback.some((item) => item.level === "error"),
      reasons,
      feedback,
      documents,
    };
  } catch (error) {
    if (error instanceof CompanyTaxReturnAuthorityError) throw error;
    throw authorityError(
      "company_tax_return_response_invalid",
      "Company-tax-return authority returned XML outside the expected validation schema.",
    );
  }
}

function parseCurrentDocument(value: unknown, label: string) {
  const document = assertRecord(value);
  if (document.encoding !== "utf-8") throw new Error("invalid");
  return {
    id: requiredText(document.id),
    encoding: "utf-8" as const,
    xml: decodeAuthorityXml(document.content, label).xml,
  };
}

function parseLockedFields(
  value: unknown,
  key: "laastFeltSkattemelding" | "laastFeltNaeringsspesifikasjon",
  document: "skattemeldingUpersonlig" | "naeringsspesifikasjon",
) {
  if (value === undefined || value === null) return [];
  const container = assertRecord(value);
  return asArray(container[key], MAX_LOCKED_FIELDS).map((candidate) => {
    const locked = assertRecord(candidate);
    return {
      document,
      occurrenceId: optionalText(locked.forekomstidentifikator),
      value: optionalText(locked.verdi),
      path: optionalText(locked.sti),
      information: optionalText(locked.oevrigInformasjon),
    };
  });
}

function parseCurrentDraftResponse(xml: string): CompanyTaxReturnCurrentDraft {
  try {
    const root = parseRoot(xml, DRAFT_RESPONSE_ROOT, DRAFT_RESPONSE_NAMESPACE);
    const documents = assertRecord(root.dokumenter);
    const rawTaxReturn = assertRecord(documents.skattemeldingdokument);
    const taxType = requiredText(rawTaxReturn.type, 100);
    if (taxType !== "skattemeldingUpersonligUtkast" && taxType !== "skattemeldingUpersonligFastsatt") {
      throw new Error("invalid");
    }
    const type = taxType as CompanyTaxReturnCurrentDraft["taxReturn"]["type"];
    const taxReturn = { ...parseCurrentDocument(rawTaxReturn, "Current company tax return"), type };
    const businessSpecification = documents.naeringsspesifikasjondokument
      ? parseCurrentDocument(documents.naeringsspesifikasjondokument, "Current company business specification")
      : null;
    const lockedFields = [
      ...parseLockedFields(root.laasteFelt, "laastFeltSkattemelding", "skattemeldingUpersonlig"),
      ...parseLockedFields(root.laasteFelt, "laastFeltNaeringsspesifikasjon", "naeringsspesifikasjon"),
    ];
    if (lockedFields.length > MAX_LOCKED_FIELDS) throw new Error("invalid");
    return { taxReturn, businessSpecification, lockedFields };
  } catch (error) {
    if (error instanceof CompanyTaxReturnAuthorityError) throw error;
    throw authorityError(
      "company_tax_return_response_invalid",
      "Company-tax-return authority returned XML outside the expected current-draft schema.",
    );
  }
}

function ensureResponse(value: unknown, maximum: number): CompanyTaxReturnAuthorityTransportResponse {
  if (!value || typeof value !== "object") {
    throw authorityError(
      "company_tax_return_transport_invalid",
      "Company-tax-return transport returned no response.",
      true,
    );
  }
  const candidate = value as Partial<CompanyTaxReturnAuthorityTransportResponse>;
  if (!Number.isInteger(candidate.status) || !candidate.headers || !(candidate.body instanceof Uint8Array)) {
    throw authorityError(
      "company_tax_return_transport_invalid",
      "Company-tax-return transport returned an invalid response.",
      true,
    );
  }
  if (candidate.body.byteLength > maximum) {
    throw authorityError(
      "company_tax_return_response_too_large",
      "Company-tax-return authority response exceeded the configured limit.",
      true,
    );
  }
  return candidate as CompanyTaxReturnAuthorityTransportResponse;
}

function decodeResponseXml(response: CompanyTaxReturnAuthorityTransportResponse) {
  const contentType = normalizedContentType(response.headers);
  if (contentType !== "application/xml" && contentType !== "text/xml") {
    throw authorityError(
      "company_tax_return_response_content_type_invalid",
      "Company-tax-return authority did not return XML.",
    );
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(response.body);
  } catch {
    throw authorityError(
      "company_tax_return_response_invalid",
      "Company-tax-return authority returned invalid UTF-8 XML.",
    );
  }
}

async function readBoundedBody(response: Response, maximum: number) {
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > maximum) {
      await reader.cancel();
      throw authorityError(
        "company_tax_return_response_too_large",
        "Company-tax-return authority response exceeded the configured limit.",
        true,
      );
    }
    chunks.push(value);
  }
  const result = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result;
}

export function createFetchCompanyTaxReturnAuthorityTransport(
  fetchImplementation: typeof fetch = fetch,
): CompanyTaxReturnAuthorityTransport {
  return async (request) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), request.timeoutMs);
    try {
      const response = await fetchImplementation(request.url, {
        method: request.method,
        headers: request.headers,
        body: request.body,
        redirect: "error",
        signal: controller.signal,
      });
      return {
        status: response.status,
        headers: Object.fromEntries(response.headers.entries()),
        body: await readBoundedBody(response, request.maxResponseBytes),
      };
    } catch (error) {
      if (error instanceof CompanyTaxReturnAuthorityError) throw error;
      const timedOut = error instanceof DOMException && error.name === "AbortError";
      throw authorityError(
        timedOut ? "company_tax_return_transport_timeout" : "company_tax_return_transport_failed",
        timedOut
          ? "Company-tax-return authority request timed out."
          : "Company-tax-return authority request failed before a response was received.",
        true,
      );
    } finally {
      clearTimeout(timeout);
    }
  };
}

export function createCompanyTaxReturnAuthorityClient(options: ClientOptions): CompanyTaxReturnAuthorityClient {
  assertEnvironment(options.environment);
  assertAccessToken(options.accessToken);
  const timeoutMs = assertBoundedInteger(
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    1_000,
    60_000,
    "company_tax_return_timeout_invalid",
    "Company-tax-return timeout",
  );
  const maxResponseBytes = assertBoundedInteger(
    options.maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES,
    64,
    50 * 1024 * 1024,
    "company_tax_return_response_limit_invalid",
    "Company-tax-return response limit",
  );
  const transport = options.transport ?? createFetchCompanyTaxReturnAuthorityTransport();
  const baseUrl = COMPANY_TAX_RETURN_VALIDATION_BASE_URLS[options.environment];
  const headers = {
    Authorization: `Bearer ${options.accessToken}`,
    Accept: "application/xml",
  };

  async function request(input: Omit<CompanyTaxReturnAuthorityTransportRequest, "timeoutMs" | "maxResponseBytes">) {
    let transported: unknown;
    try {
      transported = await transport({ ...input, timeoutMs, maxResponseBytes });
    } catch (error) {
      if (error instanceof CompanyTaxReturnAuthorityError) throw error;
      throw authorityError(
        "company_tax_return_transport_failed",
        "Company-tax-return authority request failed before a response was received.",
        true,
      );
    }
    const response = ensureResponse(transported, maxResponseBytes);
    if (response.status !== 200) {
      const retryable =
        response.status === 401 ||
        response.status === 408 ||
        response.status === 425 ||
        response.status === 429 ||
        response.status >= 500;
      throw authorityError(
        `company_tax_return_http_${response.status}`,
        `Company-tax-return authority request failed (HTTP ${response.status}).`,
        retryable,
        response.status,
      );
    }
    return decodeResponseXml(response);
  }

  async function validate(
    input: CompanyTaxReturnValidationInput,
    mode: CompanyTaxReturnValidationMode,
  ) {
    const organizationNumber = assertOrganizationNumber(input.organizationNumber);
    const incomeYear = assertIncomeYear(input.incomeYear);
    const body = buildCompanyTaxReturnValidationEnvelope({ ...input, mode });
    const endpoint = mode === "filing" ? "valider" : "validertest";
    const xml = await request({
      method: "POST",
      url: `${baseUrl}/${endpoint}/${incomeYear}/${organizationNumber}`,
      headers: { ...headers, "Content-Type": "application/xml; charset=utf-8" },
      body,
    });
    return parseValidationResponse(xml, mode === "calculation-only");
  }

  return {
    environment: options.environment,
    async getCurrentDraft(input) {
      const organizationNumber = assertOrganizationNumber(input.organizationNumber);
      const incomeYear = assertIncomeYear(input.incomeYear);
      const xml = await request({
        method: "GET",
        url: `${baseUrl}/${incomeYear}/${organizationNumber}`,
        headers,
      });
      return parseCurrentDraftResponse(xml);
    },
    validateForFiling(input) {
      return validate(input, "filing");
    },
    calculateWithoutCurrentDraft(input) {
      return validate(input, "calculation-only");
    },
  };
}
