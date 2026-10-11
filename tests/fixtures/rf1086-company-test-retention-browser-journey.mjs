import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fixtureTableTransaction } from "../support/rf1086-fixture-access.mjs";

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export async function exerciseCompanyTestRetention({ page, siteOrigin, company, openings,
  database, api, ownerId, outsiderId, ownerToken, outsiderToken, lowAalToken,
  python, environment, sourceDatabaseUrl, readerDatabaseUrl, supabaseUrl, anonKey }) {
  const authorization = { Authorization: `Bearer ${ownerToken}` };
  const originalIds = new Set();
  let acceptedId;
  await database.query("insert into public.company_memberships(company_id,user_id,role,accepted_at) values($1,$2,'owner',now())",
    [company.id, outsiderId]);
  try {
    for (const [index, status] of ["pending", "blocked", "rejected", "accepted"].entries()) {
      const actorToken = index % 2 ? outsiderToken : ownerToken;
      const result = await api.rf1086RecordTestEvidence({ companyId: company.id,
        environment: index % 2 ? "test" : "manual_evidence", status,
        testReference: `Owned company test ${index}: ${"X".repeat(index === 0 ? 8192 : 8)}`,
        feedbackSummary: `Original ø feedback ${index}\n${"ø".repeat(16000)}`,
        receiptReference: index % 2 ? `opaque-receipt-${index}` : null,
        archiveReference: `opaque-archive-${index}`, evidenceUrl: "https://unreachable.invalid/original",
        payloadHash: index % 2 ? "A".repeat(64) : null },
      { headers: { Authorization: `Bearer ${actorToken}` } });
      assert.equal(result.companyId, company.id);
      assert.equal(result.incomeYear, null);
      originalIds.add(result.recordId);
      if (status === "accepted") acceptedId = result.recordId;
    }
  } finally {
    const removed = await database.query("delete from public.company_memberships where company_id=$1 and user_id=$2 returning user_id",
      [company.id, outsiderId]);
    assert.equal(removed.rowCount, 1);
  }
  // Existing commands create synthetic simulations. Their two reference links
  // are explicit fixture setup, not authority receipts or a new legal export.
  // The dedicated company preserves every pre-existing filing scenario.
  for (const { setupId } of openings) {
    const preview = await api.rf1086GeneratePreview({ companyId: company.id, openingSnapshotId: setupId }, { headers: authorization });
    const simulation = await api.rf1086ConfirmSimulation({ previewId: preview.recordId, authorityConfirmed: true, previewConfirmed: true }, { headers: authorization });
    await fixtureTableTransaction(database, ["shareholder_register_filing.filing_submissions"], async () => {
      const linked = await database.query("update shareholder_register_filing.filing_submissions set authority_test_run_id=$1 where id=$2 and company_id=$3 returning id",
        [acceptedId, simulation.recordId, company.id]);
      assert.equal(linked.rowCount, 1);
    });
  }
  const oracle = await fixtureTableTransaction(database,
    ["shareholder_register_filing.authority_test_runs", "shareholder_register_filing.filing_submissions"], async () => {
      const rows = (await database.query(`select id::text,company_id::text,obligation,environment,status,
        test_reference,feedback_summary,receipt_reference,archive_reference,evidence_url,payload_hash,recorded_by::text,
        to_char(recorded_at at time zone 'UTC',case when date_trunc('second',recorded_at)=recorded_at
          then 'YYYY-MM-DD"T"HH24:MI:SS' else 'YYYY-MM-DD"T"HH24:MI:SS.US' end)||'+00:00' recorded_at
        from shareholder_register_filing.authority_test_runs where company_id=$1 and obligation='aksjonaerregisteroppgaven' order by id`, [company.id])).rows;
      const links = (await database.query("select income_year,authority_test_run_id::text from shareholder_register_filing.filing_submissions where company_id=$1 order by income_year", [company.id])).rows;
      assert.deepEqual(links.map(row => row.income_year), openings.map(row => row.incomeYear).sort());
      assert.ok(links.every(row => originalIds.has(row.authority_test_run_id)));
      assert.ok(rows.some(row => !links.some(link => link.authority_test_run_id === row.id)), "unlinked originals required");
      return rows;
    });
  assert.deepEqual(new Set(oracle.map(row => row.id)), originalIds);
  assert.deepEqual(new Set(oracle.map(row => row.recorded_by)), new Set([ownerId, outsiderId]));
  assert.ok(oracle.every(row => Object.keys(row).length === 13));
  const read = await api.rf1086ReadCompanyTestRetention(company.id, { headers: authorization });
  const withoutMfa = await api.rf1086ReadCompanyTestRetention(company.id,
    { headers: { Authorization: `Bearer ${lowAalToken}` } });
  assert.equal(read.coverage, "complete");
  assert.equal(withoutMfa.coverage, "complete");
  assert.deepEqual(read.records, oracle);
  assert.deepEqual(withoutMfa.records, oracle);
  assert.equal(read.recordCount, 4);
  assert.equal(read.recordsSha256, createHash("sha256").update(canonical(oracle)).digest("hex"));
  await assert.rejects(() => api.rf1086DownloadCompanyTestRetention(company.id,
    { headers: { Authorization: `Bearer ${lowAalToken}` } }), error => error.status === 403 && error.problem?.code === "FRESH_MFA_REQUIRED");
  const href = `/companies/${company.id}/rf1086-test-history`;
  await page.goto(new URL(href, siteOrigin).href);
  await page.getByRole("heading", { name: `Testhistorikk for ${company.name}`, exact: true }).waitFor();
  assert.equal(await page.locator("details").count(), 4);
  await page.locator("details").first().locator("summary").click();
  assert.equal(await page.locator("details").first().locator("dt").count(), 13);
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `company test history overflow at ${width}`);
  }
  const saved = page.waitForEvent("download");
  await page.getByRole("link", { name: "Last ned hele testhistorikken", exact: true }).click();
  const download = await saved;
  assert.equal(await download.failure(), null);
  assert.equal(download.suggestedFilename(), `rf1086-company-tests-${company.id}.ndjson`);
  const streamPath = await download.path();
  assert.ok(streamPath);
  const directory = mkdtempSync(join(tmpdir(), "talli-company-test-inventory-"));
  try {
    const expectation = join(directory, "writer-expectation.json");
    writeFileSync(expectation, canonical({ codec: read.codec, companyId: company.id,
      scope: read.scope, coverage: "complete", observedAt: read.observedAt,
      recordCount: oracle.length, recordsSha256: read.recordsSha256, records: oracle }), { mode: 0o600 });
    const result = JSON.parse(execFileSync(python, ["scripts/rehearse-rf1086-company-test-retention-restore.py",
      "--company-id", company.id, "--stream", streamPath, "--writer-expectation", expectation], {
      cwd: process.cwd(), env: { ...environment, DATABASE_URL: sourceDatabaseUrl,
        TALLI_LEDGER_DATABASE_URL: readerDatabaseUrl, SUPABASE_URL: supabaseUrl,
        SUPABASE_ANON_KEY: anonKey, TALLI_RF_RESTORE_OWNER_TOKEN: ownerToken,
        TALLI_RF_RESTORE_OUTSIDER_TOKEN: outsiderToken }, encoding: "utf8", timeout: 180_000,
      // Cooperative cancellation; the runner finishes its owned acquisition/cleanup.
      killSignal: "SIGTERM" }));
    assert.equal(result.status, "verified_owned_company_test_inventory_restore");
    assert.equal(result.sourceObservationUnchanged, true);
    assert.equal(result.sourceInventoryUnchanged, true);
    assert.equal(result.sourceIdentityAndRolesUnchanged, true);
    assert.equal(result.independentRecoveryResourcesRemoved, true);
    assert.equal(result.legalCompanyArchiveReceipt, false);
    assert.equal(result.hostedKeyRecoveryVerified, false);
    assert.equal(result.inventory.record_count, 4);
    assert.equal(result.inventory.records_sha256, read.recordsSha256);
    for (const key of ["original_recorded_actors_preserved", "current_membership_roles_verified",
      "outsider_unaccepted_banned_and_revoked_denied", "revoked_and_soft_deleted_sessions_denied",
      "authorized_successor_recovered_inventory", "stateless_owner_session_denied"])
      assert.equal(result.inventory[key], true, key);
    assert.equal(result.inventory.physical_auth_user_erasure, "blocked-by-preserved-historical-foreign-keys");
    for (const key of ["independentClusterRestored", "independentAuthRestored", "authHttpTargetBindingVerified",
      "roleAttributesAndMembershipsRestored", "ownershipGrantsAndRlsRestored", "authRowsRestoredExactly"])
      assert.equal(result.identity[key], true, key);
    const after = await api.rf1086ReadCompanyTestRetention(company.id, { headers: authorization });
    assert.deepEqual(after.records, oracle);
    assert.equal(after.recordsSha256, read.recordsSha256);
    return { ownedCompanyInventoryPipelineVerified: true, recordCount: 4,
      recordsSha256: read.recordsSha256, sourceArtifactSha256: result.sourceArtifactSha256,
      bundleSha256: result.bundleSha256 };
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}
