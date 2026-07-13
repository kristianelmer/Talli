import { COMPANY_DOCUMENTS_BUCKET, MAX_DOCUMENT_UPLOAD_BYTES, documentStorageKey } from "./documents.ts";
import type { OwnerDividendActionPayload } from "./owner-dividend.ts";
import { runPythonCli } from "./python-engine.ts";

const EXPECTED_DOCUMENTS = {
  board_proposal: "styreforslag-og-protokoll-utbytte.pdf",
  general_meeting_minutes: "generalforsamlingsprotokoll-utbytte.pdf",
} as const;

type OwnerDividendDocumentKind = keyof typeof EXPECTED_DOCUMENTS;

export type GeneratedOwnerDividendDocument = {
  kind: OwnerDividendDocumentKind;
  fileName: string;
  contentType: "application/pdf";
  content: Buffer;
};

export type PreparedOwnerDividendDocument = GeneratedOwnerDividendDocument & {
  id: string;
  storageKey: string;
  metadata: {
    id: string;
    company_id: string;
    income_year: number;
    document_type: "corporate_document";
    name: string;
    linked_to: string;
    status: "generated_unsigned";
    retention_years: number;
    storage_key: string;
    created_by: string;
  };
};

export class OwnerDividendDocumentGenerationError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "OwnerDividendDocumentGenerationError";
    this.code = code;
  }
}

export async function generateOwnerDividendCorporateDocuments(input: {
  companyName: string;
  orgNumber: string;
  incomeYear: number;
  payload: OwnerDividendActionPayload;
}): Promise<GeneratedOwnerDividendDocument[]> {
  const result = await runPythonCli(["generate-owner-dividend-documents", "--stdin-json"], {
    company_name: input.companyName,
    org_number: input.orgNumber,
    income_year: input.incomeYear,
    decision_date: input.payload.decision_date,
    payment_date: input.payload.payment_date,
    total_amount: input.payload.total_amount,
    distributable_equity: input.payload.distributable_equity,
    liquidity_after_payment: input.payload.liquidity_after_payment,
    allocations: input.payload.allocations.map((allocation) => ({
      shareholder_id: allocation.shareholderId,
      shareholder_name: allocation.shareholderName,
      share_count: allocation.shareCount,
      amount: allocation.amount,
    })),
  });
  if (result.status !== 0) {
    throw new OwnerDividendDocumentGenerationError(
      "Selskapsdokumentene kunne ikke genereres.",
      "dividend_document_generation_failed",
    );
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {
    throw new OwnerDividendDocumentGenerationError(
      "Dokumentmotoren returnerte et ugyldig svar.",
      "invalid_dividend_document_response",
    );
  }
  if (!isRecord(parsed) || !Array.isArray(parsed.documents) || parsed.documents.length !== 2) {
    throw new OwnerDividendDocumentGenerationError(
      "Dokumentmotoren returnerte feil antall dokumenter.",
      "invalid_dividend_document_count",
    );
  }

  const seenKinds = new Set<string>();
  const documents = parsed.documents.map((value) => parseGeneratedDocument(value, seenKinds));
  if (seenKinds.size !== 2) {
    throw new OwnerDividendDocumentGenerationError(
      "Dokumentmotoren returnerte duplikate dokumenter.",
      "duplicate_dividend_document_kind",
    );
  }
  return documents;
}

export function prepareOwnerDividendCorporateDocuments(input: {
  companyId: string;
  incomeYear: number;
  actionId: string;
  createdBy: string;
  documents: GeneratedOwnerDividendDocument[];
}): PreparedOwnerDividendDocument[] {
  if (input.documents.length !== 2) {
    throw new OwnerDividendDocumentGenerationError(
      "Nøyaktig to selskapsdokumenter kreves.",
      "invalid_dividend_document_count",
    );
  }
  return input.documents.map((document) => {
    const id = crypto.randomUUID();
    const storageKey = documentStorageKey(input.companyId, input.incomeYear, id, document.fileName);
    return {
      ...document,
      id,
      storageKey,
      metadata: {
        id,
        company_id: input.companyId,
        income_year: input.incomeYear,
        document_type: "corporate_document",
        name: document.fileName,
        linked_to: input.actionId,
        status: "generated_unsigned",
        retention_years: 5,
        storage_key: storageKey,
        created_by: input.createdBy,
      },
    };
  });
}

export { COMPANY_DOCUMENTS_BUCKET };

function parseGeneratedDocument(value: unknown, seenKinds: Set<string>): GeneratedOwnerDividendDocument {
  if (!isRecord(value)) {
    throw invalidArtifact();
  }
  const { kind, file_name: fileName, content_type: contentType, base64 } = value;
  if (
    typeof kind !== "string" ||
    !(kind in EXPECTED_DOCUMENTS) ||
    typeof fileName !== "string" ||
    fileName !== EXPECTED_DOCUMENTS[kind as OwnerDividendDocumentKind] ||
    contentType !== "application/pdf" ||
    typeof base64 !== "string" ||
    !/^[A-Za-z0-9+/]+={0,2}$/u.test(base64)
  ) {
    throw invalidArtifact();
  }
  const content = Buffer.from(base64, "base64");
  if (
    content.byteLength === 0 ||
    content.byteLength > MAX_DOCUMENT_UPLOAD_BYTES ||
    !content.subarray(0, 5).equals(Buffer.from("%PDF-"))
  ) {
    throw invalidArtifact();
  }
  if (seenKinds.has(kind)) {
    throw new OwnerDividendDocumentGenerationError(
      "Dokumentmotoren returnerte duplikate dokumenter.",
      "duplicate_dividend_document_kind",
    );
  }
  seenKinds.add(kind);
  return {
    kind: kind as OwnerDividendDocumentKind,
    fileName,
    contentType,
    content,
  };
}

function invalidArtifact() {
  return new OwnerDividendDocumentGenerationError(
    "Dokumentmotoren returnerte et ugyldig PDF-dokument.",
    "invalid_dividend_document_artifact",
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
