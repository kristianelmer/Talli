import { buildCancellationLifecycle } from "./cancellation";
import {
  buildDeadlineDashboard,
  buildDeadlineReminderPlan,
  defaultReminderPreferences,
} from "./deadlines";
import { reviewChecklistStatus } from "./invitations";
import { estimateAnnualTax } from "./tax-settlement";
import {
  getCurrentUser,
  listAuthorityPermissions,
  listAuthorityTestRuns,
  listAnnualData,
  listBankSuggestionAcceptances,
  listBankTransactions,
  listCorporateDocumentLifecycle,
  listDocumentsForCompanies,
  listFilingPreviews,
  listFilingOverrides,
  listFilingReadinessSnapshots,
  listFilingReviewComments,
  listFilingSubmissions,
  listProductionFilingState,
  listLedgerEntries,
  listNotificationOutbox,
  listOpeningSetups,
  listPeriodLocks,
} from "./supabase/server";
import { listCompanyCancellationLifecycle } from "./company-access-cancellation";
import { listCompanyAccessContexts } from "./company-access-context";
import { listCompanyAccessAdministration } from "./company-access-administration";
import {
  listPresentedAcquisitionLots,
  listPresentedInvestmentPositions,
  listPresentedInvestmentActivity,
  listPresentedInvestmentCorrections,
  effectiveInvestmentActivity,
  summarizeReceivedDividendAnnualImpact,
} from "../../features/investments";
import { getCurrentSessionAccessToken } from "./supabase/auth-session";
import {
  deriveCorporateDecisionFacts,
  readCorporateDecisionReadiness,
  type CorporateDecisionFactsWire,
} from "../../features/corporate-governance";
import {
  loadBillingEntitlement,
  loadBillingSnapshot,
} from "../../features/billing";

/**
 * Loads the full owner-facing workspace dataset (companies, filings, ledger,
 * holding actions, billing, deadlines, derived readiness) for the current user.
 *
 * Extracted verbatim from the original single-page console so the owner routes
 * (#90) share one data source. Pure data assembly — no compliance logic lives
 * here; all filing math stays in holding_core, reached through app/lib/*.
 */
