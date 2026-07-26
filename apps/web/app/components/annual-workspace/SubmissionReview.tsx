import Link from "next/link";

import { confirmSimulatedRf1086Submission } from "../../actions";
import { annualReviewHref, type AnnualWorkspaceViewModel } from "../../lib/annual-workspace";
import { preProductionDirectFilingCopy, requiredNonAffiliationCopy } from "../../lib/launch-copy";
import type {
  AuthorityPermissionRow,
  BillingAccountRow,
  FilingPreviewRow,
  FilingSubmissionRow,
} from "../../lib/supabase/server";
import styles from "./annual-workspace.module.css";

type SubmissionRecords = {
  previews: FilingPreviewRow[];
  submissions: FilingSubmissionRow[];
  authorityPermissions: AuthorityPermissionRow[];
  billingAccounts: BillingAccountRow[];
};

export function SubmissionReview({ model, records }: { model: AnnualWorkspaceViewModel; records: SubmissionRecords }) {
  const selectedPreview = records.previews.find((item) => item.filing === "aksjonærregisteroppgaven" && item.status !== "blocked");
  const pending = records.submissions.some((item) => item.status === "pending" && !item.receipt_id);
  const completed = records.submissions.find((item) => item.receipt_id);
  const hardReviewBlocks = model.comments.filter((item) => item.severity === "hard_block");
  const readinessOpen = model.obligations.some((item) => item.status === "blocked" || item.status === "not_started");
  const permissionReady = records.authorityPermissions.some((item) => item.confirmed_at);
  const billingReady = records.billingAccounts.some((item) => item.filing_package_paid || item.pricing_plan === "founder");
  const canSimulate = Boolean(selectedPreview) && !readinessOpen && hardReviewBlocks.length === 0;
  const gates = [
    { label: "Grunnlag", ready: !readinessOpen, text: readinessOpen ? "Én eller flere plikter har åpne blokkeringer." : "Lagret readiness er kontrollert." },
    { label: "Gjennomgang", ready: hardReviewBlocks.length === 0, text: hardReviewBlocks.length ? `${hardReviewBlocks.length} harde kontrollpunkter må løses.` : "Ingen harde kontrollpunkter er åpne." },
    { label: "Innsendingsrett", ready: permissionReady, text: permissionReady ? "Eier har bekreftet innsendingsrett." : "Må bekreftes før produksjonsinnsending." },
    { label: "Betaling", ready: billingReady, text: billingReady ? "Filingpakken er dekket." : "Må fullføres før produksjonsinnsending." },
  ];

  return (
    <section aria-labelledby="review-title">
      <header className={styles.pageHeader}><div><h1 id="review-title">Gjennomgang og innsending</h1><p>Kontroller gate for gate. Statusene kommer fra lagrede backenddata.</p></div></header>
      <div className={styles.gateList}>{gates.map((gate) => <div className={styles.gateRow} key={gate.label}><span aria-hidden="true">{gate.ready ? "✓" : "○"}</span><div><strong>{gate.label}</strong><p>{gate.text}</p></div></div>)}</div>

      <div aria-live="polite">
        {completed ? <div className={styles.receipt}><strong>Simulert kvittering arkivert</strong><p>Kvitterings-ID: {completed.receipt_id}</p></div> : null}
        {pending ? <div className={styles.notice}>Innsending behandles. Ikke start en ny innsending.</div> : null}
      </div>

      {model.role === "owner" && selectedPreview && canSimulate && !completed ? (
        <form action={confirmSimulatedRf1086Submission} className={styles.form}>
          <input type="hidden" name="returnTo" value={annualReviewHref(model.context)} />
          <input type="hidden" name="previewId" value={selectedPreview.id} />
          <label className={styles.check}><input type="checkbox" name="authorityConfirmed" required />Jeg bekrefter at jeg har fullmakt til denne simuleringen.</label>
          <label className={styles.check}><input type="checkbox" name="previewConfirmed" required />Jeg har kontrollert forhåndsvisningen.</label>
          <button disabled={pending} className={styles.primaryButton} type="submit">Arkiver simulert kvittering</button>
        </form>
      ) : null}

      {!selectedPreview ? <p className={styles.emptyState}>Lag en forhåndsvisning av aksjonærregisteroppgaven før simulert innsending.</p> : null}
      <p><Link href={model.obligations[0].href}>Tilbake til pliktene</Link></p>
      <div className={styles.legalCopy}><p>{preProductionDirectFilingCopy}</p><p>{requiredNonAffiliationCopy}</p></div>
    </section>
  );
}
