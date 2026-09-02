import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const actionsUrl = new URL("../apps/web/app/actions.ts", import.meta.url);
const pageUrl = new URL("../apps/web/app/(owner)/transactions/page.tsx", import.meta.url);

test("banking coordinator revalidates the suggestion inside the atomic writer", async () => {
  const source = await readFile(actionsUrl, "utf8");
  const start = source.indexOf("export async function acceptBankTransactionSuggestion");
  const end = source.indexOf("\nexport async function ", start + 1);
  const action = source.slice(start, end);

  assert.notEqual(start, -1);
  assert.match(action, /acceptBankSuggestion\(/);
  assert.match(action, /acceptanceId: operationId/);
  assert.match(action, /expectedSuggestion: expectedSuggestion/);
  assert.match(action, /expectedRuleVersion: requestedRuleVersion/);
  assert.doesNotMatch(action, /\.rpc\("accept_bank_transaction_suggestion"/);
  assert.doesNotMatch(action, /suggestBankTransaction\(|matched_entry_id|matched_action_id/);
});

test("transaction queue requires an explicit owner submit for every suggestion", async () => {
  const source = await readFile(pageUrl, "utf8");

  assert.match(source, /const suggestion = transaction\.suggestion/);
  assert.match(source, /action=\{acceptBankTransactionSuggestion\}/);
  assert.match(source, /name="expectedSuggestion" value=\{suggestion\.kind\}/);
  assert.match(source, /name="ruleVersion" value=\{suggestion\.ruleVersion\}/);
  assert.doesNotMatch(source, /suggestBankTransaction|suggestion\.lines|name="account"/);
  assert.doesNotMatch(source, /await acceptBankTransactionSuggestion/);
});
