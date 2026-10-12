import { downloadRf1086Archive } from "../../../../../../features/shareholder-register-filing";
import { downloadRf1086ArchiveResponse } from "../archive-download.ts";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

export async function GET(request: Request) {
  return downloadRf1086ArchiveResponse(request, downloadRf1086Archive);
}
