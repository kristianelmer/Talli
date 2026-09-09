import { createHash, createHmac } from "node:crypto";

/** Server-only proof that the callback route selected its HTTP-only cookie. */
export function systemUserCallbackProof(
  requestId: string,
  accessToken: string,
  environment: Record<string, string | undefined> = process.env,
  now: number = Date.now(),
): string {
  const key = environment.TALLI_AUTHORITY_CALLBACK_INTERNAL_KEY ?? "";
  if (Buffer.byteLength(key, "utf8") < 32 || !accessToken
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(requestId)) {
    throw new Error("system_user_callback_transport_unavailable");
  }
  const timestamp = Math.floor(now / 1000).toString();
  const bearerHash = createHash("sha256").update(accessToken, "utf8").digest("hex");
  const message = ["v1", "POST", "/api/v1/authority-connections/system-user-callbacks",
    requestId.toLowerCase(), bearerHash, timestamp].join("\n");
  const signature = createHmac("sha256", key).update(message, "utf8").digest("hex");
  return `v1:${timestamp}:${signature}`;
}
