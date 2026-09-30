import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { fixtureTableTransaction } from "../support/rf1086-fixture-access.mjs";
import { isLoopbackSupabaseUrl } from "../support/supabase_fixture_safety.mjs";

// Uses the already authenticated owner and the loopback-only fresh filing mock.
// Only admission, opening facts and a pilot entitlement are prepared. Every
// source, preview, approval, operation and receipt below is created by the app.
export async function exerciseFullYearSourceJourney({ page, siteOrigin, company, incomeYear, database, ownerId,
  openingHolderId, entitlementId, api, authorization, storage, mock, python, environment, apiCalls, lostResponse, crashBackend, armPreparedCrash, predecessorFeedback = "accepted" }) {
  assert.ok(["accepted", "rejected"].includes(predecessorFeedback));
  const predecessorLabel = predecessorFeedback === "accepted" ? "Godkjent" : "Avvist";
  const scope = { companyId: company.id, incomeYear, headers: authorization };
  const options = { headers: authorization };
  const before = await api.rf1086Workspace(company.id, incomeYear, options);
  assert.deepEqual(before.previews, []);
  assert.deepEqual(before.approvals, []);
  assert.deepEqual(before.productionSubmissions, []);
  assert.equal((await api.rf1086ReadCurrentYearSource(scope)).currentSource, null);
  const entitlement = await api.billingReadEntitlement({ ...scope,
    obligation: "aksjonaerregisteroppgaven", caseProfile: "rf1086_full_year_v1" });
  assert.equal(entitlement.pilotEntitlementId, entitlementId);
  assert.equal(entitlement.billingExempt, true);
  assert.equal(entitlement.allowed, false, "legacy frozen readiness must not decide full-year review");
  const callsBefore = mock.snapshot().filter(({ service }) => service === "skatteetaten").length;

  // Upload original bytes via Documents' actual signed-upload and finalize API.
  const { documentId, document } = await uploadOriginal({ api, options, storage, company, incomeYear, consideration: "15000" });

  const sourceHref = `${siteOrigin}/filing/aksjonaerregisteroppgaven/source?companyId=${company.id}&incomeYear=${incomeYear}`;
  await page.goto(sourceHref);
  await page.getByRole("heading", { name: "Årsgrunnlag for aksjonærregisteroppgaven", exact: true }).waitFor();
  await page.getByRole("combobox", { name: /^Aksjeklasse/ }).selectOption("01");
  for (const [label, value] of [
    ["Aksjekapital ved årets start (kr)", "30000"], ["Aksjekapital ved årets slutt (kr)", "30000"],
    ["Pålydende per aksje ved årets start (kr)", "300"], ["Pålydende per aksje ved årets slutt (kr)", "300"],
    ["Antall aksjer ved årets start", "100"], ["Antall aksjer ved årets slutt", "100"],
    ["Innbetalt aksjekapital ved årets start (kr)", "30000"], ["Innbetalt aksjekapital ved årets slutt (kr)", "30000"],
    ["Innbetalt overkurs ved årets start (kr)", "0"], ["Innbetalt overkurs ved årets slutt (kr)", "0"],
  ]) await page.getByLabel(label, { exact: true }).fill(value);
  const buyer = randomUUID();
  for (const [index, id, holderName, org, opening, closing] of [
    [1, openingHolderId, "Synthetic Fixture Owner AS", "999999999", "100", "50"],
    [2, buyer, "Synthetic Buyer AS", "888888888", "0", "50"],
  ]) {
    await page.getByRole("button", { name: "Legg til aksjonær", exact: true }).click();
    const holder = page.getByRole("group", { name: `Aksjonær ${index}`, exact: true });
    await holder.getByLabel("Aksjonærreferanse", { exact: true }).fill(id);
    await holder.getByLabel("Navn", { exact: true }).fill(holderName);
    await holder.getByRole("combobox", { name: /^Type aksjonær/ }).selectOption("norwegian_company");
    await holder.getByLabel("Organisasjonsnummer (9 siffer)", { exact: true }).fill(org);
    await holder.getByLabel("Aksjer ved årets start", { exact: true }).fill(opening);
    await holder.getByLabel("Aksjer ved årets slutt", { exact: true }).fill(closing);
  }
  await page.getByRole("combobox", { name: /^Velg originaldokument/ }).selectOption(documentId);
  await page.getByRole("button", { name: "Hent dokumentopplysninger", exact: true }).click();
  await page.getByRole("button", { name: "Oppdater dokumentopplysninger", exact: true }).waitFor();
  for (const label of ["Grunnlag ved årets start", "Grunnlag ved årets slutt", "Innbetalt kapital og overkurs"])
    await page.getByRole("group", { name: label, exact: true }).getByRole("checkbox").check();
  await page.getByRole("combobox", { name: /^Ny hendelse/ }).selectOption("share_sale");
  await page.getByRole("button", { name: "Legg til hendelse", exact: true }).click();
  const event = page.getByRole("group", { name: "1. Overdragelse av aksjer", exact: true });
  await event.getByLabel("Dato og lokalt klokkeslett", { exact: true }).fill(`${incomeYear}-07-01T12:00`);
  await event.getByLabel("Antall overdratte aksjer", { exact: true }).fill("50");
  await event.getByLabel("Samlet vederlag (kr)", { exact: true }).fill("15000");
  await event.getByRole("combobox", { name: /^Selger/ }).selectOption(openingHolderId);
  await event.getByRole("combobox", { name: /^Kjøper/ }).selectOption(buyer);
  await event.getByRole("group", { name: "Dokumenter for denne hendelsen", exact: true }).getByRole("checkbox").check();
  for (const checkbox of await page.getByRole("group", { name: "Gjennomgang av hele året", exact: true }).getByRole("checkbox").all())
    await checkbox.check();
  await page.getByRole("button", { name: "Lagre årsgrunnlag", exact: true }).click();
  await page.getByRole("heading", { name: "Årsgrunnlaget er lagret", exact: true }).waitFor();
  const source = (await api.rf1086ReadCurrentYearSource(scope)).currentSource;
  assert.equal(source.draft.case.events.length, 1);
  assert.equal(source.draft.case.events[0].type, "share_sale");
  assert.equal(source.draft.case.shareholders.length, 2);
  assert.equal(source.receipt.version, 1);
  assert.equal(source.draft.documents[0].documentId, documentId);
  assert.equal(source.draft.documents[0].contentSha256, document.contentSha256);
  await page.getByRole("button", { name: "Lag forhåndsvisning av lagret grunnlag", exact: true }).click();
  const reviewButton = page.getByRole("button", { name: "Kontroller vilkår for godkjenning", exact: true });
  await reviewButton.waitFor();
  await reviewButton.click();
  const review = page.getByRole("group", { name: "Din gjennomgang", exact: true });
  await review.waitFor();
  // Preserve the existing non-RF blocking predicate after the generic table's
  // physical retirement. The owned Accounts query must still veto RF review.
  const previewId = (await api.rf1086Workspace(company.id, incomeYear, options)).previews[0].id;
  const overrideId = randomUUID();
  const overrideScope = ["annual_accounts_filing.filing_overrides"];
  await fixtureTableTransaction(database, overrideScope, () => database.query(
    `insert into annual_accounts_filing.filing_overrides
      (id,company_id,income_year,filing,field_target,old_value,new_value,reason,risk_level,created_by,owner_confirmed_by,owner_confirmed_at)
     values($1,$2,$3,'årsregnskap','synthetic-check','a','b','Synthetic blocking prerequisite','block',$4,$4,clock_timestamp())`,
    [overrideId, company.id, incomeYear, ownerId]));
  try {
    const blocked = await api.rf1086PrepareSourceProductionReview({ companyId: company.id, incomeYear, previewId, entitlementId }, options);
    assert.equal(blocked.canApprove, false);
    assert.ok(blocked.blockers.includes("other_blocking_override"));
  } finally {
    await fixtureTableTransaction(database, overrideScope, () => database.query(
      "delete from annual_accounts_filing.filing_overrides where id=$1 and company_id=$2", [overrideId, company.id]));
  }
  await reviewButton.click();
  await review.waitFor();
  await review.getByLabel("Årsavslutningsintervjuet er ikke fullført.", { exact: true }).waitFor();
  await review.getByLabel("Inntektsåret er ikke periode-låst.", { exact: true }).waitFor();
  // Missing annual interview/period lock are explicit warnings in this fixture.
  // The frozen browser-written ready row is false; approval uses current facts.
  for (const checkbox of await review.getByRole("checkbox").all()) await checkbox.check();
  await page.getByRole("button", { name: "Lagre godkjenning", exact: true }).click();
  await page.getByRole("link", { name: "Gå til innsending og status", exact: true }).click();
  const approved = await api.rf1086Workspace(company.id, incomeYear, options);
  assert.equal(approved.approvals.length, 1);
  assert.equal(approved.approvals[0].caseProfile, "rf1086_full_year_v1");
  assert.equal(approved.approvals[0].entitlementId, entitlementId);
  assert.equal(Object.keys(approved.previews[0].underskjemaXml).length, 2);
  const panel = page.getByRole("region", { name: "Innsending og status", exact: true });
  await panel.getByRole("combobox", { name: /^Lagret godkjenning/ }).locator(`option[value="${approved.approvals[0].id}"]`).waitFor({ state: "attached" });
  assert.equal(await panel.getByRole("combobox", { name: /^Lagret godkjenning/ }).inputValue(), approved.approvals[0].id);
  await panel.getByRole("button", { name: "Hent lagret status", exact: true }).click();
  await panel.getByRole("checkbox").check();
  const send = panel.getByRole("button", { name: "Send godkjent oppgave", exact: true });
  if (predecessorFeedback === "rejected") mock.rejectNextFeedback();
  await send.focus();
  await send.press("Enter");
  await panel.getByText("Innsendingen er bekreftet. Hent lagret status og tilbakemelding.", { exact: true }).waitFor();
  assert.equal(await panel.getByRole("button", { name: "Send godkjent oppgave", exact: true }).count(), 0);
  await panel.getByRole("button", { name: "Hent lagret status", exact: true }).click();
  await panel.getByRole("button", { name: "Hent tilbakemelding", exact: true }).click();
  await panel.getByText(`Tilbakemelding: ${predecessorLabel}.`, { exact: true }).waitFor();
  const processed = await api.rf1086Workspace(company.id, incomeYear, options);
  assert.equal(processed.productionSubmissions.length, 1);
  assert.equal(processed.productionSubmissions[0].feedbackState, predecessorFeedback);
  assert.equal(processed.productionSubmissions[0].status, predecessorFeedback);
  assert.equal(processed.feedbackArtifacts.length, 2);
  assert.ok(processed.feedbackArtifacts.every(row => row.classification === predecessorFeedback));
  const position = await api.rf1086ReadSourceProductionPosition(approved.approvals[0].id, options);
  assert.equal(position.disposition, "confirmed");
  assert.equal(position.submissionId, processed.productionSubmissions[0].id);
  for (const width of [320, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `full-year source overflow at ${width}`);
  }
  await page.reload();
  await panel.getByRole("button", { name: "Hent lagret status", exact: true }).click();
  assert.equal(await panel.getByRole("button", { name: "Send godkjent oppgave", exact: true }).count(), 0);
  await panel.getByRole("link", { name: `Tilbakemelding: ${predecessorLabel}`, exact: true }).first().waitFor();
  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "Last ned RF-arkiv", exact: true }).click();
  const download = await downloading;
  assert.equal(await download.failure(), null);
  const verification = JSON.parse(execFileSync(python, ["apps/backend/scripts/verify_rf1086_archive.py", await download.path(),
    "--stream", "--company-id", company.id, "--income-year", String(incomeYear), "--require-source-history", "--require-feedback-originals"],
  { cwd: process.cwd(), env: environment, encoding: "utf8", timeout: 30_000 }));
  for (const key of ["sourceVersions", "sourceApprovals", "sourceClaims", "submissions", "sourceOriginals"])
    assert.equal(verification[key], 1, key);
  assert.equal(verification.feedbackOriginals, 2);
  assert.equal(verification.feedbackOriginalsComplete, true);
  assert.equal(verification.databaseRestorePerformed, false);
  const operations = mock.snapshot().filter(({ service }) => service === "skatteetaten").slice(callsBefore);
  assert.equal(operations.filter(({ operation }) => operation === "post_hovedskjema").length, 1);
  assert.equal(operations.filter(({ operation }) => operation === "post_underskjema").length, 2);
  assert.equal(operations.filter(({ operation }) => operation === "confirm").length, 1);
  assert.equal(operations.find(({ operation }) => operation === "post_hovedskjema").digest,
    createHash("sha256").update(approved.previews[0].hovedskjemaXml).digest("hex"));
  assert.deepEqual(operations.filter(({ operation }) => operation === "post_underskjema").map(row => row.digest).sort(),
    Object.values(approved.previews[0].underskjemaXml).map(xml => createHash("sha256").update(xml).digest("hex")).sort());
  assert.equal(operations.filter(({ operation }) => ["replayed_mutation", "request_rejected"].includes(operation)).length, 0);
  for (const endpoint of ["year-sources", "source-previews", "source-production-reviews", "source-production-approvals", "source-production-filings"])
    assert.ok(apiCalls.some(call => call.endsWith(`POST:/api/v1/shareholder-register-filings/${endpoint}:200`)), `missing full-year backend operation ${endpoint}`);
  const correction = await exerciseSourceCorrection({ page, sourceHref, company, incomeYear, api, scope, options, storage,
    mock, python, environment, source, approved, processed, documentId, predecessorLabel });
  return await exerciseUnknownSourceOutcome({ page, sourceHref, company, incomeYear, api, scope, options, storage,
    mock, python, environment, documentId, correction, lostResponse, crashBackend, armPreparedCrash,
    includeUnapprovedHistory: predecessorFeedback === "rejected" });
}

