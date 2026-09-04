import { createHash } from "node:crypto";

import {
  loadLedgerEntriesForArchive,
  presentLedgerEntriesForArchive,
} from "../../../../../features/ledger";
import {
  loadInvestmentAcquisitionLots,
  loadInvestmentActivity,
  loadInvestmentPositions,
  loadInvestmentShareSaleAllocations,
  loadInvestmentCorrections,
  effectiveInvestmentActivity,
  presentAcquisitionLots,
  presentInvestmentActivity,
  presentInvestmentPositions,
  presentShareSaleAllocations,
  presentInvestmentCorrections,
} from "../../../../../features/investments";
import {
  loadDocumentBackupProjection,
} from "../../../../../features/documents";
import { listCorporateDecisionLifecycle } from "../../../../../features/corporate-governance";
import {
  buildPersistedCompanyArchive,
  firstArchiveSourceError,
} from "../../../../lib/archive";
import { loadAcceptedMembershipCompany } from "../../../../lib/company-access-context";
import { requireStepUpForAction } from "../../../../lib/security";
import { getCurrentSessionAccessToken } from "../../../../lib/supabase/auth-session";
import {
  createSupabaseServerClient,
  createSupabaseServiceRoleClient,
} from "../../../../lib/supabase/server";

async function loadArchiveLedgerEntries(
  accessToken: string,
  companyId: string,
  incomeYear: number,
) {
  try {
    const entries = await loadLedgerEntriesForArchive(accessToken, [companyId]);
    const presented = presentLedgerEntriesForArchive(entries);
    if (presented.some((entry) => entry.company_id !== companyId)) {
      throw new Error("Ledger query escaped the authorized company scope.");
    }
    return {
      data: presented
        .filter((entry) => entry.income_year === incomeYear)
        .map((entry) => ({
          id: entry.id,
          company_id: entry.company_id,
          setup_id: entry.setup_id,
          income_year: entry.income_year,
          entry_type: entry.entry_type,
          memo: entry.memo,
          lines: entry.lines,
          created_by: entry.created_by,
          created_at: entry.created_at,
        })),
      error: null,
    };
  } catch {
    return { data: null, error: new Error("Ledger archive source unavailable.") };
  }
}

async function loadArchiveDocuments(
  accessToken: string,
  companyId: string,
  incomeYear: number,
) {
  try {
    const result = await loadDocumentBackupProjection(accessToken, companyId, incomeYear);
    return {
      data: result.objects.map((document) => ({
        id: document.documentId,
        company_id: result.companyId,
        income_year: result.incomeYear,
        document_type: document.documentType,
        name: document.name,
        linked_to: document.linkedTo,
        status: document.status,
        retention_years: document.retentionYears,
        storage_key: document.storageKey,
        created_by: document.createdBy,
        created_at: document.createdAt,
        removed_at: document.removedAt,
        removed_by: null,
        removal_reason: document.removalReason,
      })),
      projection: result,
      error: null,
    };
  } catch {
    return { data: null, projection: null, error: new Error("Documents archive projection unavailable.") };
  }
}

async function loadArchiveCorporateLifecycle(
  accessToken: string,
  companyId: string,
  incomeYear: number,
) {
  try {
    const [lifecycle, documents] = await Promise.all([
      listCorporateDecisionLifecycle(accessToken, [companyId]),
      loadDocumentBackupProjection(accessToken, companyId, incomeYear),
    ]);
    const documentsById = new Map(
      documents.objects.map((document) => [document.documentId, document]),
    );
    const artifacts = lifecycle.corporateDocumentArtifacts
      .filter((item) => item.income_year === incomeYear)
      .map((artifact) => ({
        ...artifact,
        storage_key: documentsById.get(artifact.document_id)?.storageKey ?? "",
      }));
    if (artifacts.some((artifact) => !artifact.storage_key)) {
      throw new Error("Corporate artifact document evidence is incomplete.");
    }
    return {
      data: {
        corporateDecisions: lifecycle.corporateDecisions.filter(
          (item) => item.income_year === incomeYear,
        ),
        corporateDocumentSets: lifecycle.corporateDocumentSets.filter(
          (item) => item.income_year === incomeYear,
        ),
        corporateDocumentArtifacts: artifacts,
        corporateDocumentEvents: lifecycle.corporateDocumentEvents.filter(
          (item) => item.income_year === incomeYear,
        ),
        corporateDecisionFinalizations: lifecycle.corporateDecisionFinalizations.filter(
          (item) => item.income_year === incomeYear,
        ),
      },
      error: null,
    };
  } catch {
    return { data: null, error: new Error("Corporate-governance archive source unavailable.") };
  }
}

