import Link from "next/link";

import {
  authorityObligationLabel,
  authorityObligations,
} from "../../lib/authority-permission";
import { deadlineStatusLabel } from "../../lib/deadlines";
import {
  preProductionDirectFilingCopy,
  requiredNonAffiliationCopy,
} from "../../lib/launch-copy";
import { loadWorkspaceData } from "../../lib/workspace-data";

type DashboardProps = {
  searchParams?: Promise<{ error?: string }>;
};

function statusVariant(status?: string, ready?: boolean): string {
  if (ready) {
    return "badge badge--success";
  }
  switch (status) {
    case "ready":
    case "met":
    case "filed":
      return "badge badge--success";
    case "blocked":
    case "overdue":
      return "badge badge--danger";
    case "warning":
    case "due_soon":
      return "badge badge--warning";
    default:
      return "badge badge--draft";
  }
}

export default async function DashboardPage({ searchParams }: DashboardProps) {
  const params = await searchParams;
  const data = await loadWorkspaceData();
  const {
    companies,
    primaryCompanyId,
    primaryIncomeYear,
    primaryReadinessSnapshots,
    deadlines,
    documents,
    transactions,
    unmatchedTransactions,
    actions,
  } = data;

  const primaryCompany =
    companies.find((company) => company.id === primaryCompanyId) ?? companies[0];

  const pendingObligations = primaryCompany
    ? authorityObligations.filter(
        (obligation) =>
          !primaryReadinessSnapshots.find((item) => item.obligation === obligation)?.ready,
      )
    : authorityObligations;

  let nextAction: { kicker: string; title: string; body: string; href: string; cta: string };
  if (!primaryCompany) {
    nextAction = {
      kicker: "Kom i gang",
      title: "Opprett holdingselskapet ditt",
      body: "Hent selskapet fra Brønnøysund og opprett arbeidsflaten på under ett minutt.",
      href: "/workspace",
      cta: "Opprett selskap",
    };
  } else if (pendingObligations.length > 0) {
    nextAction = {
      kicker: `Årsoppgjør ${primaryIncomeYear}`,
      title: "Gjør klar årsoppgjøret",
      body: `${pendingObligations.length} av ${authorityObligations.length} plikter gjenstår før du kan sende inn.`,
      href: "/workspace",
      cta: "Fortsett",
    };
  } else if (unmatchedTransactions.length > 0) {
    nextAction = {
      kicker: "Avstemming",
      title: "Avstem banktransaksjoner",
      body: `${unmatchedTransactions.length} transaksjoner mangler kobling mot regnskapet.`,
      href: "/workspace",
      cta: "Avstem nå",
    };
  } else {
    nextAction = {
      kicker: "Status",
      title: "Alt ser klart ut",
      body: "Forhåndsvis og send inn når du er klar. Talli holder deg i forhåndsvisning til alt er trygt.",
      href: "/workspace",
      cta: "Se innsending",
    };
  }

  const upcomingDeadlines = deadlines.slice(0, 4);

  return (
    <div>
      <div className="pageHead">
        <h1 className="pageTitle">
          {primaryCompany ? primaryCompany.name : "Velkommen til Talli"}
        </h1>
        <p className="pageLede">
          {primaryCompany
            ? `Org.nr ${primaryCompany.org_number} · Inntektsår ${primaryIncomeYear}`
            : "Holding-først årsrapportering for enkle norske AS."}
        </p>
      </div>

      {params?.error ? <p className="bannerError">{params.error}</p> : null}

      <section className="nbaCard" aria-label="Neste steg">
        <span className="nbaKicker">{nextAction.kicker}</span>
        <h2 className="nbaTitle">{nextAction.title}</h2>
        <p className="cardNote">{nextAction.body}</p>
        <div>
          <Link className="btn btn--primary" href={nextAction.href}>
            {nextAction.cta}
          </Link>
        </div>
      </section>

      {primaryCompany ? (
        <>
          <h2 className="sectionTitle">Årsoppgjør {primaryIncomeYear}</h2>
          <div className="statusList">
            {authorityObligations.map((obligation) => {
              const snapshot = primaryReadinessSnapshots.find(
                (item) => item.obligation === obligation,
              );
              return (
                <div className="statusRow" key={obligation}>
                  <span>{authorityObligationLabel(obligation)}</span>
                  <span className={statusVariant(snapshot?.status, snapshot?.ready)}>
                    {snapshot?.ready
                      ? "Klar"
                      : snapshot?.status
                        ? snapshot.status
                        : "Ikke vurdert"}
                  </span>
                </div>
              );
            })}
          </div>

          <h2 className="sectionTitle">Oversikt</h2>
          <div className="cardGrid">
            <div className="card">
              <span className="cardLabel">Dokumenter</span>
              <span className="cardValue">{documents.length}</span>
            </div>
            <div className="card">
              <span className="cardLabel">Transaksjoner</span>
              <span className="cardValue">{transactions.length}</span>
            </div>
            <div className="card">
              <span className="cardLabel">Uavstemte</span>
              <span className="cardValue">{unmatchedTransactions.length}</span>
            </div>
            <div className="card">
              <span className="cardLabel">Holdinghandlinger</span>
              <span className="cardValue">{actions.length}</span>
            </div>
          </div>

          {upcomingDeadlines.length > 0 ? (
            <>
              <h2 className="sectionTitle">Frister</h2>
              <div className="statusList">
                {upcomingDeadlines.map((deadline) => (
                  <div
                    className="statusRow"
                    key={`${deadline.incomeYear}-${deadline.filing}`}
                  >
                    <span>
                      {deadline.filing} {deadline.incomeYear} · {deadline.deadline}
                    </span>
                    <span className={statusVariant(deadline.status)}>
                      {deadlineStatusLabel(deadline.status)}
                    </span>
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </>
      ) : null}

      <h2 className="sectionTitle">Innsending</h2>
      <div className="card">
        <span className="cardLabel">Forhåndsvisning</span>
        <p className="cardNote">{preProductionDirectFilingCopy}</p>
        <p className="cardNote">{requiredNonAffiliationCopy}</p>
      </div>

      <p className="authAlt" style={{ marginTop: "var(--space-6)" }}>
        Trenger du alle verktøyene? <Link href="/workspace">Åpne full arbeidsflate</Link>
      </p>
    </div>
  );
}
