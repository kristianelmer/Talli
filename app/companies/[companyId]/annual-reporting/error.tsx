"use client";

export default function AnnualReportingRouteError({ reset }: { reset: () => void }) {
  return (
    <main style={{ maxWidth: 680, margin: "80px auto", padding: "0 24px" }}>
      <h1>Årsrapporteringen kunne ikke lastes</h1>
      <p>Ingen data er endret. Prøv på nytt, eller gå tilbake til selskapsoversikten.</p>
      <button className="primaryButton" onClick={reset} type="button">Prøv igjen</button>
      <p><a href="/">Tilbake til oversikten</a></p>
    </main>
  );
}
