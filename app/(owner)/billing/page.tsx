import { Banner, EmptyState, LinkButton, StatusBadge } from "../../components/ui";
import { billingPricing, type BillingPlan } from "../../lib/billing";
import { ownerCopy } from "../../lib/copy";
import { loadWorkspaceData } from "../../lib/workspace-data";

export const dynamic = "force-dynamic";

const t = ownerCopy.billing;
const PLAN_ORDER: BillingPlan[] = ["founder", "standard"];

export default async function BillingPage() {
  const data = await loadWorkspaceData();
  const { companies, primaryCompanyId } = data;
  const primaryCompany =
    companies.find((company) => company.id === primaryCompanyId) ?? companies[0];

  if (!primaryCompany) {
    return (
      <div>
        <div className="pageHead">
          <h1 className="pageTitle">{t.hubTitle}</h1>
          <p className="pageLede">{t.hubLede}</p>
        </div>
        <EmptyState
          title={t.needsCompanyTitle}
          action={
            <LinkButton variant="primary" href="/onboarding">
              {t.needsCompanyCta}
            </LinkButton>
          }
        >
          {t.needsCompanyBody}
        </EmptyState>
      </div>
    );
  }

  const account = data.primaryBillingAccount;
  const activePlan = account?.pricing_plan;

  return (
    <div>
      <div className="pageHead">
        <h1 className="pageTitle">{t.hubTitle}</h1>
        <p className="pageLede">{t.hubLede}</p>
      </div>

      <div className="billingPlaceholder">
        <strong className="billingPlaceholderTitle">{t.placeholderTitle}</strong>
        <p>{t.placeholderBody}</p>
      </div>

      {account?.refund_completed ? (
        <Banner variant="success">{t.refund.completedBody}</Banner>
      ) : account?.refund_eligible ? (
        <Banner variant="info">{t.refund.eligibleBody}</Banner>
      ) : null}
      {account && !account.supported_case ? (
        <Banner variant="warning">{account.no_charge_reason || t.unsupportedBody}</Banner>
      ) : null}

      {!account ? (
        <EmptyState title={t.noAccountTitle}>{t.noAccountBody}</EmptyState>
      ) : null}

      <section className="billingSection">
        <h2 className="sectionTitle">{t.planTitle}</h2>
        <div className="planGrid">
          {PLAN_ORDER.map((plan) => {
            const pricing = billingPricing(plan);
            const isCurrent = activePlan === plan;
            return (
              <div
                className={isCurrent ? "planCard planCard--current" : "planCard"}
                key={plan}
              >
                <div className="planCardHead">
                  <span className="planName">{t.plans[plan]}</span>
                  {isCurrent ? (
                    <StatusBadge variant="info" label={t.currentPlanLabel} />
                  ) : null}
                </div>
                <p className="planPrice">{t.perMonth(pricing.monthly_nok)}</p>
                <p className="planPackage">{t.packagePrice(pricing.filing_package_nok)}</p>
                {isCurrent && plan === "founder" && account?.founder_cohort_number ? (
                  <p className="cardNote">{t.founderCohort(account.founder_cohort_number)}</p>
                ) : null}
              </div>
            );
          })}
        </div>
      </section>

      {account ? (
        <section className="billingSection">
          <h2 className="sectionTitle">{t.statusTitle}</h2>
          <div className="billingStatusGrid">
            <div className="billingStatusCard">
              <div className="billingStatusHead">
                <span className="billingStatusTitle">{t.subscription.title}</span>
                <StatusBadge
                  variant={account.subscription_active ? "success" : "info"}
                  label={
                    account.subscription_active
                      ? t.subscription.active
                      : t.subscription.inactive
                  }
                  icon={account.subscription_active ? "check" : undefined}
                />
              </div>
              <p className="fieldHelp">
                {account.subscription_active
                  ? t.subscription.activeHint
                  : t.subscription.inactiveHint}
              </p>
            </div>
            <div className="billingStatusCard">
              <div className="billingStatusHead">
                <span className="billingStatusTitle">{t.package.title}</span>
                <StatusBadge
                  variant={account.filing_package_paid ? "success" : "info"}
                  label={
                    account.filing_package_paid ? t.package.paid : t.package.unpaid
                  }
                  icon={account.filing_package_paid ? "check" : undefined}
                />
              </div>
              <p className="fieldHelp">
                {account.filing_package_paid
                  ? t.package.paidHint
                  : t.package.unpaidHint}
              </p>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