export async function loadWorkspaceData() {
  const user = await getCurrentUser();
  const accessToken = user ? await getCurrentSessionAccessToken() : null;
  const { companies, error } = user ? await listCompanyAccessContexts() : { companies: [], error: null };
  const { documents } = user ? await listDocumentsForCompanies(companies.map((company) => company.id)) : { documents: [] };
  const { annualData } = user ? await listAnnualData(companies.map((company) => company.id)) : { annualData: [] };
  const { error: corporateLifecycleError, ...corporateLifecycle } = user
    ? await listCorporateDocumentLifecycle(companies.map((company) => company.id))
    : {
        corporateDecisions: [],
        corporateDocumentSets: [],
        corporateDocumentArtifacts: [],
        corporateDocumentEvents: [],
        corporateDecisionFinalizations: [],
        corporateDecisionReadiness: [],
        error: null,
      };
  const { setups, shareholders } = user ? await listOpeningSetups(companies.map((company) => company.id)) : { setups: [], shareholders: [] };
  const { previews } = user ? await listFilingPreviews(companies.map((company) => company.id)) : { previews: [] };
  const { submissions } = user ? await listFilingSubmissions(companies.map((company) => company.id)) : { submissions: [] };
  const { error: productionStateError, ...productionState } = user
    ? await listProductionFilingState(companies.map((company) => company.id))
    : {
        productionPilotEntitlements: [],
        filingApprovalSnapshots: [],
        productionFilingSubmissions: [],
        productionFeedbackArtifacts: [],
        error: null,
      };
  const { overrides } = user ? await listFilingOverrides(companies.map((company) => company.id)) : { overrides: [] };
  const { readinessSnapshots } = user ? await listFilingReadinessSnapshots(companies.map((company) => company.id)) : { readinessSnapshots: [] };
  const { comments } = user ? await listFilingReviewComments(companies.map((company) => company.id)) : { comments: [] };
  const { authorityPermissions } = user ? await listAuthorityPermissions(companies.map((company) => company.id)) : { authorityPermissions: [] };
  const { authorityTestRuns } = user ? await listAuthorityTestRuns(companies.map((company) => company.id)) : { authorityTestRuns: [] };
  const primaryCompanyId = companies[0]?.id;
  const { invitations, memberships, error: companyAccessAdministrationError } = user
    ? await listCompanyAccessAdministration(primaryCompanyId)
    : { invitations: [], memberships: [], error: null };
  const { notifications } = user ? await listNotificationOutbox(companies.map((company) => company.id)) : { notifications: [] };
  const { cancellations, error: cancellationLifecycleError } = user
    ? await listCompanyCancellationLifecycle(companies.map((company) => company.id))
    : { cancellations: [], error: null };
  const companyIds = companies.map((company) => company.id);
  const billingSnapshot = accessToken && companyIds.length
    ? await loadBillingSnapshot(accessToken, { companyIds })
    : { accounts: [], paymentEvents: [], pilotEntitlements: [], pricing: [] };
  const billingPricing = billingSnapshot.pricing.map((item) => ({
    plan: item.plan,
    monthly_nok: item.monthlyNok,
    filing_package_nok: item.filingPackageNok,
  }));
  const billingAccounts = billingSnapshot.accounts.map((account) => ({
    company_id: account.companyId,
    pricing_plan: account.pricingPlan,
    monthly_nok: account.monthlyNok,
    filing_package_nok: account.filingPackageNok,
    founder_cohort_number: account.founderCohortNumber,
    subscription_active: account.subscriptionActive,
    filing_package_paid: account.filingPackagePaid,
    supported_case: account.supportedCase,
    refund_eligible: account.refundEligible,
    refund_completed: account.refundCompleted,
    no_charge_reason: account.noChargeReason,
    provider_customer_ref: account.providerCustomerReference,
    subscription_provider_ref: account.subscriptionProviderReference,
    filing_package_payment_ref: account.filingPackagePaymentReference,
    refund_provider_ref: account.refundProviderReference,
    updated_by: account.updatedBy,
    created_at: account.createdAt,
    updated_at: account.updatedAt,
  }));
  const billingPaymentEvents = billingSnapshot.paymentEvents.map((event) => ({
    id: event.eventId,
    company_id: event.companyId,
    provider: event.provider,
    provider_reference: event.providerReference,
    idempotency_key: event.idempotencyKey,
    kind: event.kind as "subscription" | "subscription_cancellation" | "filing_package" | "refund",
    status: event.status as "created" | "succeeded" | "failed" | "refunded" | "canceled",
    amount_nok: event.amountNok,
    income_year: event.incomeYear,
    payload: {},
    created_by: event.createdBy,
    created_at: event.createdAt,
  }));
  const productionPilotEntitlements = billingSnapshot.pilotEntitlements.map((entitlement) => ({
    id: entitlement.entitlementId,
    company_id: entitlement.companyId,
    user_id: entitlement.userId,
    income_year: entitlement.incomeYear,
    obligation: entitlement.obligation as "aksjonaerregisteroppgaven",
    case_profile: entitlement.caseProfile as "rf1086_no_activity_v1",
    status: entitlement.status,
    billing_exempt: entitlement.billingExempt,
    system_user_request_id: entitlement.systemUserRequestId,
    system_user_external_reference: entitlement.systemUserExternalReference,
    starts_at: entitlement.startsAt,
    expires_at: entitlement.expiresAt,
    evidence_reference: entitlement.evidenceReference,
    approved_by: entitlement.approvedBy,
    created_at: entitlement.createdAt,
    updated_at: entitlement.updatedAt,
  }));
  const { transactions } = user ? await listBankTransactions(companies.map((company) => company.id)) : { transactions: [] };
  const { acceptances: bankSuggestionAcceptances } = user
    ? await listBankSuggestionAcceptances(companies.map((company) => company.id))
    : { acceptances: [] };
  const [activityResult, positionsResult, lotsResult, correctionsResult] = accessToken
    ? await Promise.all([
        listPresentedInvestmentActivity(accessToken, companyIds),
        listPresentedInvestmentPositions(accessToken, companyIds),
        listPresentedAcquisitionLots(accessToken, companyIds),
        listPresentedInvestmentCorrections(accessToken, companyIds),
      ])
    : [
        { actions: [], error: null },
        { positions: [], error: null },
        { lots: [], error: null },
        { corrections: [], error: null },
      ];
  const investmentActivityHistory = activityResult.actions;
  const positions = positionsResult.positions;
  const investmentLots = lotsResult.lots;
  const investmentCorrections = correctionsResult.corrections;
  const actions = effectiveInvestmentActivity(
    investmentActivityHistory,
    investmentCorrections,
  );
  const { entries } = user ? await listLedgerEntries(companies.map((company) => company.id)) : { entries: [] };
  const { locks } = user ? await listPeriodLocks(companies.map((company) => company.id)) : { locks: [] };
  const unmatchedTransactions = transactions.filter(
    (transaction) => !transaction.matched_entry_id && !transaction.matched_action_id && !transaction.accepted_warning,
  );
  const adminCostEntries = entries.filter((entry) => entry.entry_type === "admin_cost");
  const taxSettlementEntries = entries.filter((entry) => entry.entry_type === "tax_settlement");
  const taxSettlementActions = taxSettlementEntries;
  const primaryShareholders = shareholders.filter((shareholder) => shareholder.company_id === primaryCompanyId);
  const dividendReceivedActions = actions.filter((action) => action.action_type === "dividend_received");
  const dividendAnnualImpact = summarizeReceivedDividendAnnualImpact(
    dividendReceivedActions,
  );
  const manualJournalEntries = entries.filter((entry) => entry.entry_type === "manual_journal");
  const manualJournalWarnings = manualJournalEntries.flatMap((entry) => entry.risk_flags ?? []);
  const taxEstimate = estimateAnnualTax({ ledgerEntries: entries, holdingActions: actions });
  const incomeYears = Array.from(
    new Set([
      ...companies
        .map((company) => company.admittedAccountingYear)
        .filter((incomeYear): incomeYear is number => incomeYear !== null),
      ...setups.map((setup) => setup.income_year),
      ...previews.map((preview) => preview.income_year),
      ...overrides.map((override) => override.income_year),
      ...submissions.map((submission) => submission.income_year),
      ...transactions.map((transaction) => transaction.income_year),
      ...actions.map((action) => action.income_year),
      ...locks.map((lock) => lock.income_year),
    ]),
  ).sort((a, b) => b - a);
  const primaryIncomeYear = companies.find((company) => company.id === primaryCompanyId)
    ?.admittedAccountingYear ?? incomeYears[0] ?? 2025;
  const primaryBillingAccount = billingAccounts.find((account) => account.company_id === primaryCompanyId);
  const primaryBillingEvents = billingPaymentEvents.filter((event) => event.company_id === primaryCompanyId);
  const primaryReadinessSnapshots = readinessSnapshots.filter(
    (snapshot) => snapshot.company_id === primaryCompanyId && snapshot.income_year === primaryIncomeYear,
  );
  const primaryAnnualData = annualData.find(
    (item) => item.company_id === primaryCompanyId && item.income_year === primaryIncomeYear,
  );
  let primaryCorporateDecisionReadiness = corporateLifecycle.corporateDecisionReadiness.find(
    (item) => item.companyId === primaryCompanyId
      && item.incomeYear === primaryIncomeYear
      && item.decisionKind === "annual_close",
  ) ?? null;
  let corporateReadinessError: string | null = null;
  let primaryCorporateDecisionFacts: CorporateDecisionFactsWire | null = null;
  if (accessToken && primaryCompanyId) {
    try {
      const request = {
        companyId: primaryCompanyId,
        incomeYear: primaryIncomeYear,
        decisionKind: "annual_close" as const,
      };
      if (primaryAnnualData) {
        primaryCorporateDecisionFacts = await deriveCorporateDecisionFacts(
          accessToken,
          request,
        );
        primaryCorporateDecisionReadiness = await readCorporateDecisionReadiness(
          accessToken,
          request,
        );
      } else {
        primaryCorporateDecisionReadiness = await readCorporateDecisionReadiness(
          accessToken,
          request,
        );
      }
    } catch (caught) {
      corporateReadinessError = caught instanceof Error
        ? caught.message
        : "Dokumentstatus kunne ikke leses.";
    }
  }
  const primaryFilingReady = primaryReadinessSnapshots.some(
    (snapshot) => snapshot.obligation === "aksjonaerregisteroppgaven" && snapshot.ready,
  );
  const primaryBillingEntitlements = accessToken && primaryCompanyId
    ? Object.fromEntries(await Promise.all(
        (["aksjonaerregisteroppgaven", "skattemelding", "aarsregnskap"] as const).map(
          async (obligation) => [obligation, await loadBillingEntitlement(accessToken, {
            companyId: primaryCompanyId,
            incomeYear: primaryIncomeYear,
            obligation,
          })] as const,
        ),
      ))
    : {};
  const primaryBillingGate = primaryBillingEntitlements.aksjonaerregisteroppgaven ?? null;
  const primaryAuthorityPermissions = authorityPermissions.filter((permission) => permission.company_id === primaryCompanyId);
  const primaryAuthorityTestRuns = authorityTestRuns.filter((run) => run.company_id === primaryCompanyId);
  const primaryInvitations = invitations.filter((invitation) => invitation.companyId === primaryCompanyId);
  const primaryNotifications = notifications.filter((notification) => notification.company_id === primaryCompanyId);
  const primaryCancellation = cancellations.find(
    (cancellation) => cancellation.company_id === primaryCompanyId
      && cancellation.status !== "deleted"
      && cancellation.status !== "superseded",
  );
  const cancellationLifecycle = buildCancellationLifecycle(primaryCancellation);
  const reviewChecklist = reviewChecklistStatus(
    comments
      .filter((comment) => comment.company_id === primaryCompanyId)
      .map((comment) => ({ severity: comment.severity, acknowledged_by: comment.acknowledged_by })),
  );
  const deadlines = incomeYears.flatMap((incomeYear) => buildDeadlineDashboard({ incomeYear, submissions }));
  const deadlineReminderPlan = primaryCompanyId
    ? buildDeadlineReminderPlan({
        incomeYear: primaryIncomeYear,
        recipientEmail: user?.email ?? "",
        submissions: submissions.filter((submission) => submission.company_id === primaryCompanyId),
        readinessSnapshots: primaryReadinessSnapshots,
        notifications: primaryNotifications,
      })
    : [];
  const deadlineReminderPreferences = defaultReminderPreferences();
  return {
    user,
    error: error ?? corporateLifecycleError ?? corporateReadinessError ?? productionStateError ?? companyAccessAdministrationError ?? cancellationLifecycleError,
    cancellationLifecycleError,
    companies,
    documents,
    annualData,
    ...corporateLifecycle,
    setups,
    shareholders,
    previews,
    submissions,
    ...productionState,
    productionPilotEntitlements,
    overrides,
    readinessSnapshots,
    comments,
    authorityPermissions,
    authorityTestRuns,
    invitations,
    memberships,
    notifications,
    cancellations,
    billingAccounts,
    billingPricing,
    billingPaymentEvents,
    transactions,
    bankSuggestionAcceptances,
    actions,
    investmentActivityHistory,
    positions,
    investmentLots,
    investmentCorrections,
    entries,
    locks,
    primaryCompanyId,
    unmatchedTransactions,
    adminCostEntries,
    taxSettlementEntries,
    taxSettlementActions,
    primaryShareholders,
    dividendReceivedActions,
    dividendAnnualImpact,
    manualJournalEntries,
    manualJournalWarnings,
    taxEstimate,
    incomeYears,
    primaryIncomeYear,
    primaryBillingAccount,
    primaryBillingEvents,
    primaryReadinessSnapshots,
    primaryAnnualData,
    primaryCorporateDecisionReadiness,
    primaryCorporateDecisionFacts,
    primaryFilingReady,
    primaryBillingGate,
    primaryBillingEntitlements,
    primaryAuthorityPermissions,
    primaryAuthorityTestRuns,
    primaryInvitations,
    primaryNotifications,
    primaryCancellation,
    cancellationLifecycle,
    reviewChecklist,
    deadlines,
    deadlineReminderPlan,
    deadlineReminderPreferences,
  };
}

export type WorkspaceData = Awaited<ReturnType<typeof loadWorkspaceData>>;