async function uploadOriginal({ api, options, storage, company, incomeYear, consideration }) {
  const content = syntheticPdf(consideration);
  const documentId = randomUUID();
  const name = `Synthetic full-year share transfer ${consideration}.pdf`;
  const transfer = await api.documentsBeginUpload({ documentId, companyId: company.id, incomeYear,
    fileName: name, contentType: "application/pdf", byteLength: content.length,
    headerBase64: content.subarray(0, 5).toString("base64"), documentType: "corporate_document",
    finalStatus: "attached", linkedTo: "aksjonaerregisteroppgaven" },
  { ...options, idempotencyKey: randomUUID() });
  assert.ok(isLoopbackSupabaseUrl(new URL(transfer.signedUrl).origin));
  assert.ifError((await storage.from(transfer.bucket).uploadToSignedUrl(transfer.storageKey,
    transfer.token, content, { contentType: "application/pdf" })).error);
  const document = await api.documentsFinalizeUpload(documentId, { ...options, idempotencyKey: randomUUID() });
  assert.equal(document.contentSha256, createHash("sha256").update(content).digest("hex"));
  return { documentId, document, name };
}

async function approveSourceCorrection({ page, sourceHref, company, incomeYear, api, scope, options, storage,
  source, prior, documentId, consideration, previousConsideration }) {
  const before = await api.rf1086Workspace(company.id, incomeYear, options);
  const corrected = await uploadOriginal({ api, options, storage, company, incomeYear, consideration });
  await page.goto(sourceHref);
  await page.getByRole("heading", { name: "Gjeldende årsgrunnlag", exact: true }).waitFor();
  await page.getByRole("combobox", { name: /^Velg originaldokument/ }).selectOption(corrected.documentId);
  await page.getByRole("button", { name: "Hent dokumentopplysninger", exact: true }).click();
  const event = page.getByRole("group", { name: "1. Overdragelse av aksjer", exact: true });
  const documents = event.getByRole("group", { name: "Dokumenter for denne hendelsen", exact: true });
  await documents.getByRole("checkbox", { name: `${corrected.name} · ${incomeYear}`, exact: true }).check();
  await documents.getByRole("checkbox", { name: `Synthetic full-year share transfer ${previousConsideration}.pdf · ${incomeYear}`, exact: true }).uncheck();
  await event.getByLabel("Samlet vederlag (kr)", { exact: true }).fill(consideration);
  await page.getByLabel("Hvorfor korrigeres det tidligere årsgrunnlaget?", { exact: true }).fill(`Originaldokumentet viser korrigert vederlag på ${consideration} kroner.`);
  for (const checkbox of await page.getByRole("group", { name: "Gjennomgang av hele året", exact: true }).getByRole("checkbox").all())
    await checkbox.check();
  await page.getByRole("button", { name: "Lagre korrigert årsgrunnlag", exact: true }).click();
  await page.getByRole("heading", { name: "Årsgrunnlaget er lagret", exact: true }).waitFor();
  const current = (await api.rf1086ReadCurrentYearSource(scope)).currentSource;
  assert.equal(current.receipt.version, source.receipt.version + 1);
  assert.notEqual(current.receipt.sourceId, source.receipt.sourceId);
  // The read API returns a draft for the next correction, anchored to this
  // newly saved version. The archive verifier checks the persisted ancestry.
  assert.equal(current.draft.supersedesSourceId, current.receipt.sourceId);
  assert.equal(current.draft.supersedesSourceSha256, current.receipt.sourceSha256);
  assert.equal(current.draft.documents.find(row => row.documentId === corrected.documentId).contentSha256, corrected.document.contentSha256);
  assert.ok(current.draft.documents.some(row => row.documentId === documentId), "opening original retained in the corrected source");
  await page.getByRole("button", { name: "Lag forhåndsvisning av lagret grunnlag", exact: true }).click();
  await page.getByRole("button", { name: "Kontroller vilkår for godkjenning", exact: true }).click();
  const review = page.getByRole("group", { name: "Din gjennomgang", exact: true });
  await review.waitFor();
  await review.getByRole("combobox", { name: "Oppgaven som skal erstattes", exact: true }).selectOption(prior.id);
  await review.getByLabel("Hvorfor skal oppgaven korrigeres?", { exact: true }).fill("Korrigert vederlag med nytt originaldokument.");
  for (const checkbox of await review.getByRole("checkbox").all()) await checkbox.check();
  await page.getByRole("button", { name: "Lagre godkjenning", exact: true }).click();
  await page.getByRole("link", { name: "Gå til innsending og status", exact: true }).click();
  const workspace = await api.rf1086Workspace(company.id, incomeYear, options);
  assert.equal(workspace.approvals.length, before.approvals.length + 1);
  const nextApproval = workspace.approvals.find(row => !before.approvals.some(previous => previous.id === row.id));
  const nextPreview = workspace.previews.find(row => row.id === nextApproval.previewId);
  assert.ok(nextPreview);
  assert.notEqual(nextApproval.payloadHash, before.approvals.find(row => row.id === prior.approvalId).payloadHash);
  const panel = page.getByRole("region", { name: "Innsending og status", exact: true });
  await panel.getByRole("combobox", { name: /^Lagret godkjenning/ }).locator(`option[value="${nextApproval.id}"]`).waitFor({ state: "attached" });
  assert.equal(await panel.getByRole("combobox", { name: /^Lagret godkjenning/ }).inputValue(), nextApproval.id);
  return { current, nextApproval, nextPreview, panel };
}

