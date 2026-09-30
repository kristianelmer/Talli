import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

export async function exerciseRfPilotExpiry({ companyId, incomeYear, entitlementId, api, authorization, mock }) {
  const options = { headers: authorization };
  const query = { companyId, incomeYear, obligation: "aksjonaerregisteroppgaven",
    caseProfile: "rf1086_full_year_v1", ...options };
  const before = await api.rf1086GetProductionArchiveSource(companyId, incomeYear, options);
  const providerCalls = mock.snapshot();
  assert.equal((await api.billingReadEntitlement(query)).pilotEntitlementId, entitlementId);
  const snapshot = await api.billingReadSnapshot({ companyIds: [companyId], ...options });
  const pilot = snapshot.pilotEntitlements.find(row => row.entitlementId === entitlementId);
  assert.ok(pilot, "exact pilot is missing before expiry");
  const command = { companyId, incomeYear, entitlementId, userId: pilot.userId,
    caseProfile: pilot.caseProfile, status: pilot.status, billingExempt: pilot.billingExempt,
    systemUserRequestId: pilot.systemUserRequestId, startsAt: pilot.startsAt,
    expiresAt: new Date(Date.now() - 1_000).toISOString(),
    evidenceReference: "synthetic-rf-expired-pilot-recovery" };
  assert.ok(Date.parse(command.startsAt) < Date.parse(command.expiresAt));
  const mutation = { ...options, idempotencyKey: randomUUID() };
  const expired = await api.billingManagePilotEntitlement(command, mutation);
  assert.equal(expired.entitlementId, entitlementId);
  assert.equal(expired.status, "active", "expiry must be tested independently of status revocation");
  assert.ok(Date.parse(expired.expiresAt) < Date.now());
  assert.deepEqual(await api.billingManagePilotEntitlement(command, mutation), expired);
  const denied = await api.billingReadEntitlement(query);
  assert.equal(denied.pilotEntitlementId, null);
  assert.equal(denied.allowed, false);
  assert.equal(denied.chargeAllowed, false);
  const after = await api.billingReadSnapshot({ companyIds: [companyId], ...options });
  assert.deepEqual(after.pilotEntitlements.find(row => row.entitlementId === entitlementId), expired);
  assert.deepEqual(after.paymentEvents, snapshot.paymentEvents, "expiry created a payment event");
  assert.deepEqual(await api.rf1086GetProductionArchiveSource(companyId, incomeYear, options), before);
  assert.deepEqual(mock.snapshot(), providerCalls, "expiry called a filing provider");
}

// Exercise the actual server export receipt and Company Access command. No
// fixture receipt or cancellation row substitutes for the owner operations.
export async function exerciseRfCancellation({ page, siteOrigin, companyId, incomeYear, api, authorization, mock }) {
  const options = { headers: authorization };
  const before = await api.rf1086GetProductionArchiveSource(companyId, incomeYear, options);
  const providerCalls = mock.snapshot();
  const response = await page.request.get(`${siteOrigin}/archive/${companyId}/${incomeYear}/download`);
  assert.equal(response.status(), 200, `company archive failed: ${await response.text()}`);
  assert.match(response.headers()["content-disposition"], /attachment;/u);
  const archive = await response.json();
  assert.equal(archive.rf1086ProductionEvidenceAvailability, "included");
  assert.equal(archive.rf1086Production.canonicalArchive, before.canonicalArchive);
  for (const field of ["sourceOriginals", "feedbackOriginals", "sourceHistoryDocuments"])
    assert.deepEqual(archive.rf1086Production[field], before[field], field);

  const command = { companyId, incomeYear, operationId: randomUUID(), reason: "Synthetic RF retention and recovery rehearsal" };
  const result = await api.companyAccessRequestCancellation(command, options);
  assert.equal(result.cancellation.status, "retention_hold");
  assert.equal(result.cancellation.companyId, companyId);
  assert.equal(result.cancellation.evidence.archiveIncomeYear, incomeYear);
  assert.equal(result.cancellation.evidence.legalReviewRequired, true);
  assert.deepEqual(await api.companyAccessRequestCancellation(command, options), result, "cancellation replay changed its receipt");
  assert.deepEqual((await api.companyAccessListCancellations(companyId, options)).cancellations, [result.cancellation]);
  assert.deepEqual(await api.rf1086GetProductionArchiveSource(companyId, incomeYear, options), before,
    "cancellation changed retained RF evidence");
  assert.deepEqual(mock.snapshot(), providerCalls, "archive/cancellation must not call a filing provider");
  return result.cancellation;
}

