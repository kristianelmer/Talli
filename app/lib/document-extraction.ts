export type DocumentExtractionStatus =
  | "quarantined"
  | "ready_for_extraction"
  | "extracting"
  | "review_required"
  | "accepted"
  | "rejected"
  | "failed"
  | "provider_disabled";

export type DocumentExtractionInput = {
  companyId: string;
  documentId: string;
  storageKey: string;
  contentType: "application/pdf";
  sha256: string;
  status: "quarantined";
};

export type DocumentFieldSuggestion = {
  field: "amount" | "date" | "counter_account";
  value: number | string;
  confidence: number;
  evidence: string;
  untrusted: true;
};

export type DocumentExtractionResult = {
  providerRequestId: string;
  status: "review_required";
  ownerConfirmationRequired: true;
  suggestions: DocumentFieldSuggestion[];
};

export interface DocumentExtractionAdapter {
  readonly adapterKey: string;
  readonly mode: "disabled" | "test" | "production";
  extract(input: DocumentExtractionInput): Promise<DocumentExtractionResult>;
}

export class DocumentExtractionDisabledError extends Error {
  readonly code = "document_extraction_provider_disabled";

  constructor() {
    super("Dokumentuttrekk er deaktivert inntil leverandør, behandlingsregion, lagringstid og databehandleravtale er godkjent.");
    this.name = "DocumentExtractionDisabledError";
  }
}

export function createDisabledDocumentExtractionAdapter(): DocumentExtractionAdapter {
  return {
    adapterKey: "unconfigured",
    mode: "disabled",
    async extract() {
      throw new DocumentExtractionDisabledError();
    },
  };
}

export function validateDocumentExtractionInput(input: {
  companyId: string;
  documentId: string;
  storageKey: string;
  contentType: string;
  sha256: string;
}): DocumentExtractionInput {
  const companyId = input.companyId.trim();
  const documentId = input.documentId.trim();
  const storageKey = input.storageKey.trim();
  if (!companyId || !documentId) {
    throw new Error("Selskap og dokument må være identifisert.");
  }
  if (!storageKey.startsWith(`${companyId}/`) || !storageKey.includes(`/${documentId}/`)) {
    throw new Error("Dokumentet ligger ikke i selskapets lagringsområde.");
  }
  if (input.contentType !== "application/pdf") {
    throw new Error("Bare PDF kan sendes til dokumentuttrekk.");
  }
  const sha256 = input.sha256.trim().toLocaleLowerCase("en-US");
  if (!/^[a-f0-9]{64}$/.test(sha256)) {
    throw new Error("Dokumentet mangler gyldig SHA-256-kontrollsum.");
  }
  return {
    companyId,
    documentId,
    storageKey,
    contentType: "application/pdf",
    sha256,
    status: "quarantined",
  };
}

export function normalizeDocumentExtractionResult(input: {
  providerRequestId: string;
  suggestions: Array<{
    field: string;
    value: unknown;
    confidence: number;
    evidence: string;
  }>;
}): DocumentExtractionResult {
  const providerRequestId = input.providerRequestId.trim();
  if (!providerRequestId) {
    throw new Error("Uttrekksforespørselen mangler leverandørreferanse.");
  }
  if (input.suggestions.length === 0 || input.suggestions.length > 3) {
    throw new Error("Dokumentuttrekket må inneholde mellom ett og tre støttede forslag.");
  }

  const seen = new Set<string>();
  const suggestions = input.suggestions.map((suggestion): DocumentFieldSuggestion => {
    if (!['amount', 'date', 'counter_account'].includes(suggestion.field)) {
      throw new Error("Dokumentuttrekket inneholder et ustøttet felt.");
    }
    if (seen.has(suggestion.field)) {
      throw new Error("Dokumentuttrekket inneholder duplikate felt.");
    }
    seen.add(suggestion.field);
    if (!Number.isFinite(suggestion.confidence) || suggestion.confidence < 0 || suggestion.confidence > 1) {
      throw new Error("Dokumentuttrekket har ugyldig konfidens.");
    }
    const evidence = suggestion.evidence.trim().slice(0, 500);
    if (!evidence) {
      throw new Error("Dokumentuttrekket mangler feltbelegg.");
    }

    let value: number | string;
    if (suggestion.field === "amount") {
      if (
        typeof suggestion.value !== "number" ||
        !Number.isFinite(suggestion.value) ||
        suggestion.value <= 0 ||
        Math.round(suggestion.value * 100) / 100 !== suggestion.value
      ) {
        throw new Error("Dokumentuttrekket har ugyldig beløp.");
      }
      value = suggestion.value;
    } else if (suggestion.field === "date") {
      if (typeof suggestion.value !== "string" || !isIsoDate(suggestion.value)) {
        throw new Error("Dokumentuttrekket har ugyldig dato.");
      }
      value = suggestion.value;
    } else {
      if (suggestion.value !== "6700" && suggestion.value !== "7790") {
        throw new Error("Dokumentuttrekket foreslår en ustøttet motkonto.");
      }
      value = suggestion.value;
    }

    return {
      field: suggestion.field as DocumentFieldSuggestion["field"],
      value,
      confidence: suggestion.confidence,
      evidence,
      untrusted: true,
    };
  });

  return {
    providerRequestId,
    status: "review_required",
    ownerConfirmationRequired: true,
    suggestions,
  };
}

function isIsoDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }
  const date = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
