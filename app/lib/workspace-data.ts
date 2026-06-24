import { productionBillingGate } from "./billing";
import { buildCancellationLifecycle } from "./cancellation";
import {
  buildDeadlineDashboard,
  buildDeadlineReminderPlan,
  defaultReminderPreferences,
} from "./deadlines";
import { summarizeDividendReceivedAnnualImpact } from "./dividend-received";
import { reviewChecklistStatus } from "./invitations";
import { estimateAnnualTax } from "./tax-settlement";
import {
  getCurrentUser,
  listAuthorityPermissions,
  listAuthorityTestRuns,
  listAnnualData,
  listBankTransactions,
  listBillingAccounts,
  listBillingPaymentEvents,
  listCompanyCancellations,
  listCompanyWorkspaces,
  listDocumentsForCompanies,
  listFilingPreviews,
  listFilingOverrides,
  listFilingReadinessSnapshots,
  listFilingReviewComments,
  listFilingSubmissions,
  listHoldingActions,
  listInvestmentPositions,
  listLedgerEntries,
  listNotificationOutbox,
  listOpeningSetups,
  listPeriodLocks,
  listWorkspaceInvitations,
} from "./supabase/server";

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
  const { companies, error } = user ? await listCompanyWorkspaces() : { companies: [], error: null };
  const { documents } = user ? await listDocumentsForCompanies(companies.map((company) => company.id)) : { documents: [] };
  const { annualData } = user ? await listAnnualData(companies.map((company) => company.id)) : { annualData: [] };
  const { setups, shareholders } = user ? await listOpeningSetups(companies.map((company) => company.id)) : { setups: [], shareholders: [] };
  const { previews } = user ? await listFilingPreviews(companies.map((company) => company.id)) : { previews: [] };
  const { submissions } = user ? await listFilingSubmissions(companies.map((company) => company.id)) : { submissions: [] };
  const { overrides } = user ? await listFilingOverrides(companies.map((company) => company.id)) : { overrides: [] };
  const { readinessSnapshots } = user ? await listFilingReadinessSnapshots(companies.map((company) => company.id)) : { readinessSnapshots: [] };
  const { comments } = user ? await listFilingReviewComments(companies.map((company) => company.id)) : { comments: [] };
  const { authorityPermissions } = user ? await listAuthorityPermissions(companies.map((company) => company.id)) : { authorityPermissions: [] };
  const { authorityTestRuns } = user ? await listAuthorityTestRuns(companies.map((company) => company.id)) : { authorityTestRuns: [] };
  const { invitations } = user ? await listWorkspaceInvitations(companies.map((company) => company.id)) : { invitations: [] };
  const { notifications } = user ? await listNotificationOutbox(companies.map((company) => company.id)) : { notifications: [] };
  const { cancellations } = user ? await listCompanyCancellations(companies.map((company) => company.id)) : { cancellations: [] };
  const { billingAccounts } = user ? await listBillingAccounts(companies.map((company) => company.id)) : { billingAccounts: [] };
  const { billingPaymentEvents } = user ? await listBillingPaymentEvents(companies.map((company) => company.id)) : { billingPaymentEvents: [] };
  const { transactions } = user ? await listBankTransactions(companies.map((company) => company.id)) : { transactions: [] };
  const { actions } = user ? await listHoldingActions(companies.map((company) => company.id)) : { actions: [] };
  const { positions } = user ? await listInvestmentPositions(companies.map((company) => company.id)) : { positions: [] };
  const { entries } = user ? await listLedgerEntries(companies.map((company) => company.id)) : { entries: [] };
  const { locks } = user ? await listPeriodLocks(companies.map((company) => company.id)) : { locks: [] };
  const primaryCompanyId = companies[0]?.id;
  const unmatchedTransactions = transactions.filter(
    (transaction) => !transaction.matched_entry_id && !transaction.matched_action_id && !transaction.accepted_warning,
  );
  const adminCostEntries = entries.filter((entry) => entry.entry_type === "admin_cost");
  const taxSettlementEntries = entries.filter((entry) => entry.entry_type === "tax_settlement");
  const taxSettlementActions = actions.filter((action) => action.action_type === "tax_settlement");
  const primaryShareholders = shareholders.filter((shareholder) => shareholder.company_id === primaryCompanyId);
  const dividendReceivedActions = actions.filter((action) => action.action_type === "dividend_received");
  const dividendAnnualImpact = summarizeDividendReceivedAnnualImpact(
    dividendReceivedActions.map((action) => ({
      action_type: action.action_type,
      payload: action.payload as { gross_amount?: number; taxable_add_back?: number },
    })),
  );
  const manualJournalEntries = entries.filter((entry) => entry.entry_type === "manual_journal");
  const manualJournalWarnings = manualJournalEntries.flatMap((entry) => entry.risk_flags ?? []);
  const taxEstimate = estimateAnnualTax({ ledgerEntries: entries, holdingActions: actions });
  const incomeYears = Array.from(
    new Set([
      ...setups.map((setup) => setup.income_year),
      ...previews.map((preview) => preview.income_year),
      ...overrides.map((override) => override.income_year),
      ...submissions.map((submission) => submission.income_year),
      ...transactions.map((transaction) => transaction.income_year),
      ...actions.map((action) => action.income_year),
      ...locks.map((lock) => lock.income_year),
    ]),
  ).sort((a, b) => b - a);
  const primaryIncomeYear = incomeYears[0] ?? 2025;
  const primaryBillingAccount = billingAccounts.find((account) => account.company_id === primaryCompanyId);
  const primaryBillingEvents = billingPaymentEvents.filter((event) => event.company_id === primaryCompanyId);
  const primaryReadinessSnapshots = readinessSnapshots.filter(
    (snapshot) => snapshot.company_id === primaryCompanyId && snapshot.income_year === primaryIncomeYear,
  );
  const primaryAnnualData = annualData.find(
    (item) => item.company_id === primaryCompanyId && item.income_year === primaryIncomeYear,
  );
  const primaryFilingReady = primaryReadinessSnapshots.some(
    (snapshot) => snapshot.obligation === "aksjonaerregisteroppgaven" && snapshot.ready,
  );
  const primaryBillingGate = primaryBillingAccount ? productionBillingGate(primaryBillingAccount, primaryFilingReady) : null;
  const primaryAuthorityPermissions = authorityPermissions.filter((permission) => permission.company_id === primaryCompanyId);
  const primaryAuthorityTestRuns = authorityTestRuns.filter((run) => run.company_id === primaryCompanyId);
  const primaryInvitations = invitations.filter((invitation) => invitation.company_id === primaryCompanyId);
  const primaryNotifications = notifications.filter((notification) => notification.company_id === primaryCompanyId);
  const primaryCancellation = cancellations.find((cancellation) => cancellation.company_id === primaryCompanyId);
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
    error,
    companies,
    documents,
    annualData,
    setups,
    shareholders,
    previews,
    submissions,
    overrides,
    readinessSnapshots,
    comments,
    authorityPermissions,
    authorityTestRuns,
    invitations,
    notifications,
    cancellations,
    billingAccounts,
    billingPaymentEvents,
    transactions,
    actions,
    positions,
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
    primaryFilingReady,
    primaryBillingGate,
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
