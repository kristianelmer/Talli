import {
  Banner,
  EmptyState,
  LinkButton,
  StatusBadge,
  buttonClass,
} from "../../components/ui";
import { ownerCopy } from "../../lib/copy";
import { loadWorkspaceData } from "../../lib/workspace-data";
import { DocumentUpload } from "./DocumentUpload";
import { DocumentRemovalButton } from "./DocumentRemovalButton";

export const dynamic = "force-dynamic";

const t = ownerCopy.documents;
const RETURN_TO = "/documents";

function typeLabel(documentType: string): string {
  return t.upload.types[documentType] ?? t.list.genericType;
}

type DocStatus = {
  variant: "success" | "warning" | "info";
  label: string;
  icon?: "check" | "alert";
  downloadable: boolean;
};

function classifyStatus(status: string): DocStatus {
  if (status.startsWith("missing")) {
    return { variant: "warning", label: t.list.statusMissing, icon: "alert", downloadable: false };
  }
  if (status === "not_required") {
    return { variant: "info", label: t.list.statusNotRequired, downloadable: false };
  }
  return { variant: "success", label: t.list.statusAttached, icon: "check", downloadable: true };
}

type DocumentsPageProps = {
  searchParams?: Promise<{ error?: string; uploaded?: string; removed?: string }>;
};

export default async function DocumentsPage({ searchParams }: DocumentsPageProps) {
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

  const companyDocuments = data.documents.filter(
    (document) => document.company_id === primaryCompany.id,
  );
  const archiveReady = data.submissions.some(
    (submission) =>
      submission.company_id === primaryCompany.id &&
      submission.income_year === primaryIncomeYear,
  );

  return (
    <div>
      <div className="pageHead">
        <h1 className="pageTitle">{t.hubTitle}</h1>
        <p className="pageLede">{t.hubLede}</p>
        <p className="cardNote">{t.yearLabel(primaryIncomeYear)}</p>
      </div>

      {query?.uploaded ? <Banner variant="success">{t.uploaded}</Banner> : null}
      {query?.removed ? <Banner variant="success">{t.removed}</Banner> : null}
      {query?.error ? <Banner variant="danger">{query.error}</Banner> : null}

      <section className="docSection" id="last-opp">
        <h2 className="sectionTitle">{t.upload.title}</h2>
        <DocumentUpload
          companyId={primaryCompany.id}
          incomeYear={primaryIncomeYear}
          returnTo={RETURN_TO}
        />
      </section>

      <section className="docSection">
        <h2 className="sectionTitle">{t.list.title}</h2>
        {companyDocuments.length === 0 ? (
          <EmptyState title={t.emptyTitle}>{t.emptyBody}</EmptyState>
        ) : (
          <>
            <p className="cardNote">{t.list.intro}</p>
            <div className="docList">
              {companyDocuments.map((document) => {
                const status = classifyStatus(document.status);
                return (
                  <div className="docRow" key={document.id}>
                    <div className="docRowMain">
                      <span className="docRowName">{document.name}</span>
                      <span className="docRowType">{typeLabel(document.document_type)}</span>
                    </div>
                    <div className="docRowSide">
                      <StatusBadge variant={status.variant} label={status.label} icon={status.icon} />
                      {status.downloadable ? (
                        <>
                          <a className="docDownload" href={`/documents/${document.id}/download`}>
                            {t.list.download}
                          </a>
                          <DocumentRemovalButton documentId={document.id} />
                        </>
                      ) : document.status.startsWith("missing") ? (
                        <a className="docMissingLink" href="#last-opp">
                          {t.list.missingCta}
                        </a>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="fieldHelp">{t.list.secureNote}</p>
          </>
        )}
      </section>

      <section className="docSection">
        <div className="docArchive">
          <h2 className="sectionTitle">{t.archive.title}</h2>
          {archiveReady ? (
            <>
              <p className="cardNote">{t.archive.body}</p>
              <a
                className={buttonClass("primary")}
                href={`/archive/${primaryCompany.id}/${primaryIncomeYear}/download`}
              >
                {t.archive.cta}
              </a>
              <p className="fieldHelp">{t.archive.secureNote}</p>
            </>
          ) : (
            <EmptyState
              title={t.archive.notReadyTitle}
              action={
                <LinkButton variant="secondary" href="/filing">
                  {t.archive.notReadyCta}
                </LinkButton>
              }
            >
              {t.archive.notReadyBody}
            </EmptyState>
          )}
        </div>
      </section>
    </div>
  );
}
