import { createHash } from "node:crypto";

export type BankProviderMode = "disabled" | "test" | "production";

export type BankConsentRequest = {
  companyId: string;
  returnUrl: string;
};

export type BankConsentSession = {
  providerConnectionRef: string;
  authorizationUrl: string;
  expiresAt: string;
};

export type BankSyncRequest = {
  companyId: string;
  connectionId: string;
  cursor: string | null;
};

export type BankSyncTransaction = {
  providerTransactionRef: string;
  bookedAt: string;
  text: string;
  amount: number;
  currency: "NOK";
};

export type BankSyncResult = {
  transactions: BankSyncTransaction[];
  nextCursor: string | null;
  consentExpiresAt: string;
};

export type VerifiedBankWebhook = {
  eventId: string;
  connectionRef: string;
  eventType: string;
};

export interface BankProviderPort {
  readonly providerKey: string;
  readonly mode: BankProviderMode;
  beginConsent(input: BankConsentRequest): Promise<BankConsentSession>;
  syncTransactions(input: BankSyncRequest): Promise<BankSyncResult>;
  verifyWebhook(input: { headers: Headers; body: Uint8Array }): Promise<VerifiedBankWebhook>;
}

export class BankProviderDisabledError extends Error {
  readonly code = "bank_provider_disabled";

  constructor() {
    super("Bankintegrasjon er deaktivert inntil leverandør, samtykkemodell og databehandleravtale er godkjent.");
    this.name = "BankProviderDisabledError";
  }
}

export function createDisabledBankProvider(): BankProviderPort {
  const reject = async (): Promise<never> => {
    throw new BankProviderDisabledError();
  };

  return {
    providerKey: "unconfigured",
    mode: "disabled",
    beginConsent: reject,
    syncTransactions: reject,
    verifyWebhook: reject,
  };
}

export function bankWebhookReceiptKey(providerKey: string, eventId: string) {
  const provider = providerKey.trim().toLocaleLowerCase("en-US");
  const event = eventId.trim();
  if (!provider) {
    throw new Error("Bankleverandør mangler.");
  }
  if (!event) {
    throw new Error("Webhook event-ID mangler.");
  }
  return createHash("sha256").update(`${provider}\0${event}`).digest("hex");
}

export function redactBankProviderDiagnostic(message: string) {
  return message
    .replace(/Bearer\s+[^\s,;]+/gi, "Bearer [REDACTED]")
    .replace(/\b(access_token|refresh_token|client_secret)=([^\s&,;]+)/gi, "$1=[REDACTED]")
    .slice(0, 1_000);
}
