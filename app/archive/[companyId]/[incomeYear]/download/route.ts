import { buildPersistedCompanyArchive } from "../../../../lib/archive";
import { createSupabaseServerClient } from "../../../../lib/supabase/server";

export async function GET(_request: Request, { params }: { params: Promise<Record<string, string>> }) {
  const { companyId, incomeYear: incomeYearParam } = await params;
  const incomeYear = Number(incomeYearParam);
  if (!companyId || !Number.isInteger(incomeYear)) {
    return new Response("Invalid archive request", { status: 400 });
  }

  const supabase = await createSupabaseServerClient();
  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by, identity_confirmed_at, identity_locked_at, created_at")
    .eq("id", companyId)
    .single();
  if (companyError || !company) {
    return new Response("Archive not found", { status: 404 });
  }

  const { data: submissions, error: submissionError } = await supabase
    .from("filing_submissions")
    .select("id, preview_id, company_id, income_year, filing, mode, status, calls, receipt_id, feedback_document_ids, authority_confirmed_at, preview_confirmed_at, created_at, updated_at")
    .eq("company_id", companyId)
    .eq("income_year", incomeYear);
  if (submissionError) {
    return new Response("Could not read filing submissions", { status: 500 });
  }
  if (!submissions?.some((submission) => submission.receipt_id)) {
    return new Response("Archive requires simulated receipt first", { status: 409 });
  }

  const [{ data: setups }, { data: ledgerEntries }, { data: documents }, { data: previews }, { data: holdingActions }, { data: billingAccounts }] =
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
        .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, no_charge_reason, updated_by, created_at, updated_at")
        .eq("company_id", companyId),
    ]);

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
    billingAccounts: billingAccounts ?? [],
    filingPreviews: previews ?? [],
    filingSubmissions: submissions ?? [],
  });

  return new Response(JSON.stringify(archive, null, 2), {
    headers: {
      "content-disposition": `attachment; filename="talli-${company.org_number}-${incomeYear}-archive.json"`,
      "content-type": "application/json; charset=utf-8",
    },
  });
}