async function loadArchiveInvestments(
  accessToken: string,
  companyId: string,
  incomeYear: number,
) {
  try {
    const [activity, positions, lots, allocations, corrections] = await Promise.all([
      loadInvestmentActivity(accessToken, [companyId]),
      loadInvestmentPositions(accessToken, [companyId]),
      loadInvestmentAcquisitionLots(accessToken, [companyId]),
      loadInvestmentShareSaleAllocations(accessToken, [companyId]),
      loadInvestmentCorrections(accessToken, [companyId]),
    ]);
    const presentedActivity = presentInvestmentActivity(activity).map((item) => {
      if (item.action_type !== "share_sale") return item;
      return {
        ...item,
        payload: {
          ...item.payload,
          lot_allocations: allocations
            .filter((allocation) => allocation.saleActionId === item.id)
            .sort((left, right) => left.allocationOrder - right.allocationOrder)
            .map((allocation) => ({
              lot_id: allocation.lotId,
              acquisition_date: allocation.acquisitionDate,
              share_count: allocation.allocatedShareCount,
              cost_basis: Number(allocation.allocatedCostBasis.amount),
              book_cost_basis: Number(allocation.allocatedBookCostBasis.amount),
              tax_basis: Number(allocation.allocatedTaxBasis.amount),
              net_proceeds: Number(allocation.allocatedNetProceeds.amount),
              average_fund_equity_ratio_basis_points:
                allocation.averageFundEquityRatioBasisPoints,
              tax_gain_or_loss: Number(allocation.taxGainOrLoss.amount),
              exempt_gain: Number(allocation.exemptGain.amount),
              taxable_gain: Number(allocation.taxableGain.amount),
              non_deductible_loss: Number(allocation.nonDeductibleLoss.amount),
              deductible_loss: Number(allocation.deductibleLoss.amount),
            })),
        },
      };
    });
    const presentedPositions = presentInvestmentPositions(positions);
    const presentedLots = presentAcquisitionLots(lots);
    const presentedAllocations = presentShareSaleAllocations(allocations);
    const presentedCorrections = presentInvestmentCorrections(corrections);
    const allRecords = [
      ...presentedActivity,
      ...presentedPositions,
      ...presentedLots,
      ...presentedAllocations,
      ...presentedCorrections,
    ];
    if (allRecords.some((record) => record.company_id !== companyId)) {
      throw new Error("Investments query escaped the authorized company scope.");
    }
    return {
      data: {
        holdingActions: presentedActivity.filter(
          (activityItem) => activityItem.income_year === incomeYear,
        ),
        positions: presentedPositions,
        lots: presentedLots,
        allocations: presentedAllocations,
        corrections: presentedCorrections.filter(
          (correction) => correction.income_year === incomeYear,
        ),
      },
      error: null,
    };
  } catch {
    return { data: null, error: new Error("Investments archive source unavailable.") };
  }
}

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
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) {
    return new Response("Innlogging kreves", { status: 401 });
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
  const { data: archiveAttemptId, error: archiveAttemptError } = await supabase.rpc(
    "company_archive_begin_export",
    { p_company_id: companyId, p_income_year: incomeYear },
  );
  if (archiveAttemptError || typeof archiveAttemptId !== "string") {
    return new Response("Kunne ikke starte autoritativ arkiveksport", { status: 500 });
  }

  const company = await loadAcceptedMembershipCompany(companyId);
  if (!company) {
    return new Response("Fant ikke arkivet", { status: 404 });
  }

  const { data: submissions, error: submissionError } = await supabase
    .from("filing_submissions")
    .select("id, preview_id, authority_test_run_id, company_id, income_year, filing, mode, adapter_mode, payload_hash, idempotency_key, status, calls, receipt_id, feedback_document_ids, feedback_items, receipt_metadata, submitted_payload_ref, submitted_payload, authority_confirmed_at, preview_confirmed_at, created_at, updated_at, submitted_by")
    .eq("company_id", companyId)
    .eq("income_year", incomeYear);
  if (submissionError) {
    return new Response("Kunne ikke lese innsendingsgrunnlaget", { status: 500 });
  }
  if (!submissions?.length) {
    return new Response("Arkivet krever lagret RF-1086-status", { status: 409 });
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
    return new Response("Kunne ikke lese myndighetsdokumentasjonen", { status: 500 });
  }

  const sourceResults = await Promise.all([
      supabase
        .from("opening_balance_setups")
        .select("id, company_id, income_year, bank_balance, share_capital, share_count, nominal_value, locked_at, created_by")
        .eq("company_id", companyId)
        .eq("income_year", incomeYear),
      loadArchiveLedgerEntries(accessToken, companyId, incomeYear),
      loadArchiveDocuments(accessToken, companyId, incomeYear),
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
      loadArchiveInvestments(accessToken, companyId, incomeYear),
      supabase
        .from("bank_suggestion_acceptances")
        .select("id, company_id, bank_transaction_id, ledger_entry_id, rule_id, rule_version, reason, lines, accepted_by, accepted_at")
        .eq("company_id", companyId),
      loadArchiveCorporateLifecycle(accessToken, companyId, incomeYear),
    ]);
  if (firstArchiveSourceError(sourceResults)) {
    return new Response("Kunne ikke lese komplett arkivgrunnlag", { status: 500 });
  }
  const [
    { data: setups }, { data: ledgerEntries }, { data: documents, projection: documentBackupProjection }, { data: previews },
    { data: holdingActions }, { data: billingAccounts }, { data: authorityPermissions },
    { data: reviewComments }, { data: auditEvents }, { data: investments },
    { data: bankSuggestionAcceptances },
    { data: corporateLifecycle },
  ] = sourceResults;

  const setupIds = (setups ?? []).map((setup) => setup.id);
  const { data: shareholders, error: shareholdersError } = setupIds.length
    ? await supabase
        .from("opening_shareholders")
        .select("id, setup_id, company_id, name, shareholder_kind, national_id, org_number, share_count")
        .in("setup_id", setupIds)
    : { data: [], error: null };
  if (shareholdersError) {
    return new Response("Kunne ikke lese komplett arkivgrunnlag", { status: 500 });
  }

  const archive = buildPersistedCompanyArchive({
    company,
    incomeYear,
    setups: setups ?? [],
    shareholders: shareholders ?? [],
    ledgerEntries: ledgerEntries ?? [],
    documents: documents ?? [],
    documentBackupProjection: documentBackupProjection ?? undefined,
    holdingActions: [
      ...(holdingActions ?? []).filter(
        (action) => ![
          "share_purchase",
          "share_sale",
          "dividend_received",
          "fund_distribution_received",
          "shareholder_loan",
          "dividend_to_owner",
        ].includes(action.action_type),
      ),
      ...(investments?.holdingActions ?? []),
    ],
    investmentPositions: investments?.positions ?? [],
    investmentLots: investments?.lots ?? [],
    investmentLotAllocations: investments?.allocations ?? [],
    investmentCorrections: investments?.corrections ?? [],
    effectiveInvestmentActions: effectiveInvestmentActivity(
      investments?.holdingActions ?? [],
      investments?.corrections ?? [],
    ),
    bankSuggestionAcceptances: bankSuggestionAcceptances ?? [],
    billingAccounts: billingAccounts ?? [],
    authorityPermissions: authorityPermissions ?? [],
    authorityTestRuns: authorityTestRuns ?? [],
    auditEvents: auditEvents ?? [],
    reviewComments: reviewComments ?? [],
    filingPreviews: previews ?? [],
    filingSubmissions: submissions ?? [],
    corporateDecisions: corporateLifecycle?.corporateDecisions ?? [],
    corporateDocumentSets: corporateLifecycle?.corporateDocumentSets ?? [],
    corporateDocumentArtifacts: corporateLifecycle?.corporateDocumentArtifacts ?? [],
    corporateDocumentEvents: corporateLifecycle?.corporateDocumentEvents ?? [],
    corporateDecisionFinalizations: corporateLifecycle?.corporateDecisionFinalizations ?? [],
  });

  const archiveBody = JSON.stringify(archive, null, 2);
  const archiveSha256 = createHash("sha256").update(archiveBody, "utf8").digest("hex");
  let archiveProjection;
  try {
    archiveProjection = createSupabaseServiceRoleClient();
  } catch {
    return new Response("Arkivkvitteringstjenesten er utilgjengelig", { status: 503 });
  }
  const { error: archiveReceiptError } = await archiveProjection.rpc(
    "company_archive_complete_export",
    { p_attempt_id: archiveAttemptId, p_archive_sha256: archiveSha256 },
  );
  if (archiveReceiptError) {
    return new Response("Kunne ikke registrere autoritativ arkivkvittering", { status: 409 });
  }

  return new Response(archiveBody, {
    headers: {
      "content-disposition": `attachment; filename="talli-${company.org_number}-${incomeYear}-archive.json"`,
      "content-type": "application/json; charset=utf-8",
    },
  });
}
