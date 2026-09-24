import assert from "node:assert/strict";
import test from "node:test";
import { editRegister, registerCommand, resetRegisterReview, registerKinds } from "../app/(owner)/filing/aksjonaerregisteroppgaven/register/model.ts";
import { afterCaptureFailure } from "../app/(owner)/filing/aksjonaerregisteroppgaven/source/model.ts";

const companyId = "10000000-0000-4000-8000-000000000001";
const observationId = "20000000-0000-4000-8000-000000000001";
const documentId = "30000000-0000-4000-8000-000000000001";
const hash = "a".repeat(64);
const exactMoney = "9007199254740993.000001";
const civilTime = "2025-03-30T02:30:00";
const confirmations = ["completeRegisterConfirmed", "registrationConfirmed", "singleShareClassConfirmed"];
const original = () => ({ documentId, companyId, contentVersionSha256: hash, contentSha256: hash,
  metadataSha256: "b".repeat(64), sourceIncomeYear: 2024, byteLength: 123,
  documentType: "corporate_document", integrityStatus: "attached", createdAt: "2024-12-31T12:00:00Z" });
function retained(eventKind = "cash_issue") {
  return { companyId, incomeYear: 2025, eventKind, effectiveAt: civilTime,
    before: { shareCapital: "30000.000000", nominalValue: "300.000000", shareCount: 100,
      holdings: [{ shareholderId: "person", name: "Synthetic Person", kind: "norwegian_person", identifier: "01234567890", shareCount: 100 }] },
    after: { shareCapital: "60000.000000", nominalValue: "300.000000", shareCount: 200,
      holdings: [{ shareholderId: "person", name: "Synthetic Person", kind: "norwegian_person", identifier: "01234567890", shareCount: 150 },
        { shareholderId: "company", name: "Synthetic Parent AS", kind: "norwegian_company", identifier: "012345678", shareCount: 50 }] },
    documents: ["register_before", "register_after", "registration"].map(role => ({ ...original(), role })),
    completeRegisterConfirmed: true, registrationConfirmed: true, singleShareClassConfirmed: true,
    supersedesObservationId: observationId, supersedesObservationSha256: hash, correctionReason: "Previously reviewed reason" };
}
const edit = (value = retained()) => editRegister(companyId, 2025, value);

test("a new independent register draft has no inferred year-source facts, originals or confirmations", () => {
  const draft = editRegister(companyId, 2025, null);
  assert.equal(draft.companyId, companyId);
  assert.equal(draft.incomeYear, 2025);
  assert.equal(draft.effectiveAt, "");
  for (const state of [draft.before, draft.after]) assert.deepEqual(state, { shareCapital: "", nominalValue: "", shareCount: "", holdings: [] });
  assert.notEqual(draft.before, draft.after);
  assert.deepEqual(draft.documents, []);
  assert.deepEqual(draft.roles, { register_before: [], register_after: [], registration: [] });
  assert.equal(draft.supersedesObservationId, null);
  assert.equal(draft.supersedesObservationSha256, null);
  for (const flag of confirmations) assert.equal(draft[flag], false);
  draft.before.shareCapital = "30000";
  draft.before.holdings.push({ shareholderId: "owner" });
  assert.equal(draft.after.shareCapital, "");
  assert.deepEqual(draft.after.holdings, []);
  assert.throws(() => registerCommand(draft), /lokal dato/);
});

for (const eventKind of Object.keys(registerKinds)) {
  test(`${eventKind} retains exact independent facts without inferring transitions or reporting readiness`, () => {
    const current = retained(eventKind), draft = edit(current);
    const command = registerCommand(draft);
    assert.equal(command.eventKind, eventKind);
    assert.equal(command.effectiveAt, civilTime);
    assert.deepEqual(command.before, current.before);
    assert.deepEqual(command.after, current.after);
    assert.deepEqual(command.documents, current.documents);
    for (const flag of confirmations) assert.equal(command[flag], false);
    assert.equal(command.supersedesObservationId, observationId);
    assert.equal(command.supersedesObservationSha256, hash);
    assert.equal(command.correctionReason, "");
  });
}

test("corrections keep original event identity, second precision and predecessor when economic fields change", () => {
  const current = retained("loss_covering_reduction"); current.effectiveAt = "2025-10-26T02:30:17";
  const draft = edit(current);
  draft.before.shareCapital = exactMoney;
  draft.after.shareCapital = "50000.000001";
  draft.correctionReason = "Kontrollert mot korrigert original";
  for (const flag of confirmations) draft[flag] = true;
  const command = registerCommand(draft);
  assert.equal(command.effectiveAt, current.effectiveAt);
  assert.equal(command.eventKind, current.eventKind);
  assert.equal(command.supersedesObservationId, observationId);
  assert.equal(command.supersedesObservationSha256, hash);
  assert.equal(command.correctionReason, draft.correctionReason);
  for (const flag of confirmations) assert.equal(command[flag], true);
});

