import { randomUUID } from "node:crypto";

import { loadSystemBoundary } from "../../../features/system-boundary/index.ts";

export async function GET() {
  try {
    const boundary = await loadSystemBoundary(randomUUID());
    if (boundary.status !== "AVAILABLE") {
      throw new Error("Backend boundary is not available");
    }
    return Response.json(
      { status: "ready" },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return Response.json(
      { status: "not_ready" },
      {
        status: 503,
        headers: { "Cache-Control": "no-store" },
      },
    );
  }
}
