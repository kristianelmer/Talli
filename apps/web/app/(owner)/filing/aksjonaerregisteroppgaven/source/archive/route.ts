import { downloadRf1086Archive } from "../../../../../../features/shareholder-register-filing";
import { downloadRf1086ArchiveResponse } from "../archive-download.ts";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

type RequestObserver = ((request: Request, run: () => ReturnType<typeof downloadRf1086ArchiveResponse>) => ReturnType<typeof downloadRf1086ArchiveResponse>) & {
  ready: (realm: typeof globalThis) => void;
};
const observation = (globalThis as typeof globalThis & { [key: symbol]: RequestObserver | undefined })[
  Symbol.for("talli.rf-low-aal-request-observer-v1")
];
// Fixture-only callback; readiness in another execution realm is not inferred.
try { observation?.ready(globalThis); } catch { /* Diagnostics cannot prevent routing. */ }

export async function GET(request: Request) {
  if (observation) return observation(request, () => downloadRf1086ArchiveResponse(request, downloadRf1086Archive));
  return downloadRf1086ArchiveResponse(request, downloadRf1086Archive);
}
