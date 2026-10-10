/** Exact superseded-body compatibility for disposable predecessor rehearsals. */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const rule = JSON.parse(readFileSync(
  new URL("../fixtures/governance_completion_replay.json", import.meta.url), "utf8",
));
const digest = value => createHash("sha256").update(value, "utf8").digest("hex");

export function adaptGovernanceCompletionRehearsal(relative, source) {
  if (relative !== `migrations/${rule.migration}`) return source;
  if (typeof source !== "string" || digest(source) !== rule.sourceSha256
      || source.split(rule.before).length !== 2) {
    throw new Error("governance_completion_rehearsal_source_drift");
  }
  const adapted = source.replace(rule.before, rule.after);
  if (digest(adapted) !== rule.rehearsalSha256) {
    throw new Error("governance_completion_rehearsal_source_drift");
  }
  return adapted;
}
