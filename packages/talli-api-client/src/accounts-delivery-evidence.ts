/** Verify opaque retained bytes; classification and permission stay backend owned. */
import type {AccountsDeliveryOriginalWire} from "./generated/client.ts";

export async function verifyAccountsDeliveryOriginal(value: AccountsDeliveryOriginalWire) {
  if (!/^(?:draft|source|prepared_main|prepared_accounts|event|original):[a-f0-9]{64}$/u.test(value.key) || !/^[a-f0-9]{64}$/u.test(value.sha256)
      || value.sourceFilingId!==value.filingId || value.bodyBase64.length>48*1024*1024) throw new Error("Accounts original scope or size changed.");
  if (!value.key.startsWith("original:") && value.key.split(":")[1]!==value.sha256) throw new Error("Accounts original key changed.");
  const decoded=atob(value.bodyBase64);
  if (decoded.length>32*1024*1024 || btoa(decoded)!==value.bodyBase64) throw new Error("Accounts original encoding changed.");
  const bytes=Uint8Array.from(decoded,character=>character.charCodeAt(0));
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))).map(byte=>byte.toString(16).padStart(2,"0")).join("");
  if (digest!==value.sha256) throw new Error("Accounts original bytes changed.");
  return value;
}
