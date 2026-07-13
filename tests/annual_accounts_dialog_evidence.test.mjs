import assert from "node:assert/strict";
import test from "node:test";

import {
  ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID,
  ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_URN,
  AnnualAccountsDialogEvidenceError,
  verifyAnnualAccountsDialogEvidence,
} from "../app/lib/annual-accounts-dialog-evidence.ts";

const operationId = "12345678-1234-4234-9234-123456789abc";
const instanceGuid = "232c5390-9479-4506-a266-9890d7287bfb";
const dialogId = "0193d51a-ec30-7d58-b727-6ce65964d3d4";
const transmissionId = "0193d51a-ec30-7d58-b727-6ce65964d3d5";
const attachmentId = "0193d51a-ec30-7d58-b727-6ce65964d3d6";
const urlId = "0193d51a-ec30-7d58-b727-6ce65964d3d7";
const completionEvidence = {
  schemaVersion: 1,
  environment: "test",
  operationId,
  organizationNumber: "310279617",
  incomeYear: 2025,
  instance: { ownerPartyId: "500700", instanceGuid },
  completedAt: "2026-07-13T12:42:31.123Z",
  mainFormId: "ce8665c1-01c3-49f7-960f-196b250a2266",
  accountsFormId: "0445d618-28b8-4af5-95e0-c8c989487e7a",
  signatureDataElementId: "7b8b2632-5b85-4d31-86cc-0c8766e4e079",
  mainFormHash: "a".repeat(64),
  accountsFormHash: "b".repeat(64),
};

function dialog(overrides = {}) {
  return {
    id: dialogId,
    revision: "12345678-1234-4234-9234-123456789abd",
    org: "brg",
    serviceResource: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_URN,
    party: "urn:altinn:organization:identifier-no:310279617",
    status: "Completed",
    createdAt: "2026-07-13T12:00:00Z",
    updatedAt: "2026-07-13T12:43:00Z",
    transmissions: [
      {
        id: transmissionId,
        createdAt: "2026-07-13T12:43:00Z",
        isAuthorized: true,
        type: "Submission",
        attachments: [
          {
            id: attachmentId,
            name: "provider receipt",
            expiresAt: null,
            urls: [
              {
                id: urlId,
                url: "https://example.invalid/provider/receipt",
                mediaType: "application/pdf",
                consumerType: "Api",
              },
            ],
          },
        ],
      },
    ],
    providerSecret: "must not be retained",
    ...overrides,
  };
}

test("ties a completed annual-accounts dialog to the exact signed Altinn instance", async () => {
  const calls = [];
  const client = {
    environment: "test",
    async lookupDialogByInstance(input) {
      calls.push({ operation: "lookup", input });
      return {
        dialogId,
        instanceRef: `urn:altinn:instance-id:500700/${instanceGuid}`,
        party: "urn:altinn:organization:identifier-no:310279617",
        serviceResourceId: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID,
        serviceOwnerCode: "brg",
      };
    },
    async getDialog(input) {
      calls.push({ operation: "get", input });
      return dialog();
    },
  };

  const evidence = await verifyAnnualAccountsDialogEvidence({ completionEvidence, client });

  assert.deepEqual(calls, [
    {
      operation: "lookup",
      input: {
        instance: { ownerPartyId: "500700", instanceGuid },
        expectedPartyOrgNumber: "310279617",
        expectedServiceResourceId: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID,
      },
    },
    {
      operation: "get",
      input: {
        dialogId,
        expectedPartyOrgNumber: "310279617",
        expectedServiceResource: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_URN,
      },
    },
  ]);
  assert.deepEqual(evidence, {
    schemaVersion: 1,
    environment: "test",
    operationId,
    organizationNumber: "310279617",
    incomeYear: 2025,
    instance: { ownerPartyId: "500700", instanceGuid },
    completionEvidenceSha256: evidence.completionEvidenceSha256,
    dialogId,
    dialogRevision: "12345678-1234-4234-9234-123456789abd",
    dialogStatus: "Completed",
    dialogCreatedAt: "2026-07-13T12:00:00Z",
    dialogUpdatedAt: "2026-07-13T12:43:00Z",
    serviceResourceId: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID,
    serviceOwnerCode: "brg",
    transmissionCount: 1,
    authorizedTransmissionCount: 1,
    authorizedAttachmentCount: 1,
    authorizedApiAttachmentCount: 1,
  });
  assert.match(evidence.completionEvidenceSha256, /^[0-9a-f]{64}$/u);
  assert.doesNotMatch(JSON.stringify(evidence), /provider receipt|providerSecret|example\.invalid/u);
});

test("rejects dialogs that are unfinished or belong to another instance boundary", async () => {
  const variants = [
    { lookup: { dialogId, instanceRef: "urn:altinn:instance-id:500701/232c5390-9479-4506-a266-9890d7287bfb", party: "urn:altinn:organization:identifier-no:310279617", serviceResourceId: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID, serviceOwnerCode: "brg" } },
    { lookup: { dialogId, instanceRef: `urn:altinn:instance-id:500700/${instanceGuid}`, party: "urn:altinn:organization:identifier-no:930835978", serviceResourceId: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID, serviceOwnerCode: "brg" } },
    { lookup: { dialogId, instanceRef: `urn:altinn:instance-id:500700/${instanceGuid}`, party: "urn:altinn:organization:identifier-no:310279617", serviceResourceId: "other", serviceOwnerCode: "brg" } },
    { lookup: { dialogId, instanceRef: `urn:altinn:instance-id:500700/${instanceGuid}`, party: "urn:altinn:organization:identifier-no:310279617", serviceResourceId: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID, serviceOwnerCode: "other" } },
    { dialog: dialog({ status: "Awaiting" }) },
    { dialog: dialog({ id: "0193d51a-ec30-7d58-b727-6ce65964d3d8" }) },
    { dialog: dialog({ party: "urn:altinn:organization:identifier-no:930835978" }) },
    { dialog: dialog({ updatedAt: "2026-07-13T12:42:30Z" }) },
  ];

  for (const variant of variants) {
    const client = {
      environment: "test",
      async lookupDialogByInstance() {
        return variant.lookup ?? {
          dialogId,
          instanceRef: `urn:altinn:instance-id:500700/${instanceGuid}`,
          party: "urn:altinn:organization:identifier-no:310279617",
          serviceResourceId: ANNUAL_ACCOUNTS_DIALOGPORTEN_RESOURCE_ID,
          serviceOwnerCode: "brg",
        };
      },
      async getDialog() {
        return variant.dialog ?? dialog();
      },
    };
    await assert.rejects(
      verifyAnnualAccountsDialogEvidence({ completionEvidence, client }),
      (error) =>
        error instanceof AnnualAccountsDialogEvidenceError &&
        error.code === "annual_accounts_dialog_evidence_invalid",
    );
  }
});

test("rejects tampered signed-instance evidence before calling Dialogporten", async () => {
  let calls = 0;
  const client = {
    environment: "test",
    async lookupDialogByInstance() { calls += 1; throw new Error("must not call"); },
    async getDialog() { calls += 1; throw new Error("must not call"); },
  };
  await assert.rejects(
    verifyAnnualAccountsDialogEvidence({
      completionEvidence: { ...completionEvidence, accessToken: "must-not-be-accepted" },
      client,
    }),
    (error) =>
      error instanceof AnnualAccountsDialogEvidenceError &&
      error.code === "annual_accounts_dialog_completion_invalid",
  );
  assert.equal(calls, 0);
});
