import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const actionsUrl = new URL("../apps/web/app/actions.ts", import.meta.url);
const pageUrl = new URL("../apps/web/app/(owner)/transactions/page.tsx", import.meta.url);

test("server recomputes a suggestion before invoking the atomic acceptance RPC", async () => {
  const source = await readFile(actionsUrl, "utf8");

  assert.match(source, /export async function acceptBankTransactionSuggestion/);
  assert.match(source, /suggestBankTransaction\(\{[\s\S]*transaction\.text[\s\S]*transaction\.amount/);
  assert.match(source, /suggestion\.ruleId !== requestedRuleId/);
  assert.match(source, /suggestion\.ruleVersion !== requestedRuleVersion/);
  assert.match(source, /\.rpc\("accept_bank_transaction_suggestion"/);
});

test("transaction queue requires an explicit owner submit for every suggestion", async () => {
  const source = await readFile(pageUrl, "utf8");

  assert.match(source, /suggestBankTransaction/);
  assert.match(source, /action=\{acceptBankTransactionSuggestion\}/);
  assert.match(source, /name="ruleId" value=\{suggestion\.ruleId\}/);
  assert.match(source, /name="ruleVersion" value=\{suggestion\.ruleVersion\}/);
  assert.doesNotMatch(source, /await acceptBankTransactionSuggestion/);
});
