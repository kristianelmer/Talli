"use server";

import { revalidatePath } from "next/cache";
import { loadRf1086SourceProductionPosition, sendRf1086SourceProduction, reconcileRf1086ThroughApi,
  rf1086ActionErrorMessage, type RfSourceProductionSendCommandWire } from "../../../../../features/shareholder-register-filing";
import { getCurrentSessionAccessToken } from "../../../../lib/supabase/auth-session";

type Scope = { companyId: string; incomeYear: number; approvalId: string };
const uuid = (value: unknown): value is string => typeof value === "string"
  && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
function valid(input: Scope) {
  return input && uuid(input.companyId) && uuid(input.approvalId)
    && Number.isInteger(input.incomeYear) && input.incomeYear >= 2000 && input.incomeYear <= 2100;
}
const failure = (message: string) => ({ ok: false as const, message });

export async function readSourceProductionPositionAction(input: Scope) {
  if (!valid(input)) return failure("Kontroller selskap, år og godkjenning.");
  try {
    const token = await getCurrentSessionAccessToken();
    if (!token) return failure("Logg inn på nytt for å fortsette.");
    const value = await loadRf1086SourceProductionPosition(token, input.approvalId, input.companyId, input.incomeYear);
    return { ok: true as const, value };
  } catch (error) { return failure(rf1086ActionErrorMessage(error)); }
}

export async function sendSourceProductionAction(input: Scope & RfSourceProductionSendCommandWire & { confirmed: boolean }) {
  if (!valid(input) || input.confirmed !== true || !/^[a-f0-9]{64}$/.test(input.manifestSha256)
      || (input.expectedHead != null && !uuid(input.expectedHead))) return failure("Bekreft den lagrede oppgaven før innsending.");
  try {
    const token = await getCurrentSessionAccessToken();
    if (!token) return failure("Logg inn på nytt for å fortsette.");
    const position = await loadRf1086SourceProductionPosition(token, input.approvalId, input.companyId, input.incomeYear);
    if (position.manifestSha256 !== input.manifestSha256 || position.expectedHead !== (input.expectedHead ?? null)) {
      return failure("Godkjenningen er endret. Hent lagret status og kontroller oppgaven på nytt.");
    }
    const value = await sendRf1086SourceProduction(token, { approvalId: input.approvalId,
      manifestSha256: input.manifestSha256, expectedHead: input.expectedHead ?? null });
    revalidatePath("/filing/aksjonaerregisteroppgaven/source");
    revalidatePath("/filing/aksjonaerregisteroppgaven");
    return { ok: true as const, value };
  } catch (error) { return failure(rf1086ActionErrorMessage(error)); }
}

export async function reconcileSourceProductionAction(input: Scope) {
  if (!valid(input)) return failure("Kontroller selskap, år og godkjenning.");
  try {
    const token = await getCurrentSessionAccessToken();
    if (!token) return failure("Logg inn på nytt for å fortsette.");
    const position = await loadRf1086SourceProductionPosition(token, input.approvalId, input.companyId, input.incomeYear);
    if (position.disposition !== "confirmed" || !position.submissionId) {
      return failure("Mottaket er ikke bekreftet. Innsendingsutfallet må avklares før tilbakemelding kan hentes.");
    }
    const value = await reconcileRf1086ThroughApi(token, position.submissionId);
    revalidatePath("/filing/aksjonaerregisteroppgaven/source");
    return { ok: true as const, value };
  } catch (error) { return failure(rf1086ActionErrorMessage(error)); }
}
