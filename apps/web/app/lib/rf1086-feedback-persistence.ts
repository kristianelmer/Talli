import { createHash, randomUUID } from "node:crypto";

import {
  COMPANY_DOCUMENTS_BUCKET,
  rf1086FeedbackFileName,
  rf1086FeedbackStorageKey,
} from "./documents.ts";
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

function persistenceError(
  message: string,
  cause: unknown,
  options: { integrityFailure?: boolean } = {},
) {
  return createRf1086FeedbackArtifactPersistenceError(message, cause, options);
}

async function verifyPrivateReceipt(
  bucket: ReturnType<FeedbackPersistenceService["storage"]["from"]>,
  storageKey: string,
  artifact: Rf1086ReconciliationArtifact,
) {
  const stored = await bucket.download(storageKey);
  if (stored.error || !stored.data) {
    throw persistenceError(
      "Tilbakemeldingsdokumentet kunne ikke verifiseres i privat lagring.",
      stored.error,
    );
  }
  const bytes = new Uint8Array(await stored.data.arrayBuffer());
  const hash = createHash("sha256").update(bytes).digest("hex");
  if (bytes.byteLength !== artifact.byteLength || hash !== artifact.sha256) {
    throw persistenceError(
      "Tilbakemeldingsdokumentet i privat lagring samsvarer ikke med journalen.",
      null,
      { integrityFailure: true },
    );
  }
}

export function createRf1086FeedbackArtifactRecorder(
  service: FeedbackPersistenceService,
  input: FeedbackPersistenceInput,
) {
  const bucket = service.storage.from(COMPANY_DOCUMENTS_BUCKET);

  return async function recordArtifact(artifact: Rf1086ReconciliationArtifact) {
    const storageKey = rf1086FeedbackStorageKey(
      input.companyId,
      input.submissionId,
      artifact.sha256,
    );
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
      await verifyPrivateReceipt(bucket, storageKey, artifact);
      return existing.sha256;
    }

    const documentId = randomUUID();
    const upload = await bucket.upload(
      storageKey,
      artifact.bytes,
      { contentType: artifact.contentType, upsert: false },
    );
    if (upload.error) {
      try {
        await verifyPrivateReceipt(bucket, storageKey, artifact);
      } catch (error) {
        if (
          error instanceof Rf1086FeedbackArtifactPersistenceError
          && !error.retryable
        ) {
          throw error;
        }
        throw persistenceError(
          "Kunne ikke lagre tilbakemeldingsdokumentet.",
          upload.error,
        );
      }
    }

    let documentInserted = false;
    try {
      const { error: documentError } = await service.from("documents").insert({
        id: documentId,
        company_id: input.companyId,
        income_year: input.incomeYear,
        document_type: "authority_feedback",
        name: rf1086FeedbackFileName(artifact.contentType, artifact.sha256),
        linked_to: `production_filing_submission:${input.submissionId}`,
        status: "attached",
        retention_years: 5,
        storage_key: storageKey,
        created_by: input.userId,
      });
      if (documentError) {
        throw persistenceError(
          "Kunne ikke registrere tilbakemeldingsdokumentet.",
          documentError,
        );
      }
      documentInserted = true;

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
        throw persistenceError(
          "Kunne ikke registrere tilbakemeldingsmetadata.",
          error,
        );
      }
      await verifyPrivateReceipt(bucket, storageKey, artifact);
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
        await verifyPrivateReceipt(bucket, storageKey, artifact);
        if (documentInserted && persisted.data.document_id !== documentId) {
          await service.from("documents").delete().eq("id", documentId);
        }
        return persisted.data.sha256;
      }

      if (documentInserted) {
        const deleted = await service.from("documents").delete().eq("id", documentId);
        if (deleted.error) {
          throw persistenceError(
            "Kunne ikke rydde opp dokumentjournalen etter en avvist lagring.",
            deleted.error,
          );
        }
      }
      await bucket.remove([storageKey]);
      if (error instanceof Rf1086FeedbackArtifactPersistenceError) throw error;
      throw persistenceError("Tilbakemeldingen kunne ikke arkiveres sikkert.", error);
    }
  };
}
