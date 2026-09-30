import assert from "node:assert/strict";
import test from "node:test";
import {
  afterCaptureFailure, amount, count, editSource, newEvent, resetReview, sourceCommand, shareFields,
} from "../app/(owner)/filing/aksjonaerregisteroppgaven/source/model.ts";

const companyId = "10000000-0000-4000-8000-000000000001";
const sourceId = "20000000-0000-4000-8000-000000000001";
const hash = "a".repeat(64);
const exactMoney = "9007199254740993.000001";
const civilTime = "2025-03-30T02:30:00";
const reviews = ["identitiesReviewed", "completeYearConfirmed", "paidInReviewed", "noActivityConfirmed"];
const basis = () => ({ companyId, incomeYear: 2025, company: {
  orgNumber: "999999999", name: "Synthetic Holding AS", address: "Eksempelveien 1", postalCode: "0150", city: "Oslo",
  identityConfirmedAt: "2025-01-01T12:00:00Z", identityLockedAt: "2025-01-01T12:00:00Z",
}, enumerationComplete: true, enumerationSha256: hash, dividends: [], capitalEvents: [], ledgerAmendments: [], blockers: [] });
const document = (id, sourceIncomeYear = 2024) => ({ documentId: id, companyId,
  contentVersionSha256: hash, contentSha256: hash, metadataSha256: hash, byteLength: 20,
  createdAt: "2024-12-31T12:00:00Z", sourceIncomeYear, documentType: "corporate_document", integrityStatus: "attached" });
const events = () => [
  { type: "formation", timestamp: civilTime, issuedShareCount: 100, nominalValue: "300.000001", premium: "10.000001",
    shareCountAfter: 100, allocations: [{ shareholderId: "owner-person", shareCount: 100, acquisitionValue: exactMoney }] },
  { type: "cash_issue", timestamp: "2025-04-01T13:14:15", issuedShareCount: 50, nominalValue: "300", premium: "2.125000",
    shareCountAfter: 150, registrationConfirmed: true,
    allocations: [{ shareholderId: "owner-company", shareCount: 50, acquisitionValue: "15106.250000" }] },
  { type: "cash_nominal_increase", timestamp: "2025-05-01T15:00:00", capitalIncrease: "15000.000001",
    nominalValueIncrease: "100", nominalValueAfter: "400", premium: "50.000001", registrationConfirmed: false,
    allocations: [{ shareholderId: "owner-person", shareCountBasis: 100, capitalIncrease: "10000.000001", premium: "30.000001" },
      { shareholderId: "owner-company", shareCountBasis: 50, capitalIncrease: "5000", premium: "20" }] },
  { type: "loss_covering_reduction", timestamp: "2025-06-01T10:00:00", capitalReduction: "15000",
    nominalValueReduction: "100", nominalValueAfter: "300", fundIssuedCapitalBefore: 0, registrationConfirmed: true },
  { type: "share_sale", timestamp: "2025-07-01T11:12:13", sellerShareholderId: "owner-person", buyerShareholderId: "owner-company",
    shareCount: 20, consideration: exactMoney },
  { type: "dividend", timestamp: "2025-10-26T02:30:00", totalAmount: exactMoney, perShareAmount: "17.123456",
    allocations: [{ shareholderId: "owner-person", amount: "10.000001", shareCountBasis: 80 },
      { shareholderId: "owner-company", amount: "20.123456", shareCountBasis: 70 }] },
];
function currentSource(sourceEvents = events()) {
  const { identityConfirmedAt, identityLockedAt, ...company } = basis().company;
  return { companyId, incomeYear: 2025,
    case: { caseId: "retained-owner-year", company: { ...company, incomeYear: 2025, shareType: "01", contactEmail: null },
      shareSnapshot: { previousShareCapital: "30000", currentShareCapital: "45000", previousNominalValue: "300", currentNominalValue: "300",
        previousShareCount: 100, currentShareCount: 150, previousPaidInShareCapital: "30000.000001", currentPaidInShareCapital: "45000.000001",
        previousPaidInPremium: "0.000001", currentPaidInPremium: exactMoney },
      shareholders: [{ id: "owner-person", name: "Synthetic Owner", kind: "norwegian_person", nationalId: "12345678901", orgNumber: null },
        { id: "owner-company", name: "Synthetic Parent AS", kind: "norwegian_company", nationalId: null, orgNumber: "999999999" }],
      shareholderSnapshots: [{ shareholderId: "owner-company", previousShareCount: 0, currentShareCount: 70 },
        { shareholderId: "owner-person", previousShareCount: 100, currentShareCount: 80 }], events: sourceEvents },
    paidIn: { openingCapital: "30000.000001", closingCapital: "45000.000001", openingPremium: "0.000001", closingPremium: exactMoney },
    documents: [document("opening"), document("closing", 2025), document("paid-in"), ...sourceEvents.map((_, i) => document(`event-${i}`, 2025))],
    openingDocumentIds: ["opening"], closingDocumentIds: ["closing"], paidInDocumentIds: ["paid-in"],
    eventEvidence: sourceEvents.map((_, eventIndex) => ({ eventIndex, eventSha256: `${eventIndex}`.repeat(64),
      documentIds: [`event-${eventIndex}`], governanceReceiptId: `governance-${eventIndex}` })),
    identitiesReviewed: true, completeYearConfirmed: true, paidInReviewed: true, noActivityConfirmed: true,
    supersedesSourceId: sourceId, supersedesSourceSha256: hash, correctionReason: "Old correction justification" };
}
const edit = (current = currentSource()) => editSource(basis(), current, "new-case-id");

