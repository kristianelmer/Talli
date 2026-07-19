import styles from "../../../../components/annual-workspace/annual-workspace.module.css";

export default function AnnualReportingLoading() {
  return <div className={styles.skeleton} aria-label="Laster årsrapportering" role="status" />;
}
