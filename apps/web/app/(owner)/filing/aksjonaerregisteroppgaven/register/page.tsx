import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { listDocuments } from "../../../../../features/documents";
import { loadRf1086RegisterObservations, rf1086RegisterErrorMessage } from "../../../../../features/shareholder-register-filing";
import { Banner } from "../../../../components/ui";
import { loadAcceptedMembershipCompany } from "../../../../lib/company-access-context";
import { getCurrentSessionAccessToken } from "../../../../lib/supabase/auth-session";
import { RegisterEditor } from "./RegisterEditor";
import { registerKinds } from "./model";
export const dynamic = "force-dynamic";
type Props = { searchParams: Promise<{ companyId?: string | string[]; incomeYear?: string | string[]; observationId?: string | string[] }> };
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
export default async function RegisterPage({ searchParams }: Props) {
  const query = await searchParams;
  if (!uuid(query.companyId) || typeof query.incomeYear !== "string" || !/^\d{4}$/.test(query.incomeYear)
      || (query.observationId !== undefined && !uuid(query.observationId))) notFound();
  const companyId = query.companyId, incomeYear = Number(query.incomeYear);
  if (incomeYear < 2000 || incomeYear > 2100) notFound();
  const token = await getCurrentSessionAccessToken();
  if (!token) redirect("/login");
  const company = await loadAcceptedMembershipCompany(companyId);
  const scope = new URLSearchParams({ companyId, incomeYear: String(incomeYear) }).toString();
  const base = `/filing/aksjonaerregisteroppgaven/register?${scope}`;
  const header = <div className="pageHead"><Link className="backLink" href={`/filing/aksjonaerregisteroppgaven/source?${scope}`}>← Årsgrunnlaget</Link>
    <h1 className="pageTitle">Aksjeeierbok ved kapitalendring</h1><p className="pageLede">Registrer aksjer og eiere før og etter endringen fra uavhengige originaldokumenter.</p>
    <p className="cardNote">{company?.name} · {incomeYear}</p></div>;
  if (!company || company.id !== companyId || company.role !== "owner" || company.entity_type !== "AS"
      || !company.identity_confirmed_at || !company.identity_locked_at) return <div>{header}<Banner variant="danger">Kontroller eiertilgangen og de bekreftede selskapsopplysningene.</Banner></div>;
  let records, documents;
  try {
    [records, documents] = await Promise.all([loadRf1086RegisterObservations(token, companyId, incomeYear), listDocuments(token, companyId)]);
    if (documents.documents.some(d => d.companyId !== companyId)) throw new Error("Document scope mismatch");
  } catch (error) { return <div>{header}<Banner variant="danger">{rf1086RegisterErrorMessage(error)}</Banner></div>; }
  const current = query.observationId ? records.observations.find(row => row.receipt.observationId === query.observationId) : null;
  if (query.observationId && !current) notFound();
  return <div className="wizardForm">{header}
    <section className="dataPanel"><h2>Lagrede registergrunnlag</h2>
      {records.observations.length ? <ul>{records.observations.map(row => <li key={row.receipt.observationId}>
        <Link href={`${base}&observationId=${row.receipt.observationId}`}>{registerKinds[row.draft.eventKind]} · {row.draft.effectiveAt.replace("T", " ")} · versjon {row.receipt.version} · {row.isCurrent ? "gjeldende" : "erstattet"}</Link>
      </li>)}</ul> : <p>Ingen registergrunnlag er lagret for dette året.</p>}
      {current ? <Link className="btn btn--secondary" href={base}>Registrer en annen kapitalendring</Link> : null}
    </section>
    <RegisterEditor key={`${companyId}:${incomeYear}:${current?.receipt.observationId ?? "new"}`} companyId={companyId} incomeYear={incomeYear} current={current ?? null}
      documentOptions={documents.documents.filter(d => d.removedAt === null && d.status === "attached" && d.linkedTo === "workspace"
        && ["corporate_document", "accounting_document"].includes(d.documentType)).map(d => ({ id: d.id, name: d.name, incomeYear: d.incomeYear }))} />
  </div>;
}
