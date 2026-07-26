export function GET() {
  return Response.json(
    { status: "alive" },
    { headers: { "Cache-Control": "no-store" } },
  );
}
