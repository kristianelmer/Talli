import { randomUUID } from "node:crypto";

import {
  loadSystemBoundary,
  presentSystemBoundaryFailure,
  presentSystemBoundarySuccess,
} from "../../features/system-boundary";

export const dynamic = "force-dynamic";

export default async function SystemBoundaryPage() {
  const requestId = randomUUID();
  let presentation;

  try {
    presentation = presentSystemBoundarySuccess(
      await loadSystemBoundary(requestId),
    );
  } catch (error) {
    presentation = presentSystemBoundaryFailure(error, requestId);
  }

  return (
    <main className="workspace">
      <section className="intro" aria-labelledby="boundary-heading">
        <p className="eyebrow">Systemstatus</p>
        <h1 id="boundary-heading">{presentation.heading}</h1>
        <p className="lede" role={presentation.tone === "failure" ? "alert" : "status"}>
          {presentation.message}
        </p>
      </section>
    </main>
  );
}
