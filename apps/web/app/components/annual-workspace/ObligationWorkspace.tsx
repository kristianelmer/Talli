import Link from "next/link";

import {
  addFilingReviewComment,
  confirmAuthorityPermission,
  generateRf1086Preview,
  uploadDocument,
} from "../../actions";
import type { AuthorityObligation } from "../../lib/authority-permission";
import type { AnnualWorkspaceViewModel } from "../../lib/annual-workspace";
import type {
  AuthorityPermissionRow,
  FilingPreviewRow,
  OpeningBalanceSetupRow,
} from "../../lib/supabase/server";
import styles from "./annual-workspace.module.css";

const obligationDescription: Record<AuthorityObligation, string> = {
  aksjonaerregisteroppgaven: "Kontroller aksjonærer, kapital og bevegelser før oppgaven klargjøres.",
  aarsregnskap: "Samle årsopplysninger, dokumentasjon og noter til et komplett årsregnskap.",
  skattemelding: "Kontroller at transaksjoner og skattebehandling er tydelig dokumentert.",
};

const issueTitleByCode: Record<string, string> = {
  notes_missing: "Noter mangler",
  annual_data_missing: "Årsopplysninger mangler",
  opening_balance_missing: "Åpningsbalanse mangler",
  documents_missing: "Dokumentasjon mangler",
  authority_permission_missing: "Innsendingsrett må bekreftes",
  filing_package_not_paid: "Betaling må fullføres",
};

type ObligationRecords = {
  setups: OpeningBalanceSetupRow[];
  previews: FilingPreviewRow[];
  authorityPermissions: AuthorityPermissionRow[];
};

export function ObligationWorkspace({
  model,
  obligation,
  records,
}: {
  model: AnnualWorkspaceViewModel;
  obligation: AuthorityObligation;
  records: ObligationRecords;
}) {
  const view = model.obligations.find((item) => item.obligation === obligation);
  if (!view) return null;
  const issues = [...view.hardBlocks, ...view.warnings, ...view.acceptedWarnings];
  const setup = records.setups[0];
  const preview = records.previews.find((item) => filingMatches(item.filing, obligation));
  const hasAuthority = records.authorityPermissions.some((item) => item.obligation === obligation);

  return (
    <div className={styles.obligationLayout}>
      <section>
        <header className={styles.pageHeader}>
          <div><h1>{view.label}</h1><p>{obligationDescription[obligation]}</p></div>
          <span className={styles.status} aria-label={`Status: ${view.statusLabel}`}><span className={styles.statusDot} aria-hidden="true" />{view.statusLabel}</span>
        </header>

        {view.unsupported ? <div className={styles.notice}><strong>Denne plikten trenger faglig vurdering.</strong><br />De andre årspliktene er fortsatt tilgjengelige. Ta dette punktet med en regnskapsfører.</div> : null}

        <section className={styles.section} aria-labelledby="readiness-title">
          <h2 id="readiness-title">Dette må være klart</h2>
          {issues.length ? (
            <div className={styles.readinessList}>
              {issues.map((issue) => (
                <article id={`issue-${issue.code}`} key={`${issue.source}-${issue.code}`} className={styles.readinessRow}>
                  <svg className={styles.issueIcon} viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M10 5.5v5M10 14h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
                  <div><h3>{issueTitleByCode[issue.code] ?? "Åpent punkt"}</h3><p>{issue.message}</p></div>
                </article>
              ))}
            </div>
          ) : <p className={styles.emptyState}>Ingen åpne punkter er lagret for denne plikten.</p>}
        </section>

        <section className={styles.section} aria-labelledby="evidence-title">
          <h2 id="evidence-title">Grunnlag og dokumentasjon</h2>
          <p className={styles.muted}>{model.documents.length} dokumenter er knyttet til {model.context.incomeYear}. Data fra arbeidsflaten brukes som kilde.</p>
          {model.role === "owner" ? (
            <form action={uploadDocument} className={styles.form}>
              <input type="hidden" name="returnTo" value={view.href} />
              <input type="hidden" name="companyId" value={model.context.companyId} />
              <input type="hidden" name="incomeYear" value={model.context.incomeYear} />
              <input type="hidden" name="linkedTo" value={obligation} />
              <label>Dokument<input name="file" type="file" required /></label>
              <button className={styles.secondaryButton} type="submit">Last opp dokument</button>
            </form>
          ) : null}
        </section>

        {model.role === "owner" && obligation === "aksjonaerregisteroppgaven" && setup ? (
          <section className={styles.section} aria-labelledby="preview-title">
            <h2 id="preview-title">Forhåndsvisning</h2>
            <form action={generateRf1086Preview} className={styles.form}>
              <input type="hidden" name="returnTo" value={view.href} />
              <input type="hidden" name="setupId" value={setup.id} />
              <button className={styles.primaryButton} type="submit">Lag ny forhåndsvisning</button>
            </form>
          </section>
        ) : null}

        {model.role === "owner" && !hasAuthority ? (
          <section className={styles.section} aria-labelledby="authority-title">
            <h2 id="authority-title">Innsendingsrett</h2>
            <form action={confirmAuthorityPermission} className={styles.form}>
              <input type="hidden" name="returnTo" value={view.href} />
              <input type="hidden" name="companyId" value={model.context.companyId} />
              <input type="hidden" name="obligation" value={obligation} />
              <label className={styles.check}><input type="checkbox" name="authorityConfirmed" required />Jeg bekrefter at jeg har rett til å sende inn for selskapet.</label>
              <button className={styles.secondaryButton} type="submit">Bekreft innsendingsrett</button>
            </form>
          </section>
        ) : null}
      </section>

      <aside className={styles.contextRail} aria-label="Kontroll">
        <section className={styles.contextGroup}><h2>Kontrollør</h2><p className={styles.muted}>{model.role === "reviewer" ? "Du kan kontrollere samme grunnlag som eier." : "Inviterte kontrollører ser denne samme arbeidsflaten."}</p></section>
        {preview && model.role !== "read_only" ? (
          <section className={styles.contextGroup}>
            <h2>Legg til kommentar</h2>
            <form action={addFilingReviewComment} className={styles.form}>
              <input type="hidden" name="returnTo" value={view.href} />
              <input type="hidden" name="previewId" value={preview.id} />
              <label>Type<select name="severity"><option value="advisory">Kommentar</option><option value="hard_block">Må løses</option></select></label>
              <label>Kommentar<textarea name="body" rows={4} required /></label>
              <button className={styles.secondaryButton} type="submit">Lagre kommentar</button>
            </form>
          </section>
        ) : <section className={styles.contextGroup}><h2>Kommentarer</h2><p className={styles.muted}>Lag en forhåndsvisning før kontrollkommentarer legges til.</p></section>}
        <Link className={styles.secondaryButton} href={view.href.replace(/\/[^/]+$/, "/review")}>Gå til gjennomgang</Link>
      </aside>
    </div>
  );
}

function filingMatches(filing: string, obligation: AuthorityObligation) {
  if (obligation === "aksjonaerregisteroppgaven") return filing === "aksjonærregisteroppgaven";
  if (obligation === "aarsregnskap") return filing === "årsregnskap";
  return filing === "skattemelding for AS";
}
