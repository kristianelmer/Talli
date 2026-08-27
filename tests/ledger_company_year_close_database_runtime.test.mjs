import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const migration = readFileSync(new URL(
  "../supabase/migrations/20260827104000_ledger_company_year_close.sql",
  import.meta.url,
), "utf8");
const lifecycle = readFileSync(new URL(
  "./ledger_database_runtime.test.mjs",
  import.meta.url,
), "utf8");
const rollback = readFileSync(new URL(
  "../supabase/rollback/20260827101000_ledger_capability_contract.sql",
  import.meta.url,
), "utf8");

const closeFunction = migration.match(
  /create or replace function ledger\.close_company_year_v1\([\s\S]+?\$function\$\s*;/iu,
)?.[0];
const replayFunction = migration.match(
  /create or replace function ledger\.get_company_year_close_replay_v1\([\s\S]+?\$function\$\s*;/iu,
)?.[0];
const queryFunction = migration.match(
  /create or replace function ledger\.get_company_year_close_assessment_v1\([\s\S]+?\$function\$\s*;/iu,
)?.[0];
const postFunction = migration.match(
  /create or replace function ledger\.post_entry\([\s\S]+?\$function\$\s*;/iu,
)?.[0];

test("company-year close has one evidence-gated atomic database interface", () => {
  assert.ok(closeFunction);
  assert.match(closeFunction, /p_reconstruction_assessment_id uuid/iu);
  assert.match(closeFunction, /p_reconstruction_digest text/iu);
  assert.match(closeFunction, /p_evidence jsonb/iu);
  assert.match(closeFunction, /returns table \([\s\S]+assessment_id uuid[\s\S]+reconstruction_assessment_id uuid[\s\S]+close_lock_id uuid[\s\S]+ledger_state_digest text[\s\S]+is_current boolean[\s\S]+replayed boolean/iu);
  assert.match(closeFunction, /ledger\.lock_company_year_v1/iu);
  assert.doesNotMatch(closeFunction, /ledger\.period_locks/iu);
  assert.match(closeFunction, /ledger\.company_year_close_locks/iu);
  assert.match(closeFunction, /operation_name = 'close_company_year'/u);
  assert.match(closeFunction, /'PERIOD_END_UNSUPPORTED'/u);
  assert.match(closeFunction, /'CHECK_EVIDENCE_INCOMPLETE'/u);
  assert.match(
    closeFunction,
    /select distinct gap[\s\S]+pg_catalog\.unnest\(p_gap_codes\)[\s\S]+v_requested_gaps is distinct from v_derived_gaps/iu,
  );
  for (const gap of [
    "BANK_NOT_RECONCILED",
    "DUPLICATE_POSTING_FOUND",
    "JOURNAL_UNBALANCED",
    "MATERIAL_BALANCE_UNDOCUMENTED",
    "REPORTING_NOT_RECONCILED",
    "SOURCE_INCOMPLETE",
    "UNRESOLVED_BANK_ROW",
    "UNSUPPORTED_TRANSACTION",
  ]) {
    assert.match(closeFunction, new RegExp(`'${gap}'`, "u"));
  }
  assert.match(
    closeFunction,
    /not ledger\.entry_lines_are_valid_v1\(entry\.lines, true\)[\s\S]+JOURNAL_UNBALANCED/iu,
  );
  assert.match(
    closeFunction,
    /group by entry\.source_capability, entry\.source_record_id[\s\S]+DUPLICATE_POSTING_FOUND/iu,
  );
});

test("close replay and latest query share one exact raw-command fingerprint", () => {
  assert.ok(replayFunction);
  assert.ok(queryFunction);
  assert.match(
    migration,
    /create or replace function ledger\.company_year_close_request_fingerprint_v1/iu,
  );
  for (const callable of [closeFunction, replayFunction]) {
    assert.match(callable, /company_year_close_request_fingerprint_v1/iu);
  }
  const fingerprint = migration.match(
    /create or replace function ledger\.company_year_close_request_fingerprint_v1\([\s\S]+?\$function\$\s*;/iu,
  )?.[0];
  assert.ok(fingerprint);
  assert.match(fingerprint, /'correlationId', p_correlation_id/u);
  assert.doesNotMatch(fingerprint, /derivedState|gapCodes/u);
  assert.match(replayFunction, /operation_name = 'close_company_year'/u);
  assert.match(
    replayFunction,
    /company_access_is_accepted_owner_v1\(p_company_id\)[\s\S]+ledger_forbidden/iu,
  );
  assert.match(replayFunction, /is_current/iu);
  assert.match(queryFunction, /order by assessment\.recorded_at desc, assessment\.id desc/iu);
});

test("ordinary posting is receipt-first and serialized behind statutory close", () => {
  assert.ok(postFunction);
  assert.match(postFunction, /post_entry_without_company_year_close_lock_v1/iu);
  assert.match(postFunction, /operation_name = 'post_entry'/u);
  assert.match(postFunction, /ledger\.lock_company_year_v1/iu);
  assert.match(postFunction, /ledger\.company_year_close_locks/iu);
  assert.match(postFunction, /raise exception 'ledger_period_locked'/u);
  assert.ok(
    postFunction.indexOf("operation_name = 'post_entry'")
      < postFunction.indexOf("ledger.company_year_close_locks"),
  );
});

test("close assessments and evidence are immutable forced-RLS ledger data", () => {
  for (const table of [
    "company_year_close_assessments",
    "company_year_close_evidence",
    "company_year_close_locks",
    "company_year_close_reporting_outputs",
  ]) {
    assert.match(migration, new RegExp(
      `alter table ledger\\.${table} force row level security`, "iu",
    ));
  }
  assert.match(migration, /create trigger ledger_company_year_close_assessments_immutable/iu);
  assert.match(migration, /create trigger ledger_company_year_close_evidence_immutable/iu);
  assert.match(migration, /create trigger ledger_company_year_close_locks_immutable/iu);
  assert.match(migration, /create trigger ledger_company_year_close_reporting_outputs_immutable/iu);
  assert.match(migration, /alter table ledger\.reconstruction_assessments[\s\S]+ledger_state_digest/iu);
  assert.match(migration, /company_year_ledger_state_digest_v1/iu);
  for (const outputKind of [
    "INVESTMENTS",
    "CORPORATE_GOVERNANCE",
    "SHAREHOLDER_REGISTER_FILING",
    "COMPANY_TAX_FILING",
    "ANNUAL_ACCOUNTS_FILING",
    "SAF_T",
    "COMPANY_ARCHIVE",
  ]) {
    assert.match(migration, new RegExp(`'${outputKind}'`, "u"));
  }
  assert.doesNotMatch(
    migration,
    /grant[^;]+(?:insert|update|delete)[^;]+ledger\.company_year_close_(?:assessments|evidence)[^;]+ledger_executor/iu,
  );
});

test("database lifecycle covers close, correction staleness, rollback and recutover", () => {
  for (const evidence of [
    "close_company_year_v1",
    "PERIOD_END_UNSUPPORTED",
    "CHECK_EVIDENCE_INCOMPLETE",
    "company_year_close_assessments",
    "staleCloseDigest",
    "recutoverCloseReplay",
    "journalUnbalancedClose",
    "duplicatePostingClose",
    "closeReplayBeforeFreshness",
    "latestCloseAssessment",
    "postReplayAfterStatutoryClose",
    "supportedPostAfterStatutoryClose",
    "linkedCorrectionAfterStatutoryClose",
    "set role = 'reviewer'",
  ]) {
    assert.match(lifecycle, new RegExp(evidence, "u"));
  }
  assert.match(closeFunction, /to_regclass\('ledger\.entries'\) is null[\s\S]+ledger_cutover_inactive/iu);
  assert.match(rollback, /alter table ledger\.period_locks set schema public/iu);
  assert.match(
    rollback,
    /ledger_legacy_enforce_v1[\s\S]+ledger\.company_year_close_locks[\s\S]+ledger_period_locked/iu,
  );
  for (const targetWriter of [
    "post_supported_entry_v1",
    "correct_entry_v1",
    "record_reconstruction_assessment",
    "close_company_year_v1",
  ]) {
    assert.match(rollback, new RegExp(`revoke all on function ledger\\.${targetWriter}`, "iu"));
  }
});