for (const [input, expected] of [[exactMoney, exactMoney], ["9007199254740993,000001", exactMoney], ["  42,010000  ", "42.010000"], ["0", "0"]]) {
  test(`money ${input.trim()} preserves exact decimal digits without Number conversion`, () => {
    assert.equal(amount(input, "Kroner"), expected);
  });
}
for (const input of [undefined, "", " ", "1.0000001", "1,2,3", "1e6", "1 000", "-1", "+1", "Infinity"]) {
  test(`money rejects ${String(input)} without rounding or guessing`, () => assert.throws(() => amount(input, "Kroner")));
}
for (const input of [undefined, "", " ", "1.0", "-1", "+1", "1e2", "9007199254740992", "NaN"]) {
  test(`share count rejects ${String(input)}`, () => assert.throws(() => count(input, "Antall")));
}
test("explicit zero and largest safe share count remain valid", () => {
  assert.equal(count("0", "Antall"), 0);
  assert.equal(count("9007199254740991", "Antall"), Number.MAX_SAFE_INTEGER);
});

test("new intake starts from scoped company identity with no invented financial facts or reviews", () => {
  const draft = editSource(basis(), null, "new-case-id");
  assert.equal(draft.companyId, companyId);
  assert.equal(draft.incomeYear, 2025);
  assert.equal(draft.company.orgNumber, basis().company.orgNumber);
  assert.equal(draft.caseId, "new-case-id");
  assert.deepEqual(draft.shares, {});
  assert.deepEqual(draft.holders, []);
  assert.deepEqual(draft.events, []);
  assert.equal(draft.supersedesSourceId, null);
  assert.equal(draft.supersedesSourceSha256, null);
  for (const field of reviews) assert.equal(draft[field], false);
  assert.throws(() => sourceCommand(draft), /Aksjekapital/);
});

test("editing keeps current correction predecessor, joins holders by identity, and preserves document roles", () => {
  const current = currentSource();
  const original = structuredClone(current);
  const draft = edit(current);
  assert.equal(draft.caseId, current.case.caseId);
  assert.equal(draft.supersedesSourceId, sourceId);
  assert.equal(draft.supersedesSourceSha256, hash);
  assert.equal(draft.correctionReason, "");
  for (const field of reviews) assert.equal(draft[field], false);
  assert.deepEqual(draft.holders.map(h => [h.id, h.previousShareCount, h.currentShareCount]), [
    ["owner-person", "100", "80"], ["owner-company", "0", "70"],
  ]);
  draft.correctionReason = "Reviewed changed original";
  const command = sourceCommand(draft);
  assert.equal(command.correctionReason, draft.correctionReason);
  assert.deepEqual(command.openingDocumentIds, ["opening"]);
  assert.deepEqual(command.closingDocumentIds, ["closing"]);
  assert.deepEqual(command.paidInDocumentIds, ["paid-in"]);
  assert.equal(command.documents[0].sourceIncomeYear, 2024);
  assert.equal(command.documents[0].metadataSha256, hash);
  draft.documents[0].metadataSha256 = "b".repeat(64);
  draft.openingDocumentIds.push("additional");
  draft.events[0].documentIds.push("additional-event-proof");
  draft.events[0].allocations[0].values.acquisitionValue = "7";
  assert.deepEqual(current, original, "editor changes must not mutate the retained draft");
});

for (const event of events()) {
  test(`${event.type} roundtrips typed event values and allocations without stale transport fields`, () => {
    const draft = edit(currentSource([event]));
    assert.deepEqual(sourceCommand(draft).case.events, [event]);
    assert.deepEqual(sourceCommand(draft).eventEvidence, [{ eventIndex: 0, documentIds: ["event-0"], governanceReceiptId: "governance-0" }]);
    assert.equal(Object.hasOwn(sourceCommand(draft).eventEvidence[0], "eventSha256"), false);
  });
}

test("reordering events keeps each original evidence association and assigns fresh indexes", () => {
  const draft = edit();
  draft.events = [draft.events[5], draft.events[0], draft.events[4]];
  draft.events[2].values.consideration = "12,123456";
  const command = sourceCommand(draft);
  assert.deepEqual(command.case.events.map(e => e.type), ["dividend", "formation", "share_sale"]);
  assert.equal(command.case.events[2].consideration, "12.123456");
  assert.deepEqual(command.eventEvidence, [
    { eventIndex: 0, documentIds: ["event-5"], governanceReceiptId: "governance-5" },
    { eventIndex: 1, documentIds: ["event-0"], governanceReceiptId: "governance-0" },
    { eventIndex: 2, documentIds: ["event-4"], governanceReceiptId: "governance-4" },
  ]);
});

