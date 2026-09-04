import assert from "node:assert/strict";
import test from "node:test";

import { persistAndRegisterCorporateDocumentDraft } from "../features/corporate-governance/draft-lifecycle.ts";

const artifacts = [
  { documentId: "11111111-1111-4111-8111-111111111111" },
  { documentId: "22222222-2222-4222-8222-222222222222" },
];

test("registration failure removes every newly persisted governance document", async () => {
  const removed = [];
  const registrationFailure = new Error("registration unavailable");

  await assert.rejects(
    persistAndRegisterCorporateDocumentDraft({
      persist: async () => ({ artifacts }),
      register: async () => {
        throw registrationFailure;
      },
      remove: async (artifact) => {
        removed.push(artifact.documentId);
      },
    }),
    registrationFailure,
  );

  assert.deepEqual(removed.sort(), artifacts.map((artifact) => artifact.documentId).sort());
});

test("registration failure preserves cleanup failures for reconciliation", async () => {
  const registrationFailure = new Error("registration unavailable");
  const cleanupFailure = new Error("document remained linked");

  await assert.rejects(
    persistAndRegisterCorporateDocumentDraft({
      persist: async () => ({ artifacts }),
      register: async () => {
        throw registrationFailure;
      },
      remove: async (artifact) => {
        if (artifact.documentId === artifacts[0].documentId) throw cleanupFailure;
      },
    }),
    (error) => error instanceof AggregateError
      && error.errors.includes(registrationFailure)
      && error.errors.includes(cleanupFailure),
  );
});
