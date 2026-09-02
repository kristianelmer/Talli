import { randomUUID } from "node:crypto";

import { rf1086FeedbackFileName } from "./documents.ts";
import {
  Rf1086FeedbackArtifactPersistenceError,
  createRf1086FeedbackArtifactPersistenceError,
  type Rf1086ReconciliationArtifact,
} from "./rf1086-production.ts";
import type { createSupabaseServiceRoleClient } from "./supabase/server.ts";

type FeedbackPersistenceService = ReturnType<typeof createSupabaseServiceRoleClient>;

type FeedbackPersistenceInput = {
  submissionId: string;
  companyId: string;
  incomeYear: number;
  userId: string;
};

export type Rf1086FeedbackDocumentStore = {
  store(input: {
    documentId: string;
    fileName: string;
    artifact: Rf1086ReconciliationArtifact;
  }): Promise<{ contentSha256: string | null; byteLength: number | null }>;
  remove(documentId: string): Promise<void>;
};

function persistenceError(
  message: string,
  cause: unknown,
  options: { integrityFailure?: boolean } = {},
) {
  return createRf1086FeedbackArtifactPersistenceError(message, cause, options);
}

export function createRf1086FeedbackArtifactRecorder(
  service: FeedbackPersistenceService,
  input: FeedbackPersistenceInput,
  documents: Rf1086FeedbackDocumentStore,
) {
  return async function recordArtifact(artifact: Rf1086ReconciliationArtifact) {
    const { data: existing, error: existingError } = await service
      .from("production_feedback_artifacts")
      .select("document_id,sha256")
      .eq("submission_id", input.submissionId)
      .eq("sha256", artifact.sha256)
      .maybeSingle();
    if (existingError) {
      throw persistenceError("Kunne ikke kontrollere tilbakemeldingsarkivet.", existingError);
    }
    if (existing) {
      if (existing.sha256 !== artifact.sha256) {
        throw persistenceError(
          "Tilbakemeldingsmetadata samsvarer ikke med forventet dokument.",
          null,
          { integrityFailure: true },
        );
      }
      return existing.sha256;
    }

    const documentId = randomUUID();
    const stored = await documents.store({
      documentId,
      fileName: rf1086FeedbackFileName(artifact.contentType, artifact.sha256),
      artifact,
    });
    if (stored.contentSha256 !== artifact.sha256 || stored.byteLength !== artifact.byteLength) {
      await documents.remove(documentId).catch(() => undefined);
      throw persistenceError(
        "Tilbakemeldingsdokumentets integritetsbevis samsvarer ikke med journalen.",
        null,
        { integrityFailure: true },
      );
    }

    try {
      const { data, error } = await service.rpc("record_production_feedback_artifact", {
        p_company_id: input.companyId,
        p_submission_id: input.submissionId,
        p_document_id: documentId,
        p_authority_reference: artifact.authorityReference,
        p_content_type: artifact.contentType,
        p_byte_length: artifact.byteLength,
        p_sha256: artifact.sha256,
        p_classification: artifact.classification,
      });
      if (error || !data) {
        throw persistenceError("Kunne ikke registrere tilbakemeldingsmetadata.", error);
      }
      return artifact.sha256;
    } catch (error) {
      const persisted = await service
        .from("production_feedback_artifacts")
        .select("document_id,sha256")
        .eq("submission_id", input.submissionId)
        .eq("sha256", artifact.sha256)
        .maybeSingle();
      if (persisted.error) {
        throw persistenceError(
          "Kunne ikke avgjøre om tilbakemeldingsmetadata ble lagret.",
          persisted.error,
        );
      }
      if (persisted.data) {
        if (persisted.data.sha256 !== artifact.sha256) {
          throw persistenceError(
            "Tilbakemeldingsmetadata samsvarer ikke med forventet dokument.",
            null,
            { integrityFailure: true },
          );
        }
        if (persisted.data.document_id !== documentId) {
          await documents.remove(documentId).catch(() => undefined);
        }
        return persisted.data.sha256;
      }
      try {
        await documents.remove(documentId);
      } catch (cleanupError) {
        throw persistenceError(
          "Kunne ikke rydde opp dokumentjournalen etter en avvist lagring.",
          cleanupError,
        );
      }
      if (error instanceof Rf1086FeedbackArtifactPersistenceError) throw error;
      throw persistenceError("Tilbakemeldingen kunne ikke arkiveres sikkert.", error);
    }
  };
}