async function exerciseSourceCorrection({ page, sourceHref, company, incomeYear, api, scope, options, storage,
  mock, python, environment, source, approved, processed, documentId, predecessorLabel }) {
  const prior = processed.productionSubmissions[0];
  const historyBefore = await api.rf1086GetProductionArchiveSource(company.id, incomeYear, options);
  const callsBefore = mock.snapshot().filter(({ service }) => service === "skatteetaten").length;
  const { current, nextApproval, nextPreview, panel } = await approveSourceCorrection({ page, sourceHref,
    company, incomeYear, api, scope, options, storage, source, prior, documentId,
    consideration: "18000", previousConsideration: "15000" });
  await panel.getByRole("button", { name: "Hent lagret status", exact: true }).click();
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: "Send godkjent oppgave", exact: true }).click();
  await panel.getByText("Innsendingen er bekreftet. Hent lagret status og tilbakemelding.", { exact: true }).waitFor();
  await panel.getByRole("button", { name: "Hent lagret status", exact: true }).click();
  await panel.getByRole("button", { name: "Hent tilbakemelding", exact: true }).click();
  await panel.getByText("Tilbakemelding: Godkjent.", { exact: true }).waitFor();
  const after = await api.rf1086Workspace(company.id, incomeYear, options);
  assert.equal(after.productionSubmissions.length, 2);
  assert.equal(after.feedbackArtifacts.length, 4);
  assert.deepEqual(after.approvals.find(row => row.id === approved.approvals[0].id), approved.approvals[0]);
  assert.deepEqual(after.previews.find(row => row.id === approved.previews[0].id), approved.previews[0]);
  const replacement = after.productionSubmissions.find(row => row.id !== prior.id);
  assert.equal(replacement.feedbackState, "accepted");
  assert.equal(replacement.supersedesSubmissionId, prior.id);
  assert.deepEqual(after.productionSubmissions.find(row => row.id === prior.id), prior);
  assert.deepEqual(after.feedbackArtifacts.filter(row => row.submissionId === prior.id), processed.feedbackArtifacts);
  const historyAfter = await api.rf1086GetProductionArchiveSource(company.id, incomeYear, options);
  assert.deepEqual(historyAfter.productionEvents.filter(row => row.submissionId === prior.id),
    historyBefore.productionEvents.filter(row => row.submissionId === prior.id));
  await page.reload();
  await panel.getByRole("combobox", { name: /^Lagret godkjenning/ }).selectOption(approved.approvals[0].id);
  await panel.getByRole("button", { name: "Hent lagret status", exact: true }).click();
  await panel.getByText(`Innsendingen er bekreftet mottatt. Se tilbakemeldingen for Skatteetatens behandling. Status: ${predecessorLabel}.`, { exact: true }).waitFor();
  assert.equal(await panel.getByRole("button", { name: /^(Send godkjent oppgave|Fortsett samme innsending)$/ }).count(), 0);
  const priorPosition = await api.rf1086ReadSourceProductionPosition(approved.approvals[0].id, options);
  assert.equal(priorPosition.submissionId, prior.id);
  assert.equal(priorPosition.feedbackState, prior.feedbackState);
  await panel.getByRole("link", { name: `Tilbakemelding: ${predecessorLabel}`, exact: true }).first().waitFor();
  await panel.getByRole("combobox", { name: /^Lagret godkjenning/ }).selectOption(nextApproval.id);
  await panel.getByRole("button", { name: "Hent lagret status", exact: true }).click();
  assert.equal((await api.rf1086ReadSourceProductionPosition(nextApproval.id, options)).submissionId, replacement.id);
  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "Last ned RF-arkiv", exact: true }).click();
  const download = await downloading;
  assert.equal(await download.failure(), null);
  const verification = JSON.parse(execFileSync(python, ["apps/backend/scripts/verify_rf1086_archive.py", await download.path(),
    "--stream", "--company-id", company.id, "--income-year", String(incomeYear), "--require-source-history", "--require-feedback-originals"],
  { cwd: process.cwd(), env: environment, encoding: "utf8", timeout: 30_000 }));
  for (const key of ["sourceVersions", "sourceApprovals", "sourceClaims", "submissions", "sourceOriginals"])
    assert.equal(verification[key], 2, key);
  assert.equal(verification.feedbackOriginals, 4);
  assert.equal(verification.feedbackOriginalsComplete, true);
  assert.equal(verification.databaseRestorePerformed, false);
  const operations = mock.snapshot().filter(({ service }) => service === "skatteetaten").slice(callsBefore);
  assert.equal(operations.filter(({ operation }) => operation === "post_hovedskjema").length, 1);
  assert.equal(operations.filter(({ operation }) => operation === "post_underskjema").length, 2);
  assert.equal(operations.filter(({ operation }) => operation === "confirm").length, 1);
  assert.equal(operations.find(({ operation }) => operation === "post_hovedskjema").digest,
    createHash("sha256").update(nextPreview.hovedskjemaXml).digest("hex"));
  assert.deepEqual(operations.filter(({ operation }) => operation === "post_underskjema").map(row => row.digest).sort(),
    Object.values(nextPreview.underskjemaXml).map(xml => createHash("sha256").update(xml).digest("hex")).sort());
  assert.equal(operations.filter(({ operation }) => ["replayed_mutation", "request_rejected"].includes(operation)).length, 0);
  return { source: current, approval: nextApproval, submission: replacement };
}

