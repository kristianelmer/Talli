import Link from "next/link";

import { Banner, EmptyState, LinkButton } from "../../components/ui";
import { ownerCopy } from "../../lib/copy";
import { loadWorkspaceData } from "../../lib/workspace-data";

const ACTION_SLUGS = [
  "share-purchase",
  "share-sale",
  "dividend-received",
  "owner-dividend",
  "shareholder-loan",
  "tax-settlement",
] as const;

type ActionsHubProps = {
  searchParams?: Promise<{ error?: string; posted?: string }>;
};

export default async function ActionsHubPage({ searchParams }: ActionsHubProps) {
  const params = await searchParams;
  const data = await loadWorkspaceData();
  const { companies, primaryCompanyId, actions } = data;

  const a = ownerCopy.actions;
  const primaryCompany =
    companies.find((company) => company.id === primaryCompanyId) ?? companies[0];

  if (!primaryCompany) {
    return (
      <div>
        <div className="pageHead">
          <h1 className="pageTitle">{a.hubTitle}</h1>
          <p className="pageLede">{a.hubIntro}</p>
        </div>
        <EmptyState
          title={a.needsCompanyTitle}
          action={
            <LinkButton variant="primary" href="/onboarding">
              {a.needsCompanyCta}
            </LinkButton>
          }
        >
          {a.needsCompanyBody}
        </EmptyState>
      </div>
    );
  }

  const recent = actions
    .filter((action) => action.company_id === primaryCompany.id)
    .slice()
    .sort((left, right) => right.action_date.localeCompare(left.action_date))
    .slice(0, 8);

  return (
    <div>
      <div className="pageHead">
        <h1 className="pageTitle">{a.hubTitle}</h1>
        <p className="pageLede">{a.hubIntro}</p>
      </div>

      {params?.posted ? <Banner variant="success">{a.posted}</Banner> : null}
      {params?.error ? <Banner variant="danger">{params.error}</Banner> : null}

      <h2 className="sectionTitle">{a.chooseTitle}</h2>
      <div className="actionGrid">
        {ACTION_SLUGS.map((slug) => {
          const card = a.cards[slug];
          return (
            <Link key={slug} className="actionCard" href={`/actions/${slug}`}>
              <span className="actionCardTitle">{card.title}</span>
              <span className="actionCardBody">{card.body}</span>
            </Link>
          );
        })}
      </div>

      <h2 className="sectionTitle">{a.recentTitle}</h2>
      {recent.length === 0 ? (
        <p className="cardNote">{a.recentEmpty}</p>
      ) : (
        <ul className="recentList">
          {recent.map((action) => (
            <li key={action.id} className="recentItem">
              <span className="recentType">
                {a.typeLabels[action.action_type]}
              </span>
              <span className="recentMeta">{action.action_date}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
