import Link from "next/link";

import {
  acceptBankTransactionSuggestion,
  recordAdminCost,
} from "../../actions";
import {
  Banner,
  EmptyState,
  LinkButton,
  StatusBadge,
  SubmitButton,
} from "../../components/ui";
import { ownerCopy } from "../../lib/copy";
import { suggestBankTransaction } from "../../lib/bank-suggestions";
import { loadWorkspaceData } from "../../lib/workspace-data";
import { BankImport } from "./BankImport";

export const dynamic = "force-dynamic";

const t = ownerCopy.transactions;
const RETURN_TO = "/transactions";
const CATEGORY_KEYS = [
  "bank_fee",
  "accounting_fee",
  "software",
  "public_fee",
  "legal_advisory",
  "other_admin_cost",
] as const;

function formatKr(amount: number): string {
  return `${amount.toLocaleString("nb-NO", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} kr`;
}

type TransactionsPageProps = {
  searchParams?: Promise<{ error?: string; posted?: string; imported?: string }>;
};

export default async function TransactionsPage({
  searchParams,
}: TransactionsPageProps) {
  const query = await searchParams;
  const data = await loadWorkspaceData();
  const { companies, primaryCompanyId, primaryIncomeYear } = data;
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

  const companyTransactions = data.transactions.filter(
    (transaction) => transaction.company_id === primaryCompany.id,
  );
  const unmatched = companyTransactions.filter(
    (transaction) =>
      !transaction.matched_entry_id &&
      !transaction.matched_action_id &&
      !transaction.accepted_warning,
  );
  const reconciled = companyTransactions.filter(
    (transaction) =>
      transaction.matched_entry_id ||
      transaction.matched_action_id ||
      transaction.accepted_warning,
  );

  return (
    <div>
      <div className="pageHead">
        <h1 className="pageTitle">{t.hubTitle}</h1>
        <p className="pageLede">{t.hubLede}</p>
        <p className="cardNote">{t.yearLabel(primaryIncomeYear)}</p>
      </div>

      {query?.imported ? <Banner variant="success">{t.imported}</Banner> : null}
      {query?.posted ? <Banner variant="success">{t.posted}</Banner> : null}
      {query?.error ? <Banner variant="danger">{query.error}</Banner> : null}

      <section className="txSection">
        <BankImport
          companyId={primaryCompany.id}
          incomeYear={primaryIncomeYear}
          returnTo={RETURN_TO}
        />
      </section>

      <section className="txSection">
        <div className="txSectionHead">
          <h2 className="sectionTitle">{t.queue.title}</h2>
          {companyTransactions.length > 0 ? (
            <StatusBadge
              variant={unmatched.length ? "warning" : "success"}
              label={
                unmatched.length
                  ? t.queue.countLabel(unmatched.length)
                  : t.reconciledCount(reconciled.length)
              }
              icon={unmatched.length ? "alert" : "check"}
            />
          ) : null}
        </div>

        {companyTransactions.length === 0 ? (
          <EmptyState title={t.emptyTitle}>{t.emptyBody}</EmptyState>
        ) : unmatched.length === 0 ? (
          <EmptyState title={t.allReconciledTitle}>
            {t.allReconciledBody(companyTransactions.length)}
          </EmptyState>
        ) : (
          <>
            <p className="cardNote">{t.queue.intro}</p>
            <div className="txQueue">
              {unmatched.map((transaction) => {
                const amount = Number(transaction.amount);
                const outgoing = amount < 0;
                const suggestion = suggestBankTransaction({
                  text: transaction.text,
                  amount,
                });
                return (
                  <details className="txRow" key={transaction.id}>
                    <summary className="txRowSummary">
                      <span className="txRowMain">
                        <StatusBadge
                          variant={outgoing ? "draft" : "info"}
                          label={outgoing ? t.queue.outgoing : t.queue.incoming}
                        />
                        <span className="txRowText">{transaction.text}</span>
                      </span>
                      <span className="txRowMeta">
                        <span className="txRowDate">{transaction.transaction_date}</span>
                        <span className="txRowAmount">{formatKr(amount)}</span>
                      </span>
                    </summary>

                    <div className="txResolve">
                      {suggestion ? (
                        <div className="txSuggestion">
                          <div className="txSuggestionHead">
                            <StatusBadge variant="info" label={t.queue.suggestionBadge} />
                            <h3 className="txResolveTitle">{t.queue.suggestionTitle}</h3>
                          </div>
                          <p className="fieldHelp">{suggestion.reason}</p>
                          <ul className="txSuggestionLines">
                            {suggestion.lines.map((line) => (
                              <li key={`${suggestion.ruleId}-${line.account}`}>
                                <span>
                                  {line.debit > 0 ? "Debet" : "Kredit"} {line.account} ·{" "}
                                  {line.description}
                                </span>
                                <strong>{formatKr(line.debit || line.credit)}</strong>
                              </li>
                            ))}
                          </ul>
                          <p className="fieldHelp">{t.queue.suggestionHint}</p>
                          <form action={acceptBankTransactionSuggestion}>
                            <input type="hidden" name="returnTo" value={RETURN_TO} />
                            <input
                              type="hidden"
                              name="bankTransactionId"
                              value={transaction.id}
                            />
                            <input type="hidden" name="ruleId" value={suggestion.ruleId} />
                            <input type="hidden" name="ruleVersion" value={suggestion.ruleVersion} />
                            <SubmitButton pendingLabel={t.queue.suggestionPending}>
                              {t.queue.suggestionCta}
                            </SubmitButton>
                          </form>
                        </div>
                      ) : null}

                      {outgoing ? (
                        <div className="txResolveOption">
                          <h3 className="txResolveTitle">{t.queue.resolveCostTitle}</h3>
                          <p className="fieldHelp">{t.queue.resolveCostHint}</p>
                          <form className="txCostForm" action={recordAdminCost}>
                            <input type="hidden" name="returnTo" value={RETURN_TO} />
                            <input type="hidden" name="companyId" value={primaryCompany.id} />
                            <input type="hidden" name="incomeYear" value={transaction.income_year} />
                            <input type="hidden" name="bankTransactionId" value={transaction.id} />
                            <input type="hidden" name="amount" value={Math.abs(amount)} />
                            <input type="hidden" name="paidDate" value={transaction.transaction_date} />
                            <label className="field">
                              <span className="fieldLabel">{t.queue.categoryLabel}</span>
                              <select name="category" defaultValue="bank_fee">
                                {CATEGORY_KEYS.map((key) => (
                                  <option key={key} value={key}>
                                    {t.queue.categories[key]}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label className="field">
                              <span className="fieldLabel">{t.queue.payeeLabel}</span>
                              <input
                                name="payee"
                                defaultValue={transaction.text}
                                required
                              />
                            </label>
                            <SubmitButton pendingLabel={t.queue.bookPending}>
                              {t.queue.bookCta}
                            </SubmitButton>
                          </form>
                        </div>
                      ) : null}

                      <div className="txResolveOption">
                        <h3 className="txResolveTitle">{t.queue.resolveActionTitle}</h3>
                        <p className="fieldHelp">{t.queue.resolveActionHint}</p>
                        <LinkButton variant="secondary" href="/actions">
                          {t.queue.resolveActionCta}
                        </LinkButton>
                      </div>

                      <div className="txResolveOption">
                        <h3 className="txResolveTitle">{t.queue.resolveManualTitle}</h3>
                        <p className="fieldHelp">{t.queue.resolveManualHint}</p>
                        <LinkButton variant="ghost" href="/workspace">
                          {t.queue.resolveManualCta}
                        </LinkButton>
                      </div>
                    </div>
                  </details>
                );
              })}
            </div>
          </>
        )}

        {reconciled.length > 0 && unmatched.length > 0 ? (
          <div className="txReconciled">
            <h3 className="sectionTitle">{t.reconciledTitle}</h3>
            <ul className="recentList">
              {reconciled
                .slice()
                .sort((left, right) =>
                  right.transaction_date.localeCompare(left.transaction_date),
                )
                .slice(0, 5)
                .map((transaction) => (
                  <li key={transaction.id} className="recentItem">
                    <span className="recentType">{transaction.text}</span>
                    <span className="recentMeta">
                      {transaction.transaction_date} · {formatKr(Number(transaction.amount))}
                    </span>
                  </li>
                ))}
            </ul>
          </div>
        ) : null}
      </section>
    </div>
  );
}