async function exerciseUnknownSourceOutcome({ page, sourceHref, company, incomeYear, api, scope, options, storage,
  mock, python, environment, documentId, correction, lostResponse, crashBackend, armPreparedCrash, includeUnapprovedHistory }) {
  const { nextApproval, nextPreview, panel } = await approveSourceCorrection({ page, sourceHref,
    company, incomeYear, api, scope, options, storage, source: correction.source, prior: correction.submission,
    documentId, consideration: "19000", previousConsideration: "18000" });
  const position = await api.rf1086ReadSourceProductionPosition(nextApproval.id, options);
  assert.equal(position.disposition, "unclaimed");
  assert.equal(position.expectedHead, correction.submission.id);
  const command = { approvalId: nextApproval.id, manifestSha256: position.manifestSha256, expectedHead: position.expectedHead };
  const callsBefore = mock.snapshot().filter(row => row.service === "skatteetaten").length;
  const fail = { main: "failNextMainResponse", child: "failNextChildResponse", confirmation: "failNextConfirmationResponse" }[lostResponse];
  assert.ok(fail);
  const operation = { main: "post_hovedskjema", child: "post_underskjema", confirmation: "confirm" }[lostResponse];
  const held = armPreparedCrash ? armPreparedCrash(operation) : crashBackend ? mock.holdNextResponse(operation) : undefined;
  let beforeCrashArchive, callsAtCrash;
  if (!crashBackend) mock[fail]();
  await panel.getByRole("button", { name: "Hent lagret status", exact: true }).click();
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: "Send godkjent oppgave", exact: true }).click();
  if (crashBackend) {
    let timer;
    try {
      await Promise.race([held, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("mock_mutation_hold_deadline_exceeded")), 10_000);
      })]);
    } finally { clearTimeout(timer); }
    const atCrash = await api.rf1086GetProductionArchiveSource(company.id, incomeYear, options);
    const active = atCrash.productionSubmissions.find(row => row.approvalId === nextApproval.id);
    const lastMutation = mock.snapshot().filter(row => row.service === "skatteetaten").at(-1);
    const intent = atCrash.productionEvents.filter(row => row.submissionId === active.id && (armPreparedCrash
      ? row.operationName.split(":")[0] === operation && row.operationState === "prepared"
        && !atCrash.productionEvents.some(outcome => outcome.idempotencyKey === row.idempotencyKey && outcome.operationState !== "prepared")
      : row.idempotencyKey === lastMutation.key));
    assert.equal(intent.length, 1, "selected operation must have exactly one already committed intent");
    assert.equal(intent[0].operationState, "prepared");
    assert.equal(active.status, "sending");
    beforeCrashArchive = atCrash;
    callsAtCrash = mock.snapshot();
    await crashBackend();
    await page.reload();
  } else {
    await panel.getByText("Innsendingsutfallet er ukjent. Kontroller lagret status og avklar utfallet før du gjør noe mer.", { exact: true }).waitFor();
  }
  await panel.getByRole("button", { name: "Hent lagret status", exact: true }).click();
  const unknownText = "En operasjon har ukjent utfall. Utfallet må avklares før innsendingen kan fortsette.";
  await panel.getByText(unknownText, { exact: true }).waitFor();
  assert.equal(await panel.getByRole("button", { name: /^(Send godkjent oppgave|Fortsett samme innsending|Hent tilbakemelding)$/ }).count(), 0);
  for (const width of [320, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `unknown-outcome overflow at ${width}`);
  }
  const retained = await api.rf1086GetProductionArchiveSource(company.id, incomeYear, options);
  if (crashBackend) {
    assert.deepEqual(mock.snapshot(), callsAtCrash, "restart and initial reads must not acquire tokens or call providers");
    for (const field of ["productionSubmissions", "productionEvents", "sourceSubmissionClaims", "submissionHead", "feedbackArtifacts"])
      assert.deepEqual(retained[field], beforeCrashArchive[field], `restart changed ${field}`);
  }
  const unknown = retained.productionSubmissions.find(row => row.approvalId === nextApproval.id);
  assert.equal(retained.productionSubmissions.length, 3);
  assert.equal(unknown.status, crashBackend ? "sending" : "unknown");
  assert.equal(unknown.supersedesSubmissionId, correction.submission.id);
  assert.equal(retained.submissionHead.submissionId, unknown.id);
  assert.equal(retained.sourceSubmissionClaims.length, 3);
  assert.equal(retained.sourceSubmissionClaims.filter(row => row.approvalId === nextApproval.id).length, 1);
  const journal = retained.productionEvents.filter(row => row.submissionId === unknown.id);
  const mutations = mock.snapshot().filter(row => row.service === "skatteetaten").slice(callsBefore);
  const intendedOperations = { main: ["post_hovedskjema"], child: ["post_hovedskjema", "post_underskjema"],
    confirmation: ["post_hovedskjema", "post_underskjema", "post_underskjema", "confirm"] }[lostResponse];
  const expectedOperations = armPreparedCrash ? intendedOperations.slice(0, -1) : intendedOperations;
  assert.deepEqual(mutations.map(row => row.operation), expectedOperations);
  if (mutations.length) assert.equal(mutations[0].digest, createHash("sha256").update(nextPreview.hovedskjemaXml).digest("hex"));
  assert.equal(journal.length, mutations.length * 2 + (armPreparedCrash ? 1 : crashBackend ? -1 : 0));
  const succeeded = journal.filter(row => row.operationState === "succeeded");
  const uncertain = journal.filter(row => row.operationState === "unknown");
  assert.equal(succeeded.length, mutations.length - (armPreparedCrash ? 0 : 1));
  assert.equal(uncertain.length, crashBackend ? 0 : 1);
  if (!crashBackend) {
    assert.equal(uncertain[0].failureClass, "unknown");
    assert.equal(uncertain[0].authorityReference, null);
  }
  const knownReferences = {};
  const childHashes = Object.values(nextPreview.underskjemaXml).map(xml => createHash("sha256").update(xml).digest("hex"));
  if (armPreparedCrash) {
    const incomplete = journal.filter(event => event.operationState === "prepared"
      && !journal.some(outcome => outcome.idempotencyKey === event.idempotencyKey && outcome.operationState !== "prepared"));
    assert.equal(incomplete.length, 1);
    const pending = incomplete[0];
    assert.equal(pending.operationName.split(":")[0], operation);
    assert.equal(pending.attempt, 1);
    assert.equal(pending.authorityReference, null);
    assert.equal(pending.failureClass, null);
    assert.equal(pending.resultingStatus, "sending");
    assert.match(pending.idempotencyKey, /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/u);
    const expectedHash = lostResponse === "main" ? createHash("sha256").update(nextPreview.hovedskjemaXml).digest("hex")
      : lostResponse === "confirmation" ? createHash("sha256").update(`${mutations[0].id}:2`).digest("hex") : undefined;
    if (expectedHash) assert.equal(pending.bodyHash, expectedHash);
    else assert.ok(childHashes.includes(pending.bodyHash));
    assert.equal(mutations.some(mutation => mutation.key === pending.idempotencyKey), false);
  }
  if (lostResponse === "confirmation")
    assert.deepEqual(mutations.filter(row => row.operation === "post_underskjema").map(row => row.digest).sort(), childHashes.sort());
  for (const [index, mutation] of mutations.entries()) {
    const events = journal.filter(row => row.idempotencyKey === mutation.key);
    const incomplete = crashBackend && !armPreparedCrash && index === mutations.length - 1;
    assert.equal(events.length, incomplete ? 1 : 2);
    assert.deepEqual(events.map(row => row.operationState).sort(), incomplete ? ["prepared"]
      : ["prepared", !armPreparedCrash && index === mutations.length - 1 ? "unknown" : "succeeded"].sort());
    const bodyHash = mutation.operation === "confirm"
      ? createHash("sha256").update(`${mutations[0].id}:2`).digest("hex") : mutation.digest;
    for (const event of events) {
      assert.equal(event.attempt, 1);
      assert.equal(event.bodyHash, bodyHash);
      if (mutation.operation === "post_underskjema") {
        assert.ok(event.operationName.startsWith("post_underskjema:"));
        assert.ok(childHashes.includes(mutation.digest));
      } else assert.equal(event.operationName, mutation.operation);
    }
    if (!incomplete) assert.equal(events[0].operationName, events[1].operationName);
    const completed = events.find(row => row.operationState === "succeeded");
    if (completed) {
      const reference = mutation.operation === "post_hovedskjema" ? mutations[0].id : "posted";
      assert.equal(completed.authorityReference, reference);
      knownReferences[completed.operationName] = reference;
    }
  }
  assert.deepEqual(unknown.authorityReferences, knownReferences, "retain only references from received successful responses");
  assert.equal(Object.hasOwn(unknown.authorityReferences, "confirm"), false);
  const callsAfterLoss = mock.snapshot();
  for (let attempt = 0; attempt < 2; attempt++) {
    await assert.rejects(api.rf1086SendSourceProduction(command, options), error =>
      error.status === 409 && error.problem?.code === "rf1086_unknown_production_outcome");
    await page.reload();
    await panel.getByRole("button", { name: "Hent lagret status", exact: true }).click();
    await panel.getByText(unknownText, { exact: true }).waitFor();
    assert.equal(await panel.getByRole("button", { name: /^(Send godkjent oppgave|Fortsett samme innsending|Hent tilbakemelding)$/ }).count(), 0);
    const current = await api.rf1086ReadSourceProductionPosition(nextApproval.id, options);
    assert.equal(current.disposition, "recovery_required");
    assert.equal(current.submissionId, unknown.id);
    assert.equal(current.manifestSha256, position.manifestSha256);
  }
  assert.deepEqual(mock.snapshot(), callsAfterLoss, "retries and status reads must not acquire provider tokens or resend");
  const after = await api.rf1086GetProductionArchiveSource(company.id, incomeYear, options);
  for (const field of ["productionSubmissions", "productionEvents", "sourceSubmissionClaims", "submissionHead", "feedbackArtifacts"])
    assert.deepEqual(after[field], retained[field], field);
  assert.equal(after.feedbackArtifacts.some(row => row.submissionId === unknown.id), false);
  if (includeUnapprovedHistory) {
    await exerciseUnapprovedPriorYearSource({ page, sourceHref, company, incomeYear, api, scope, options, storage });
    const withDraft = await api.rf1086GetProductionArchiveSource(company.id, incomeYear, options);
    for (const field of ["approvals", "sourceApprovalLineage", "productionSubmissions", "productionEvents", "sourceSubmissionClaims", "submissionHead", "feedbackArtifacts"])
      assert.deepEqual(withDraft[field], after[field], `unapproved source changed ${field}`);
    assert.deepEqual(mock.snapshot(), callsAfterLoss, "saving an unapproved source must not call a provider");
  }
  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "Last ned RF-arkiv", exact: true }).click();
  const download = await downloading;
  assert.equal(await download.failure(), null);
  const verification = JSON.parse(execFileSync(python, ["apps/backend/scripts/verify_rf1086_archive.py", await download.path(),
    "--stream", "--company-id", company.id, "--income-year", String(incomeYear), "--require-source-history", "--require-feedback-originals"],
  { cwd: process.cwd(), env: environment, encoding: "utf8", timeout: 30_000 }));
  for (const key of ["sourceApprovals", "sourceClaims", "submissions"])
    assert.equal(verification[key], 3, key);
  for (const key of ["sourceVersions", "sourceOriginals"])
    assert.equal(verification[key], includeUnapprovedHistory ? 4 : 3, key);
  assert.equal(verification.feedbackOriginals, 4, "an unknown send must not invent feedback");
  assert.equal(verification.databaseRestorePerformed, false);
  return { path: await download.path(), verification };
}

