import { buildPersistedCompanyArchive } from "../../../../lib/archive";
import { requireStepUpForAction } from "../../../../lib/security";
import { createSupabaseServerClient } from "../../../../lib/supabase/server";

export async function GET(_request: Request, { params }: { params: Promise<Record<string, string>> }) {
  const { companyId, incomeYear: incomeYearParam } = await params;
  const incomeYear = Number(incomeYearParam);
  if (!companyId || !Number.isInteger(incomeYear)) {
    return new Response("Invalid archive request", { status: 400 });
  }

  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return new Response("Innlogging kreves", { status: 401 });
  }

  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by, identity_confirmed_at, identity_locked_at, created_at")
    .eq("id", companyId)
    .single();
  if (companyError || !company) {
    return new Response("Archive not found", { status: 404 });
  }
  try {
    await requireStepUpForAction({
      supabase,
      userId: user.id,
      companyId,
      action: "archive_export",
    });
  } catch {
    return new Response(
      "Ekstra identitetsbekreftelse med tofaktorautentisering kreves før arkivet kan lastes ned.",
      { status: 403 },
    );
  }

  const { data: submissions, error: submissionError } = await supabase
    .from("filing_submissions")
    .select("id, preview_id, authority_test_run_id, company_id, income_year, filing, mode, adapter_mode, payload_hash, idempotency_key, status, calls, receipt_id, feedback_document_ids, feedback_items, receipt_metadata, submitted_payload_ref, submitted_payload, authority_confirmed_at, preview_confirmed_at, created_at, updated_at, submitted_by")
    .eq("company_id", companyId)
    .eq("income_year", incomeYear);
  if (submissionError) {
    return new Response("Could not read filing submissions", { status: 500 });
  }
  if (!submissions?.length) {
    return new Response("Archive requires RF-1086 submission state first", { status: 409 });
  }
  const authorityTestRunIds = [...new Set(
    submissions
      .filter((submission) => submission.mode === "test_authority")
      .map((submission) => submission.authority_test_run_id)
      .filter((id): id is string => Boolean(id)),
  )];
  const { data: authorityTestRuns, error: authorityTestRunsError } = authorityTestRunIds.length
    ? await supabase
        .from("authority_test_runs")
        .select("id, company_id, obligation, environment, status, test_reference, feedback_summary, receipt_reference, archive_reference, evidence_url, payload_hash, recorded_by, recorded_at")
        .in("id", authorityTestRunIds)
    : { data: [], error: null };
  if (authorityTestRunsError) {
    return new Response("Could not read authority evidence", { status: 500 });
  }

  const [
    { data: setups },
    { data: ledgerEntries },
    { data: documents },
    { data: previews },
    { data: holdingActions },
    { data: billingAccounts },
    { data: authorityPermissions },
    { data: reviewComments },
    { data: auditEvents },
    { data: investmentPositions },
    { data: investmentLots },
    { data: investmentLotAllocations },
    { data: bankSuggestionAcceptances },
    { data: corporateDecisions, error: corporateDecisionsError },
    { data: corporateDocumentSets, error: corporateDocumentSetsError },
    { data: corporateDocumentArtifacts, error: corporateDocumentArtifactsError },
    { data: corporateDocumentEvents, error: corporateDocumentEventsError },
    { data: corporateDecisionFinalizations, error: corporateDecisionFinalizationsError },
  ] =
    await Promise.all([
      supabase
        .from("opening_balance_setups")
        .select("id, company_id, income_year, bank_balance, share_capital, share_count, nominal_value, locked_at, created_by")
        .eq("company_id", companyId)
        .eq("income_year", incomeYear),
      supabase
        .from("ledger_entries")
        .select("id, company_id, setup_id, income_year, entry_type, memo, lines, created_by, created_at")
        .eq("company_id", companyId)
        .eq("income_year", incomeYear),
      supabase
        .from("documents")
        .select("id, company_id, income_year, document_type, name, linked_to, status, retention_years, storage_key, created_by, created_at")
        .eq("company_id", companyId)
        .eq("income_year", incomeYear),
      supabase
        .from("filing_previews")
        .select("id, company_id, setup_id, income_year, filing, status, issues, preview, hovedskjema_xml, underskjema_xml, source, created_at")
        .eq("company_id", companyId)
        .eq("income_year", incomeYear),
      supabase
        .from("holding_actions")
        .select("id, company_id, income_year, action_type, action_date, payload, ledger_entry_id, bank_transaction_id, document_id, risk_level, blocker_code, created_by, created_at")
        .eq("company_id", companyId)
        .eq("income_year", incomeYear),
      supabase
        .from("billing_accounts")
        .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, refund_completed, no_charge_reason, provider_customer_ref, subscription_provider_ref, filing_package_payment_ref, refund_provider_ref, updated_by, created_at, updated_at")
        .eq("company_id", companyId),
      supabase
        .from("authority_permissions")
        .select("id, company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled, updated_at")
        .eq("company_id", companyId),
      supabase
        .from("filing_review_comments")
        .select("id, preview_id, company_id, target, severity, body, created_by, acknowledged_by, acknowledged_at, created_at")
        .eq("company_id", companyId),
      supabase
        .from("audit_events")
        .select("id, company_id, actor_id, category, action, message, created_at")
        .eq("company_id", companyId),
      supabase
        .from("investment_positions")
        .select("id, company_id, investment_key, name, kind, tax_treatment, org_number, share_count, cost_basis, lot_history_status, movements, created_by, created_at, updated_at")
        .eq("company_id", companyId),
      supabase
        .from("investment_lots")
        .select("id, company_id, position_id, acquisition_action_id, acquisition_date, original_share_count, remaining_share_count, original_cost_basis, remaining_cost_basis, created_by, created_at")
        .eq("company_id", companyId),
      supabase
        .from("investment_lot_allocations")
        .select("id, company_id, position_id, lot_id, sale_action_id, allocated_share_count, allocated_cost_basis, created_by, created_at")
        .eq("company_id", companyId),
      supabase
        .from("bank_suggestion_acceptances")
        .select("id, company_id, bank_transaction_id, ledger_entry_id, rule_id, rule_version, reason, lines, accepted_by, accepted_at")
        .eq("company_id", companyId),
      supabase
        .from("corporate_decisions")
        .select("id, company_id, income_year, decision_kind, annual_close_source_id, source_hash, canonical_input, decision_hash, supersedes_decision_id, created_by, created_at")
        .eq("company_id", companyId)
        .eq("income_year", incomeYear),
      supabase
        .from("corporate_document_sets")
        .select("id, company_id, income_year, decision_id, template_family, template_version, decision_hash, supersedes_set_id, created_by, created_at")
        .eq("company_id", companyId)
        .eq("income_year", incomeYear),
      supabase
        .from("corporate_document_artifacts")
        .select("id, company_id, income_year, set_id, artifact_kind, variant, document_id, content_sha256, byte_length, mime_type, storage_key, supersedes_artifact_id, created_by, created_at")
        .eq("company_id", companyId)
        .eq("income_year", incomeYear),
      supabase
        .from("corporate_document_events")
        .select("id, company_id, income_year, decision_id, set_id, artifact_id, event_kind, actor_id, occurred_at, decision_hash, content_sha256, metadata, idempotency_key, created_at")
        .eq("company_id", companyId)
        .eq("income_year", incomeYear),
      supabase
        .from("corporate_decision_finalizations")
        .select("id, company_id, income_year, decision_id, finalization_kind, holding_action_id, ledger_entry_id, annual_close_source_id, decision_hash, signed_artifact_hashes, accounting_policy_version, created_by, created_at")
        .eq("company_id", companyId)
        .eq("income_year", incomeYear),
    ]);

  const corporateError = corporateDecisionsError
    ?? corporateDocumentSetsError
    ?? corporateDocumentArtifactsError
    ?? corporateDocumentEventsError
    ?? corporateDecisionFinalizationsError;
  if (corporateError) {
    return new Response("Could not read corporate decision evidence", { status: 500 });
  }

  const setupIds = (setups ?? []).map((setup) => setup.id);
  const { data: shareholders } = setupIds.length
    ? await supabase
        .from("opening_shareholders")
        .select("id, setup_id, company_id, name, shareholder_kind, national_id, org_number, share_count")
        .in("setup_id", setupIds)
    : { data: [] };

  const archive = buildPersistedCompanyArchive({
    company,
    incomeYear,
    setups: setups ?? [],
    shareholders: shareholders ?? [],
    ledgerEntries: ledgerEntries ?? [],
    documents: documents ?? [],
    holdingActions: holdingActions ?? [],
    investmentPositions: investmentPositions ?? [],
    investmentLots: investmentLots ?? [],
    investmentLotAllocations: investmentLotAllocations ?? [],
    bankSuggestionAcceptances: bankSuggestionAcceptances ?? [],
    billingAccounts: billingAccounts ?? [],
    authorityPermissions: authorityPermissions ?? [],
    authorityTestRuns: authorityTestRuns ?? [],
    auditEvents: auditEvents ?? [],
    reviewComments: reviewComments ?? [],
    filingPreviews: previews ?? [],
    filingSubmissions: submissions ?? [],
    corporateDecisions: corporateDecisions ?? [],
    corporateDocumentSets: corporateDocumentSets ?? [],
    corporateDocumentArtifacts: corporateDocumentArtifacts ?? [],
    corporateDocumentEvents: corporateDocumentEvents ?? [],
    corporateDecisionFinalizations: corporateDecisionFinalizations ?? [],
  });

  const { error: auditError } = await supabase.from("audit_events").insert({
    company_id: companyId,
    actor_id: user.id,
    category: "archive",
    action: `company_year_archive_exported:${incomeYear}`,
    message: `Company-year archive exported with ${(corporateDocumentArtifacts ?? []).length} corporate object references.`,
  });
  if (auditError) {
    return new Response("Could not record archive export evidence", { status: 500 });
  }

  return new Response(JSON.stringify(archive, null, 2), {
    headers: {
      "content-disposition": `attachment; filename="talli-${company.org_number}-${incomeYear}-archive.json"`,
      "content-type": "application/json; charset=utf-8",
    },
  });
}