test("all register amounts preserve large values and six fractional digits without Number conversion", () => {
  const draft = edit();
  draft.before.shareCapital = exactMoney;
  draft.before.nominalValue = " 42,010000 ";
  draft.after.shareCapital = "9007199254740993,000001";
  draft.after.nominalValue = "0.000001";
  const command = registerCommand(draft);
  assert.equal(command.before.shareCapital, exactMoney);
  assert.equal(command.before.nominalValue, "42.010000");
  assert.equal(command.after.shareCapital, exactMoney);
  assert.equal(command.after.nominalValue, "0.000001");
  assert.equal(command.before.holdings[0].identifier, "01234567890");
  assert.equal(command.after.holdings[1].identifier, "012345678");
});

for (const side of ["before", "after"]) {
  for (const field of ["shareCapital", "nominalValue"]) {
    test(`${side} ${field} refuses excess precision without rounding`, () => {
      const draft = edit(); draft[side][field] = "1.1234567";
      assert.throws(() => registerCommand(draft), /desimaler/);
    });
  }
  for (const position of ["total", "holding"]) {
    test(`${side} ${position} share counts reject unsafe integers rather than rounding`, () => {
      const draft = edit();
      const set = value => { if (position === "total") draft[side].shareCount = value; else draft[side].holdings[0].shareCount = value; };
      set(String(Number.MAX_SAFE_INTEGER));
      const command = registerCommand(draft);
      assert.equal(position === "total" ? command[side].shareCount : command[side].holdings[0].shareCount, Number.MAX_SAFE_INTEGER);
      for (const value of ["9007199254740992", "1.5", "1e3", "", "-1"]) {
        set(value); assert.throws(() => registerCommand(draft));
      }
    });
  }
}

for (const timestamp of [civilTime, "2025-10-26T02:30:00", "2025-04-01T14:15:16"]) {
  test(`civil register time ${timestamp} survives unchanged`, () => {
    const draft = edit(); draft.effectiveAt = timestamp;
    assert.equal(registerCommand(draft).effectiveAt, timestamp);
  });
}
test("civil minute input appends whole seconds only", () => {
  const draft = edit(); draft.effectiveAt = "2025-03-30T02:30";
  assert.equal(registerCommand(draft).effectiveAt, civilTime);
});
for (const timestamp of ["2025-03-30T02:30:00Z", "2025-03-30T02:30:00+02:00", "2025-03-30T02:30:00.001", "2025-03-30", ""]) {
  test(`register refuses timezone or incomplete civil time ${timestamp}`, () => {
    const draft = edit(); draft.effectiveAt = timestamp;
    assert.throws(() => registerCommand(draft), /lokal dato/);
  });
}

test("one original assigned to all three roles retains each role and exact immutable metadata", () => {
  const current = retained(), snapshot = structuredClone(current), draft = edit(current);
  assert.deepEqual(draft.documents, [original()]);
  for (const ids of Object.values(draft.roles)) assert.deepEqual(ids, [documentId]);
  assert.deepEqual(registerCommand(draft).documents, current.documents);
  draft.documents[0].metadataSha256 = "c".repeat(64);
  draft.roles.register_before.push("new-document");
  draft.before.holdings[0].name = "Edited Person";
  draft.after.holdings[0].shareCount = "199";
  assert.deepEqual(current, snapshot, "editor changes cannot mutate retained server values");
});

test("orphan original roles fail instead of silently omitting evidence", () => {
  const draft = edit(); draft.documents = [];
  assert.throws(() => registerCommand(draft), /dokumentopplysningene/);
});

test("content edits reset all three owner confirmations while retaining correction work and roles", () => {
  const before = edit(); for (const flag of confirmations) before[flag] = true;
  before.correctionReason = "Ny kontroll";
  const after = resetRegisterReview(before);
  for (const flag of confirmations) { assert.equal(after[flag], false); assert.equal(before[flag], true); }
  assert.deepEqual(after, { ...before, completeRegisterConfirmed: false, registrationConfirmed: false, singleShareClassConfirmed: false });
});

test("a first observation never sends a correction reason or invents ancestry", () => {
  const draft = edit(); draft.supersedesObservationId = null; draft.supersedesObservationSha256 = null;
  draft.correctionReason = "Unused text";
  const command = registerCommand(draft);
  assert.equal(command.supersedesObservationId, null);
  assert.equal(command.supersedesObservationSha256, null);
  assert.equal(command.correctionReason, null);
});

test("a register attempt freezes its exact body and key through an unknown result and later refusal", () => {
  const draft = edit(), command = registerCommand(draft), snapshot = structuredClone(command);
  const attempt = { command, key: "register-attempt-0001", uncertain: false };
  assert.equal(afterCaptureFailure(attempt, true), null);
  const unknown = afterCaptureFailure(attempt, false);
  const stillUnknown = afterCaptureFailure(unknown, true);
  assert.strictEqual(stillUnknown.command, command);
  assert.equal(stillUnknown.key, attempt.key);
  assert.equal(stillUnknown.uncertain, true);
  draft.before.holdings[0].name = "Later edited name";
  draft.documents[0].metadataSha256 = "d".repeat(64);
  draft.roles.register_after.length = 0;
  assert.deepEqual(command, snapshot, "the attempt body must be independent of subsequent draft mutations");
});
