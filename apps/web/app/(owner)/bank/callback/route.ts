import { randomUUID } from "node:crypto";

import { NextResponse, type NextRequest } from "next/server";

import {
  bankingActionErrorMessage,
  completeBankConnection,
} from "../../../../features/banking";
import { getCurrentSessionAccessToken } from "../../../lib/supabase/auth-session";

const CALLBACK_KEYS = ["code", "state", "resource_id", "result"] as const;

export async function GET(request: NextRequest) {
  const target = new URL("/transactions", request.url);
  const connectionId = request.nextUrl.searchParams.get("connectionId") ?? "";
  const companyId = request.nextUrl.searchParams.get("companyId") ?? "";
  const incomeYear = Number(request.nextUrl.searchParams.get("incomeYear"));
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken || !connectionId || !companyId || !Number.isInteger(incomeYear)) {
    target.searchParams.set("error", "Banktilkoblingen kunne ikke bekreftes. Start tilkoblingen på nytt.");
    return NextResponse.redirect(target, 303);
  }

  const callback = Object.fromEntries(
    CALLBACK_KEYS.flatMap((key) => {
      const value = request.nextUrl.searchParams.get(key);
      return value === null ? [] : [[key === "resource_id" ? "resourceId" : key, value]];
    }),
  );
  try {
    await completeBankConnection(accessToken, connectionId, {
      companyId,
      incomeYear,
      requestId: randomUUID(),
      ...callback,
    });
  } catch (error) {
    target.searchParams.set("error", bankingActionErrorMessage(error));
    return NextResponse.redirect(target, 303);
  }
  target.searchParams.set("bankConnected", "1");
  return NextResponse.redirect(target, 303);
}