async function exerciseUnapprovedPriorYearSource({ page, sourceHref, company, incomeYear, api, scope, options, storage }) {
  const before = await api.rf1086Workspace(company.id, incomeYear, options);
  const history = archive => JSON.parse(JSON.parse(archive.canonicalArchive).snapshotText).fields.source_history.fields;
  const historyBefore = history(await api.rf1086GetProductionArchiveSource(company.id, incomeYear, options));
  const originalSource = (await api.rf1086ReadCurrentYearSource(scope)).currentSource;
  const priorYear = incomeYear - 1;
  const original = await uploadOriginal({ api, options, storage, company, incomeYear: priorYear, consideration: "20000" });
  assert.equal(original.document.incomeYear, priorYear);
  await page.goto(sourceHref);
  await page.getByRole("heading", { name: "Gjeldende årsgrunnlag", exact: true }).waitFor();
  await page.getByRole("combobox", { name: /^Velg originaldokument/ }).selectOption(original.documentId);
  await page.getByRole("button", { name: "Hent dokumentopplysninger", exact: true }).click();
  // Prior-year evidence can support this year's opening basis. It is not an
  // invented current-year transfer and must retain its actual document year.
  const opening = page.getByRole("group", { name: "Grunnlag ved årets start", exact: true });
  await opening.getByRole("checkbox", { name: `${original.name} · ${priorYear}`, exact: true }).check();
  await page.getByLabel("Hvorfor korrigeres det tidligere årsgrunnlaget?", { exact: true }).fill("Tilleggsdokument fra tidligere år for inngående grunnlag; ikke godkjent for innsending.");
  for (const checkbox of await page.getByRole("group", { name: "Gjennomgang av hele året", exact: true }).getByRole("checkbox").all())
    await checkbox.check();
  await page.getByRole("button", { name: "Lagre korrigert årsgrunnlag", exact: true }).click();
  await page.getByRole("heading", { name: "Årsgrunnlaget er lagret", exact: true }).waitFor();
  const current = (await api.rf1086ReadCurrentYearSource(scope)).currentSource;
  assert.equal(current.receipt.version, originalSource.receipt.version + 1);
  const captured = current.draft.documents.find(row => row.documentId === original.documentId);
  assert.equal(captured.sourceIncomeYear, priorYear);
  assert.equal(captured.contentSha256, original.document.contentSha256);
  await page.getByRole("button", { name: "Lag forhåndsvisning av lagret grunnlag", exact: true }).click();
  await page.getByRole("button", { name: "Kontroller vilkår for godkjenning", exact: true }).waitFor();
  const after = await api.rf1086Workspace(company.id, incomeYear, options);
  // Workspace previews are materialized by review preparation. An unreviewed
  // preview belongs only to the complete source history in the canonical archive.
  assert.deepEqual(after.previews, before.previews);
  const historyAfter = history(await api.rf1086GetProductionArchiveSource(company.id, incomeYear, options));
  for (const field of ["year_sources", "source_previews"]) {
    assert.equal(historyAfter[field].length, historyBefore[field].length + 1, field);
    for (const record of historyBefore[field])
      assert.ok(historyAfter[field].some(row => JSON.stringify(row) === JSON.stringify(record)), `existing ${field} record is immutable`);
  }
  assert.deepEqual(after.approvals, before.approvals, "the saved draft has no approval");
  assert.deepEqual(after.productionSubmissions, before.productionSubmissions);
}

