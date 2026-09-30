import { randomUUID } from "node:crypto";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { listDocuments } from "../../../../../features/documents";
import {
  loadRf1086CurrentYearSource,
  loadRf1086SourceIntakeBasis,
  rf1086SourceErrorMessage,
  loadRf1086Workspaces,
} from "../../../../../features/shareholder-register-filing";
import { Banner } from "../../../../components/ui";
import { loadAcceptedMembershipCompany } from "../../../../lib/company-access-context";
import { getCurrentSessionAccessToken } from "../../../../lib/supabase/auth-session";
import { SourceEditor } from "./SourceEditor";
import { SourceProduction } from "./SourceProduction";

export const dynamic = "force-dynamic";

type Props = {
  searchParams: Promise<{ companyId?: string | string[]; incomeYear?: string | string[] }>;
};

async function SourceProductionPanel({ token, companyId, incomeYear }: { token: string; companyId: string; incomeYear: number }) {
  try {
    const [workspace] = await loadRf1086Workspaces(token, [companyId], incomeYear);
    const approvals = workspace.approvals.filter(row => row.caseProfile === "rf1086_full_year_v1" && row.incomeYear === incomeYear)
      .sort((a, b) => b.approvedAt.localeCompare(a.approvedAt)).map(row => ({ id: row.id, approvedAt: row.approvedAt }));
    const artifacts = workspace.feedbackArtifacts.map(row => ({ id: row.id, submissionId: row.submissionId,
      documentId: row.documentId, classification: row.classification }));
    // A newly saved approval replaces selection and clears any prior send consent/status.
    return <SourceProduction key={`production:${companyId}:${incomeYear}:${approvals[0]?.id ?? "none"}`} companyId={companyId} incomeYear={incomeYear} approvals={approvals} artifacts={artifacts} />;
  } catch {
    return <Banner variant="danger">Lagrede godkjenninger og innsendingsstatus kunne ikke hentes. Last siden på nytt før du gjør noe mer.</Banner>;
  }
}

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
    {company?.name ? <p className="cardNote">{company.name}</p> : null}
  </div>;
  if (!company || company.id !== companyId || company.role !== "owner" || company.entity_type !== "AS"
      || !company.identity_confirmed_at || !company.identity_locked_at) {
    return <div>{header}<Banner variant="danger">Årsgrunnlaget er ikke tilgjengelig. Kontroller eiertilgangen og at selskapsopplysningene er bekreftet.</Banner></div>;
  }
  const archiveDownload = <div className="card">
    <a className="btn btn--secondary" href={`/filing/aksjonaerregisteroppgaven/source/archive?${new URLSearchParams({ companyId, incomeYear: String(incomeYear) })}`}>Last ned RF-arkiv</a>
    <p className="cardNote">Lagret årsgrunnlag, innsendingshistorikk og bevarte originaldokumenter for {incomeYear}. Ekstra identitetsbekreftelse kreves.</p>
  </div>;
  const production = SourceProductionPanel({ token, companyId, incomeYear });
  try {
    const [basis, source, documents] = await Promise.all([
      loadRf1086SourceIntakeBasis(token, companyId, incomeYear),
      loadRf1086CurrentYearSource(token, companyId, incomeYear),
      listDocuments(token, companyId),
    ]);
    if (documents.documents.some((document) => document.companyId !== companyId)) {
      throw new Error("Document scope mismatch");
    }
    return <div>{header}{archiveDownload}{await production}<SourceEditor key={`source:${companyId}:${incomeYear}`} basis={basis} current={source.currentSource}
      documentOptions={documents.documents.filter(document => document.removedAt === null).map((document) => ({ id: document.id, name: document.name, incomeYear: document.incomeYear }))}
      caseId={randomUUID()} /></div>;
  } catch (error) {
    return <div>{header}{archiveDownload}{await production}<Banner variant="danger">{rf1086SourceErrorMessage(error)}</Banner></div>;
  }
}
