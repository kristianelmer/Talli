import { backendBaseUrl } from "../../../features/system-boundary/index.ts";

export async function GET() {
  try {
    backendBaseUrl();
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
