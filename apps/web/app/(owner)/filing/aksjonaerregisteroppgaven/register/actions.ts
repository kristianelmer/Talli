"use server";
import { revalidatePath } from "next/cache";
import { captureRf1086RegisterObservationThroughApi, rf1086RegisterErrorMessage, rf1086RegisterCaptureRejected,
  type RfRegisterObservationCaptureWire, type RfRegisterObservationReceiptWire } from "../../../../../features/shareholder-register-filing";
import { getCurrentSessionAccessToken } from "../../../../lib/supabase/auth-session";
type Result = { ok: true; value: RfRegisterObservationReceiptWire } | { ok: false; message: string; rejected: boolean };
export async function captureRegisterAction(command: RfRegisterObservationCaptureWire, key: string): Promise<Result> {
  if (!command || typeof command !== "object" || typeof command.companyId !== "string"
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(command.companyId)
      || !Number.isInteger(command.incomeYear) || command.incomeYear < 2000 || command.incomeYear > 2100
      || typeof key !== "string" || !/^[A-Za-z0-9._:-]{16,255}$/.test(key)) {
    return { ok: false, rejected: false, message: "Kontroller selskap og inntektsår." };
  }
  try {
    const token = await getCurrentSessionAccessToken();
    if (!token) return { ok: false, rejected: false, message: "Logg inn på nytt for å fortsette." };
    const value = await captureRf1086RegisterObservationThroughApi(token, command, key);
    revalidatePath("/filing/aksjonaerregisteroppgaven/register");
    return { ok: true, value };
  } catch (error) { return { ok: false, rejected: rf1086RegisterCaptureRejected(error), message: rf1086RegisterErrorMessage(error) }; }
}
