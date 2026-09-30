import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

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