export async function exerciseRfFinalDeletion({ page, siteOrigin, companyId, incomeYear, api, authorization,
  reviewerId, reviewerAuthorization, cancellation, entitlementId, mock }) {
  const options = { headers: authorization };
  const reviewOptions = { headers: reviewerAuthorization };
  const before = await api.rf1086GetProductionArchiveSource(companyId, incomeYear, options);
  const previewId = (await api.rf1086Workspace(companyId, incomeYear, options)).previews[0].id;
  const providerCalls = mock.snapshot();
  const { grant } = await api.companyAccessGrantSupportAccess({ companyId, operatorUserId: reviewerId,
    operationId: randomUUID(), reason: "service_recovery", scopes: ["profile", "cancellation"],
    startsAt: new Date(Date.now() - 5_000).toISOString(), expiresAt: new Date(Date.now() + 600_000).toISOString() }, options);
  const reviewCommand = { companyId, expectedUpdatedAt: cancellation.updatedAt, operationId: randomUUID(),
    decision: "approved", evidenceReference: "synthetic-local-retention-review" };
  await assert.rejects(() => api.companyAccessReviewDeletion(cancellation.id, grant.caseId, reviewCommand, reviewOptions),
    error => error.status === 404 && error.problem?.code === "COMPANY_ACCESS_NOT_FOUND", "unopened support case admitted review");
  await api.companyAccessOpenSupportCase(grant.caseId, { operationId: randomUUID() }, reviewOptions);
  const review = await api.companyAccessReviewDeletion(cancellation.id, grant.caseId, reviewCommand, reviewOptions);
  assert.equal(review.cancellation.status, "deletion_approved");
  assert.equal(review.review.reviewedBy, reviewerId);
  assert.notEqual(reviewerId, cancellation.requestedBy);
  assert.deepEqual(await api.companyAccessReviewDeletion(cancellation.id, grant.caseId, reviewCommand, reviewOptions), review);

  // Review and support audit writes invalidate the earlier export. Finalization
  // must reject it, then admit an actual new complete company archive.
  const finalCommand = { companyId, operationId: randomUUID(), expectedUpdatedAt: review.cancellation.updatedAt };
  await assert.rejects(() => api.companyAccessFinalizeDeletion(cancellation.id, finalCommand, options),
    error => error.problem?.code === "CANCELLATION_PREREQUISITE_FAILED", "stale export admitted final deletion");
  const exported = await page.request.get(`${siteOrigin}/archive/${companyId}/${incomeYear}/download`);
  assert.equal(exported.status(), 200, `final archive failed: ${await exported.text()}`);
  assert.equal((await exported.json()).rf1086Production.canonicalArchive, before.canonicalArchive);
  const finalized = await api.companyAccessFinalizeDeletion(cancellation.id, finalCommand, options);
  assert.equal(finalized.cancellation.status, "deleted");
  assert.equal(finalized.cancellation.deletedBy, cancellation.requestedBy);
  assert.deepEqual(await api.companyAccessFinalizeDeletion(cancellation.id, finalCommand, options), finalized);
  assert.deepEqual(await api.rf1086GetProductionArchiveSource(companyId, incomeYear, options), before);
  await assert.rejects(() => api.rf1086PrepareSourceProductionReview({ companyId, incomeYear, previewId, entitlementId }, options),
    error => error.problem?.code === "SHAREHOLDER_REGISTER_FILING_COMPANY_YEAR_NOT_ADMITTED",
    "deleted company admitted a new consequential RF review");
  assert.deepEqual(mock.snapshot(), providerCalls, "deletion/recovery called a filing provider");
  return { cancellation: finalized.cancellation, supportCaseId: grant.caseId, reviewId: review.review.id };
}