test("civil times retain DST-gap and repeated-hour wall times and append only missing whole seconds", () => {
  const draft = edit(currentSource([events()[0], events()[5]]));
  draft.events[0].timestamp = "2025-03-30T02:30";
  assert.deepEqual(sourceCommand(draft).case.events.map(e => e.timestamp), [civilTime, "2025-10-26T02:30:00"]);
});
for (const timestamp of ["2025-03-30T02:30:00Z", "2025-03-30T02:30:00+02:00", "2025-03-30T02:30:00.001", "2025-03-30", ""]) {
  test(`civil event rejects timezone or incomplete timestamp ${timestamp}`, () => {
    const draft = edit(currentSource([events()[0]]));
    draft.events[0].timestamp = timestamp;
    assert.throws(() => sourceCommand(draft), /lokal dato/);
  });
}

test("paid-in command values have one editable source and preserve all six decimal digits", () => {
  const current = currentSource([]);
  // Historical copies are never a second source of editable paid-in amounts.
  current.paidIn = { openingCapital: "1", closingCapital: "2", openingPremium: "3", closingPremium: "4" };
  const draft = edit(current);
  draft.shares.previousPaidInShareCapital = "9007199254740993,000001";
  draft.shares.currentPaidInShareCapital = "10,000002";
  draft.shares.previousPaidInPremium = "20,000003";
  draft.shares.currentPaidInPremium = "30,000004";
  const command = sourceCommand(draft);
  assert.deepEqual(command.paidIn, { openingCapital: exactMoney, closingCapital: "10.000002", openingPremium: "20.000003", closingPremium: "30.000004" });
  assert.equal(command.paidIn.openingCapital, command.case.shareSnapshot.previousPaidInShareCapital);
  assert.equal(command.paidIn.closingCapital, command.case.shareSnapshot.currentPaidInShareCapital);
  assert.equal(command.paidIn.openingPremium, command.case.shareSnapshot.previousPaidInPremium);
  assert.equal(command.paidIn.closingPremium, command.case.shareSnapshot.currentPaidInPremium);
  assert.equal(new Set(shareFields.map(f => f.key)).size, shareFields.length);
});

test("content edits clear all four confirmations without destroying work or mutating the prior draft", () => {
  const before = { ...edit(), identitiesReviewed: true, completeYearConfirmed: true, paidInReviewed: true, noActivityConfirmed: true };
  const cleared = resetReview(before);
  for (const field of reviews) {
    assert.equal(cleared[field], false);
    assert.equal(before[field], true);
  }
  assert.deepEqual(cleared.events, before.events);
  assert.deepEqual(cleared.documents, before.documents);
  assert.equal(cleared.supersedesSourceId, before.supersedesSourceId);
  assert.notEqual(cleared, before);
});

test("new events have independent empty evidence and never imply registration", () => {
  const one = newEvent("cash_issue", "one");
  const two = newEvent("cash_issue", "two");
  one.documentIds.push("one-document");
  one.allocations.push({ shareholderId: "owner-person", values: { shareCount: "1" } });
  assert.deepEqual(two, { key: "two", type: "cash_issue", timestamp: "", values: {}, allocations: [], registrationConfirmed: false, documentIds: [], governanceReceiptId: "" });
});


test("missing retained shareholder counts remain blank and cannot become an implicit zero", () => {
  const current = currentSource([]);
  current.case.shareholderSnapshots = current.case.shareholderSnapshots.filter(row => row.shareholderId !== "owner-person");
  const draft = edit(current);
  assert.equal(draft.holders[0].previousShareCount, "");
  assert.equal(draft.holders[0].currentShareCount, "");
  assert.throws(() => sourceCommand(draft), /Synthetic Owner/);
});

test("a first source never sends a correction reason or fabricates a predecessor", () => {
  const draft = edit(currentSource([]));
  draft.supersedesSourceId = null;
  draft.supersedesSourceSha256 = null;
  draft.correctionReason = "Unused text";
  const command = sourceCommand(draft);
  assert.equal(command.supersedesSourceId, null);
  assert.equal(command.supersedesSourceSha256, null);
  assert.equal(command.correctionReason, null);
});


test("a missing capture response freezes the exact attempt through later validation refusals", () => {
  const command = sourceCommand(edit());
  const attempt = { command, key: "same-attempt-key", uncertain: false };
  assert.equal(afterCaptureFailure(attempt, true), null, "first definitive rejection permits correction");
  const uncertain = afterCaptureFailure(attempt, false);
  assert.equal(uncertain.uncertain, true);
  assert.strictEqual(uncertain.command, command);
  assert.equal(uncertain.key, attempt.key);
  const stillUncertain = afterCaptureFailure(uncertain, true);
  assert.deepEqual(stillUncertain, uncertain);
  assert.strictEqual(stillUncertain.command, command);
  assert.deepEqual(afterCaptureFailure(stillUncertain, false), uncertain);
  assert.equal(attempt.uncertain, false, "do not mutate earlier state");
});
