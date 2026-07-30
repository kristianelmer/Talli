import { Banner, EmptyState, LinkButton, StatusBadge } from "../../components/ui";
import { ownerCopy } from "../../lib/copy";
import {
  createSupabaseServerClient,
  getCurrentUser,
  listCompanyWorkspaces,
} from "../../lib/supabase/server";
import { SystemUserRequestControls } from "./SystemUserRequestControls";
import {
  loadSystemUserRequestPresentations,
  selectReadableCompany,
  systemUserCallbackNotice,
  type SystemUserRequestPresentation,
} from "./_presentation";

export const dynamic = "force-dynamic";

type ConnectionsPageProps = {
  searchParams?: Promise<{
    company?: string | string[];
    systembruker?: string | string[];
  }>;
};

export default async function ConnectionsPage({ searchParams }: ConnectionsPageProps) {
  const query = await searchParams;
  const c = ownerCopy.connections;
  const user = await getCurrentUser();
  const { companies, error: companiesError } = user
    ? await listCompanyWorkspaces(user.id)
    : { companies: [], error: "Innlogging kreves." };
  const selectedCompany = selectReadableCompany(query?.company, companies);
  const notice = systemUserCallbackNotice(query?.systembruker, c);
  const header = (
    <div className="pageHead">
      <h1 className="pageTitle">{c.title}</h1>
      <p className="pageLede">{c.intro}</p>
    </div>
  );
  const noticeRegion = (
    <div aria-live="polite">
      {notice ? <Banner variant="info">{notice}</Banner> : null}
    </div>
  );

  if (!selectedCompany) {
    return (
      <div>
        {header}
        {noticeRegion}
        {companiesError ? (
          <Banner variant="danger" title={c.loadErrorTitle}>
            {c.loadErrorBody}
          </Banner>
        ) : (
          <EmptyState
            title={c.noCompaniesTitle}
            action={(
              <LinkButton variant="primary" href="/onboarding">
                {c.noCompaniesCta}
              </LinkButton>
            )}
          >
            {c.noCompaniesBody}
          </EmptyState>
        )}
      </div>
    );
  }

  let requestLoadFailed = false;
  let requests: SystemUserRequestPresentation[] = [];
  try {
    const supabase = await createSupabaseServerClient();
    requests = await loadSystemUserRequestPresentations(
      supabase,
      companies.map((company) => company.id),
      c,
    );
  } catch {
    requestLoadFailed = true;
  }
  const request = requests.find((candidate) => candidate.companyId === selectedCompany.id) ?? null;

  return (
    <div>
      {header}
      {noticeRegion}

      {companies.length > 1 ? (
        <section className="filingStep" aria-labelledby="connections-company-heading">
          <div className="filingStepHead">
            <h2 className="filingStepTitle" id="connections-company-heading">
              {c.companyHeading}
            </h2>
          </div>
          <nav className="statusList" aria-label={c.companyHeading}>
            {companies.map((company) => (
              <LinkButton
                block
                key={company.id}
                variant={company.id === selectedCompany.id ? "primary" : "secondary"}
                href={`/connections?company=${company.id}`}
                aria-current={company.id === selectedCompany.id ? "page" : undefined}
              >
                {company.name}
              </LinkButton>
            ))}
          </nav>
        </section>
      ) : null}

      <section className="filingStep" aria-labelledby="connections-status-heading">
        <div className="filingStepHead">
          <h2 className="filingStepTitle" id="connections-status-heading">
            {c.statusHeading(selectedCompany.name)}
          </h2>
          {request ? (
            <StatusBadge
              variant={request.badgeVariant}
              label={request.title}
              icon={request.badgeIcon}
            />
          ) : null}
        </div>
        <div className="filingStepBody">
          {requestLoadFailed ? (
            <Banner variant="danger" title={c.loadErrorTitle}>
              {c.loadErrorBody}
            </Banner>
          ) : request ? (
            <>
              <p className="cardNote">{request.body}</p>
              <SystemUserRequestControls companyId={selectedCompany.id} request={request} />
            </>
          ) : (
            <>
              <p className="cardNote">{c.noRequestTitle}</p>
              <p className="cardNote">{c.noRequestBody}</p>
              <SystemUserRequestControls companyId={selectedCompany.id} request={null} />
            </>
          )}
        </div>
      </section>
    </div>
  );
}
