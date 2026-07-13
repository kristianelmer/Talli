import { NextResponse } from "next/server";
import { evaluateRuntimeReadiness } from "../../lib/runtime-readiness";

export const dynamic = "force-dynamic";

export async function GET() {
  const readiness = await evaluateRuntimeReadiness();
  return NextResponse.json(readiness, {
    status: readiness.status === "ready" ? 200 : 503,
    headers: { "Cache-Control": "no-store" },
  });
}
