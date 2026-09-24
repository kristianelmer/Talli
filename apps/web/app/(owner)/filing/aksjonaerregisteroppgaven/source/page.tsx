import { randomUUID } from "node:crypto";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { listDocuments } from "../../../../../features/documents";
import {
  loadRf1086CurrentYearSource,
  loadRf1086SourceIntakeBasis,
  rf1086SourceErrorMessage,
} from "../../../../../features/shareholder-register-filing";
import { Banner } from "../../../../components/ui";
import { loadAcceptedMembershipCompany } from "../../../../lib/company-access-context";
import { getCurrentSessionAccessToken } from "../../../../lib/supabase/auth-session";
import { SourceEditor } from "./SourceEditor";

export const dynamic = "force-dynamic";

type Props = {
  searchParams: Promise<{ companyId?: string | string[]; incomeYear?: string | string[] }>;
};

export default async function Rf1086SourcePage({ searchParams }: Props) {
  const query = await searchParams;
  if (typeof query.companyId !== "string"
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(query.companyId)
      || typeof query.incomeYear !== "string" || !/^\d{4}$/.test(query.incomeYear)) notFound();
  const companyId = query.companyId;
  const incomeYear = Number(query.incomeYear);
  if (incomeYear < 2000 || incomeYear > 2100) notFound();
  const token = await getCurrentSessionAccessToken();
  if (!token) redirect("/login");
  const company = await loadAcceptedMembershipCompany(companyId);
  const header = <div className="pageHead">
    <Link className="backLink" href="/filing/aksjonaerregisteroppgaven">← Aksjonærregisteroppgaven</Link>
    <h1 className="pageTitle">Årsgrunnlag for aksjonærregisteroppgaven</h1>
    <p className="pageLede">Kontroller aksjonærer, aksjer og årets hendelser før du lager en forhåndsvisning.</p>
    <p className="cardNote">Inntektsåret {incomeYear}</p>
  </div>;
  if (!company || company.id !== companyId || company.role !== "owner" || company.entity_type !== "AS"
      || !company.identity_confirmed_at || !company.identity_locked_at) {
    return <div>{header}<Banner variant="danger">Årsgrunnlaget er ikke tilgjengelig. Kontroller eiertilgangen og at selskapsopplysningene er bekreftet.</Banner></div>;
  }
  try {
    const [basis, source, documents] = await Promise.all([
      loadRf1086SourceIntakeBasis(token, companyId, incomeYear),
      loadRf1086CurrentYearSource(token, companyId, incomeYear),
      listDocuments(token, companyId),
    ]);
    if (documents.documents.some((document) => document.companyId !== companyId)) {
      throw new Error("Document scope mismatch");
    }
    return <div>{header}<SourceEditor key={`${companyId}:${incomeYear}`} basis={basis} current={source.currentSource}
      documentOptions={documents.documents.filter(document => document.removedAt === null).map((document) => ({ id: document.id, name: document.name, incomeYear: document.incomeYear }))}
      caseId={randomUUID()} /></div>;
  } catch (error) {
    return <div>{header}<Banner variant="danger">{rf1086SourceErrorMessage(error)}</Banner></div>;
  }
}
