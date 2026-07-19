import type { AuthorityObligation } from "./authority-permission.ts";
import { productionRf1086AdapterEnabled } from "./rf1086-submission.ts";

export type AuthorityAdapterCapability = {
  productionImplemented: boolean;
  productionEnabled: boolean;
};

export type AuthorityAdapterCapabilities = Record<
  AuthorityObligation,
  AuthorityAdapterCapability
>;

export type AuthoritySubmissionStep = {
  id: string;
  actor: "system_user" | "person_id_porten";
  outcome: string;
};

export type AuthoritySubmissionPlan = {
  obligation: AuthorityObligation;
  transport: "skatteetaten_xml_api" | "skatteetaten_validation_and_altinn3" | "altinn3_instance";
  requiresPersonalSignature: boolean;
  steps: AuthoritySubmissionStep[];
};

export interface AuthorityProductionAdapter {
  readonly obligation: AuthorityObligation;
  readonly mode: "disabled" | "test" | "production";
  execute(input: {
    companyId: string;
    incomeYear: number;
    payloadHash: string;
    idempotencyKey: string;
  }): Promise<never>;
}

export class AuthorityProductionAdapterDisabledError extends Error {
  readonly code = "production_authority_adapter_disabled";
  readonly obligation: AuthorityObligation;

  constructor(obligation: AuthorityObligation) {
    super(`Produksjonsadapter er ikke implementert eller aktivert for ${obligation}.`);
    this.name = "AuthorityProductionAdapterDisabledError";
    this.obligation = obligation;
  }
}

export function currentAuthorityAdapterCapabilities(
  environment: Record<string, string | undefined> = process.env,
): AuthorityAdapterCapabilities {
  return {
    aksjonaerregisteroppgaven: {
      productionImplemented: true,
      productionEnabled: productionRf1086AdapterEnabled(environment),
    },
    skattemelding: {
      productionImplemented: false,
      productionEnabled: false,
    },
    aarsregnskap: {
      productionImplemented: false,
      productionEnabled: false,
    },
  };
}

export function createDisabledAuthorityProductionAdapter(
  obligation: AuthorityObligation,
): AuthorityProductionAdapter {
  return {
    obligation,
    mode: "disabled",
    async execute() {
      throw new AuthorityProductionAdapterDisabledError(obligation);
    },
  };
}

export const authoritySubmissionPlans: Record<AuthorityObligation, AuthoritySubmissionPlan> = {
  aksjonaerregisteroppgaven: {
    obligation: "aksjonaerregisteroppgaven",
    transport: "skatteetaten_xml_api",
    requiresPersonalSignature: false,
    steps: [
      { id: "post_hovedskjema", actor: "system_user", outcome: "main_document_reference" },
      { id: "post_underskjema", actor: "system_user", outcome: "subdocument_references" },
      { id: "post_bekreft", actor: "system_user", outcome: "submission_reference" },
      { id: "poll_feedback", actor: "system_user", outcome: "feedback_documents" },
      { id: "archive_receipt", actor: "system_user", outcome: "official_receipt_and_archive_reference" },
    ],
  },
  skattemelding: {
    obligation: "skattemelding",
    transport: "skatteetaten_validation_and_altinn3",
    requiresPersonalSignature: true,
    steps: [
      { id: "fetch_prefill", actor: "system_user", outcome: "authority_prefill_snapshot" },
      { id: "validate_documents", actor: "system_user", outcome: "validation_feedback" },
      { id: "create_altinn_instance", actor: "system_user", outcome: "instance_reference" },
      { id: "upload_skattemelding", actor: "system_user", outcome: "skattemelding_data_reference" },
      { id: "upload_naeringsspesifikasjon", actor: "system_user", outcome: "business_specification_reference" },
      { id: "personal_signing_handoff", actor: "person_id_porten", outcome: "signed_and_submitted_instance" },
      { id: "archive_receipt", actor: "system_user", outcome: "official_receipt_and_archive_reference" },
    ],
  },
  aarsregnskap: {
    obligation: "aarsregnskap",
    transport: "altinn3_instance",
    requiresPersonalSignature: true,
    steps: [
      { id: "create_altinn_instance", actor: "system_user", outcome: "instance_reference" },
      { id: "upload_hovedskjema", actor: "system_user", outcome: "main_data_reference" },
      { id: "upload_selskapsregnskap", actor: "system_user", outcome: "accounts_data_reference" },
      { id: "upload_attachments", actor: "system_user", outcome: "attachment_references" },
      { id: "lock_instance", actor: "system_user", outcome: "signing_ready_instance" },
      { id: "personal_signing_handoff", actor: "person_id_porten", outcome: "signed_and_submitted_instance" },
      { id: "archive_receipt", actor: "system_user", outcome: "official_receipt_and_archive_reference" },
    ],
  },
};
