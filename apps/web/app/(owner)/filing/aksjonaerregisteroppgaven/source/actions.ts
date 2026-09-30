"use server";

import { revalidatePath } from "next/cache";
import {
  captureRf1086YearSourceThroughApi,
  generateRf1086SourcePreviewThroughApi,
  loadRf1086SourceDocument,
  rf1086SourceCaptureRejected,
  rf1086SourceErrorMessage,
  type RfSourceDocumentWire,
  type RfSourcePreviewRequestWire,
  type RfSourcePreviewWire,
  type RfYearSourceCaptureWire,
  type RfYearSourceReceiptWire,
} from "../../../../../features/shareholder-register-filing";
import { getCurrentSessionAccessToken } from "../../../../lib/supabase/auth-session";

type Result<T> = { ok: true; value: T } | { ok: false; message: string };
type CaptureResult = { ok: true; value: RfYearSourceReceiptWire }
  | { ok: false; message: string; rejected: boolean };
const invalid = "Kontroller selskap og inntektsår, og prøv igjen.";
const signIn = "Logg inn på nytt før du fortsetter.";
const uuid = (value: unknown): value is string => typeof value === "string"
  && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const year = (value: unknown): value is number => typeof value === "number"
  && Number.isInteger(value) && value >= 2000 && value <= 2100;

export async function readSourceDocumentAction(companyId: string, documentId: string): Promise<Result<RfSourceDocumentWire>> {
  if (!uuid(companyId) || !uuid(documentId)) return { ok: false, message: invalid };
  try {
    const token = await getCurrentSessionAccessToken();
    if (!token) return { ok: false, message: signIn };
    return { ok: true, value: await loadRf1086SourceDocument(token, companyId, documentId) };
  } catch (error) {
    return { ok: false, message: rf1086SourceErrorMessage(error) };
  }
}

export async function captureSourceAction(command: RfYearSourceCaptureWire, key: string): Promise<CaptureResult> {
  if (!command || typeof command !== "object" || !uuid(command.companyId) || !year(command.incomeYear)
      || typeof key !== "string" || !/^[A-Za-z0-9._:-]{16,255}$/.test(key)) {
    return { ok: false, message: invalid, rejected: false };
  }
  try {
    const token = await getCurrentSessionAccessToken();
    if (!token) return { ok: false, message: signIn, rejected: false };
    const value = await captureRf1086YearSourceThroughApi(token, command, key);
    revalidatePath("/filing/aksjonaerregisteroppgaven/source");
    return { ok: true, value };
  } catch (error) {
    return { ok: false, message: rf1086SourceErrorMessage(error), rejected: rf1086SourceCaptureRejected(error) };
  }
}

export async function previewSourceAction(command: RfSourcePreviewRequestWire): Promise<Result<RfSourcePreviewWire>> {
  if (!command || typeof command !== "object" || !uuid(command.companyId)
      || !year(command.incomeYear) || !uuid(command.sourceId)) return { ok: false, message: invalid };
  try {
    const token = await getCurrentSessionAccessToken();
    if (!token) return { ok: false, message: signIn };
    return { ok: true, value: await generateRf1086SourcePreviewThroughApi(token, command) };
  } catch (error) {
    return { ok: false, message: rf1086SourceErrorMessage(error) };
  }
}
