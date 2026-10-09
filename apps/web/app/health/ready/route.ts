import { dependenciesReady } from "../../../features/system-boundary/index.ts";

export async function GET() {
  const ready = await dependenciesReady();
  return Response.json(
    { status: ready ? "ready" : "not_ready" },
    { status: ready ? 200 : 503, headers: { "Cache-Control": "no-store" } },
  );
}
