import { randomUUID } from "node:crypto";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { TalliApiError } from "@talli/talli-api-client";
import {
  companyTestHistoryHref, companyTestHistoryPage, companyTestHistoryPageNumber,
  companyTestHistoryRecordFields, isCompanyTestHistoryCompany, loadCompanyTestHistory,
} from "../../../../features/shareholder-register-filing";
import { loadCompanyTestHistoryMember } from "./history-access";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Testhistorikk", robots: { index: false, follow: false } };

type Props = {
  params: Promise<{ companyId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function CompanyTestHistoryPage({ params, searchParams }: Props) {
  const [{ companyId }, query] = await Promise.all([params, searchParams]);
  const page = companyTestHistoryPageNumber(query.page);
  if (!isCompanyTestHistoryCompany(companyId) || page === null || Object.keys(query).some(key => key !== "page")) notFound();
  const href = companyTestHistoryHref(companyId, page);
  const requestId = randomUUID();
  let history;
  let companyName;
  try {
    const { accessToken, company } = await loadCompanyTestHistoryMember(companyId, requestId);
    companyName = company.name;
    history = companyTestHistoryPage(await loadCompanyTestHistory(accessToken, companyId, requestId), page);
  } catch (error) {
    if (error instanceof TalliApiError && error.status === 401) redirect(`/login?next=${encodeURIComponent(href)}`);
    const denied = error instanceof TalliApiError && [403, 404].includes(error.status);
    return <main className="appMain">
      <h1 className="pageTitle">Testhistorikk</h1>
      <p role="alert">{denied
        ? "Testhistorikken er ikke tilgjengelig for denne innloggingen."
        : "Testhistorikken er midlertidig utilgjengelig. Prøv igjen senere."}</p>
      {!denied ? <a className="btn btn--secondary" href={href}>Prøv igjen</a> : null}
    </main>;
  }
  return <main className="appMain">
    <div className="pageHead">
      <h1 className="pageTitle">Testhistorikk for {companyName}</h1>
      <p className="pageLede">Registrerte tester for aksjonærregisteroppgaven, på tvers av år og registrerende personer.</p>
      <p className="cardNote">Dette er testhistorikk. Selskapets fullstendige årsarkiv lastes ned separat.</p>
    </div>
    {history.kind === "unavailable" ? <>
      <p role="alert">Historikken kunne ikke bekreftes. Antall registrerte tester er ukjent.</p>
      <a className="btn btn--secondary" href={href}>Prøv igjen</a>
    </>
      : history.kind === "out_of_range" ? <section className="card">
        <p>Denne siden finnes ikke i historikken som ble hentet. Antall registrerte tester: {history.recordCount}.</p>
        <Link href={companyTestHistoryHref(companyId)}>Gå til første side</Link>
      </section> : <>
        <section className="card" aria-label="Hentet testhistorikk">
          <p>Registrerte tester: {history.recordCount}</p>
          <p>Observasjonstid: <code>{history.observedAt}</code></p>
          <p>Kontrollsum for denne observasjonen: <code style={{ overflowWrap: "anywhere" }}>{history.recordsSha256}</code></p>
          <a className="btn btn--secondary" href={`${companyTestHistoryHref(companyId)}/download`}>Last ned hele testhistorikken</a>
          <p className="cardNote">Nedlasting krever fersk identitetsbekreftelse. En avbrutt fil må lastes ned på nytt og kontrolleres før den brukes som arkiv.</p>
        </section>
        {history.recordCount === 0 ? <p>Ingen tester er registrert i denne observasjonen.</p> : <>
          <p>Viser post {history.firstRecord}–{history.lastRecord} av {history.recordCount}. Hver side viser historikken på tidspunktet den hentes.</p>
          <section aria-label="Registrerte tester">
            {history.records.map(record => <details className="card" key={record.id} style={{ minWidth: 0 }}>
              <summary style={{ minWidth: 0, overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}>{record.test_reference} — {record.status}</summary>
              <dl>{companyTestHistoryRecordFields.map(([key, label]) => <div key={key}>
                <dt>{label}</dt>
                <dd><code style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{record[key] === null ? "Ikke oppgitt" : record[key]}</code></dd>
              </div>)}</dl>
            </details>)}
          </section>
          <nav aria-label="Sider i testhistorikken" style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", flexWrap: "wrap", marginBlock: "var(--space-4)" }}>
            {page > 1 ? <Link className="btn btn--secondary" href={companyTestHistoryHref(companyId, page - 1)}>Forrige side</Link> : null}
            <span aria-current="page">Side {page} av {history.pageCount}</span>
            {page < history.pageCount ? <Link className="btn btn--secondary" href={companyTestHistoryHref(companyId, page + 1)}>Neste side</Link> : null}
          </nav>
        </>}
      </>}
  </main>;
}
