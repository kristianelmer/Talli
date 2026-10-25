// Existing V1–V4 compatibility cases model a backend without the additive V6 operation.
// Current V6 routing/failure behavior is exercised separately, including the initial 404.
export function mockLegacyRfBackend(t, fetch) {
  return t.mock.method(globalThis, "fetch", (...args) => new URL(args[0]).pathname.endsWith("/production-v6")
    ? Promise.resolve(new Response(null, { status: 404 })) : fetch(...args));
}