function syntheticPdf(consideration) {
  const stream = `BT /F1 12 Tf 20 100 Td (Synthetic share transfer: 50 of 100 shares, NOK ${consideration}.) Tj ET`;
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 500 200] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"];
  let pdf = "%PDF-1.7\n";
  const offsets = [0];
  for (const [i, body] of objects.entries()) { offsets.push(pdf.length); pdf += `${i + 1} 0 obj\n${body}\nendobj\n`; }
  const xref = pdf.length;
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(n => `${String(n).padStart(10, "0")} 00000 n \n`).join("")}`;
  return Buffer.from(`${pdf}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
}

// An admitted company/year is a prerequisite, not an RF result. Read the current
// manifest/legal constants so this synthetic seed cannot silently use old terms.
export async function seedFullYearAdmission(database, company, ownerId, python, environment) {
  const facts = JSON.parse(execFileSync(python, ["-c", `import json
from talli_backend.modules.company_access import public as a
legal = {p + "_" + s: str(getattr(a, "CURRENT_" + (p + "_" + s).upper()))
    for p in ("business_terms", "dpa", "privacy_notice") for s in ("version", "effective_date", "path", "sha256")}
promise = {"accountingYear": a.CAPABILITY_MANIFEST["accountingYear"],
    "startsOn": a.CAPABILITY_MANIFEST["promise"]["startsOn"], "endsOn": a.CAPABILITY_MANIFEST["promise"]["endsOn"],
    "reconstructionRequiredFrom": a.CAPABILITY_MANIFEST["promise"]["startsOn"],
    "onlyAccountingAndFilingProduct": True, "customerClaims": a.CAPABILITY_MANIFEST["promise"]["customerClaims"]}
print(json.dumps({"manifest": a.CAPABILITY_MANIFEST, "version": a.CURRENT_CAPABILITY_MANIFEST_VERSION,
    "hash": a.CURRENT_CAPABILITY_MANIFEST_SHA256, "legal": legal, "promise": promise, "promiseHash": a._canonical_sha256(promise)}))`],
    { cwd: process.cwd(), env: environment, encoding: "utf8", timeout: 10_000 }));
  const incomeYear = facts.manifest.accountingYear;
  const now = (await database.query("select clock_timestamp() now")).rows[0].now;
  const assessment = randomUUID(), admission = randomUUID();
  const common = { company_id: company.id, accounting_year: incomeYear,
    capability_manifest: facts.manifest, capability_manifest_version: facts.version, capability_manifest_sha256: facts.hash };
  const rows = [
    ["public.company_eligibility_assessments", { ...common, id: assessment, operation_id: randomUUID(),
      trigger: "initial_admission", decision: "supported", public_facts: { source: "synthetic-browser-fixture" },
      public_facts_sha256: "a".repeat(64), answers: { fixture: true }, answers_sha256: "b".repeat(64),
      consequential_operations_allowed: true, archive_export_available: true, evaluator_version: facts.version,
      assessed_by: ownerId, assessed_at: now, next_step_code: "CONTINUE_COMPANY_YEAR", next_step: "Synthetic browser prerequisite." }],
    ["public.company_year_admissions", { ...common, id: admission, eligibility_assessment_id: assessment,
      company_year_promise: facts.promise, company_year_promise_sha256: facts.promiseHash,
      reconstruct_from: facts.promise.startsOn, admitted_by: ownerId, admitted_at: now }],
    ["public.company_year_acceptances", { ...facts.legal, id: randomUUID(), company_year_admission_id: admission,
      company_id: company.id, accounting_year: incomeYear, accepted_by: ownerId, accepted_at: now, customer_legal_name: company.name,
      customer_org_number: company.organizationNumber, capability_manifest_version: facts.version,
      capability_manifest_sha256: facts.hash, authority_statement_version: "authority-v1", acceptance_method: "in_app_clickwrap" }],
  ];
  await fixtureTableTransaction(database, rows.map(([table]) => table), async () => {
    for (const [table, values] of rows) await database.query(
      `insert into ${table} (${Object.keys(values).join(",")}) values (${Object.keys(values).map((_, i) => `$${i + 1}`).join(",")})`,
      Object.values(values));
  });
  return incomeYear;
}
