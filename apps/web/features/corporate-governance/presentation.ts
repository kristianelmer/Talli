import { TalliApiError } from "@talli/talli-api-client";

const PERSONAL_SHAREHOLDER_LOAN_BLOCK =
  "Lån fra selskap til personlig aksjonær må håndteres av regnskapsfører.";
const RELATED_PARTY_SECURITY_BLOCK =
  "Sikkerhet eller garanti mellom nærstående må vurderes av regnskapsfører.";

const MESSAGES: Record<string, string> = {
  AUTHENTICATION_REQUIRED: "Innlogging kreves.",
  corporate_governance_forbidden: "Bare en godkjent eier kan behandle utbyttet.",
  corporate_governance_not_found: "Fant ikke utbyttebeslutningen.",
  corporate_documents_idempotency_conflict: "Forespørsels-ID-en er allerede brukt til et annet innhold.",
  corporate_documents_latest_annual_accounts_required: "Siste godkjente årsregnskap mangler.",
  corporate_documents_reviewed_facts_changed: "Fakta er endret. Opprett og gjennomgå et nytt utkast.",
  corporate_documents_shareholder_facts_mismatch: "Aksjonærgrunnlaget er endret.",
  corporate_documents_unsupported_dividend_basis: "Utbyttegrunnlaget eller dokumentasjonen er ikke komplett.",
  corporate_documents_incomplete_board: "Hele styret må delta.",
  corporate_documents_incomplete_share_representation: "Alle aksjer må være representert.",
  corporate_documents_non_unanimous: "Beslutningen må være enstemmig.",
  corporate_documents_equity_or_liquidity_failed: "Egenkapital og likviditet må være forsvarlig etter utdelingen.",
  corporate_documents_finalized_declaration_required: "Utbyttet må være ferdigstilt før betaling registreres.",
  corporate_documents_payment_exceeds_payable: "Betalingen overstiger gjenstående utbyttegjeld.",
  corporate_documents_bank_transaction_already_matched: "Banktransaksjonen er allerede avstemt.",
  corporate_documents_accounting_policy_disabled: "Utbytte kan ikke ferdigstilles før regnskapsprinsippet er godkjent.",
  corporate_documents_missing_signed_artifacts: "Begge signerte utbyttedokumentene må være lastet opp og attestert.",
  REQUEST_VALIDATION_FAILED: "Kontroller feltene og prøv igjen.",
};

const SHAREHOLDER_LOAN_MESSAGES: Record<string, string> = {
  AUTHENTICATION_REQUIRED: "Innlogging kreves.",
  corporate_governance_forbidden: "Bare en godkjent eier kan registrere aksjonærlån.",
  personal_shareholder_loan_blocked: PERSONAL_SHAREHOLDER_LOAN_BLOCK,
  related_party_security_blocked: RELATED_PARTY_SECURITY_BLOCK,
  corporate_documents_invalid_persisted_facts: "Kontroller opplysningene om aksjonærlånet.",
  corporate_documents_idempotency_conflict: "Forespørsels-ID-en er allerede brukt til et annet innhold.",
  corporate_documents_bank_transaction_already_matched: "Banktransaksjonen er allerede avstemt.",
  corporate_governance_dependency_unavailable: "Tjenesten for aksjonærlån er midlertidig utilgjengelig. Prøv igjen.",
  REQUEST_VALIDATION_FAILED: "Kontroller opplysningene om aksjonærlånet.",
};

export function corporateGovernanceActionErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError) {
    const code = error.problem?.code;
    return code === undefined
      ? "Utbyttetjenesten svarte ikke som forventet. Prøv igjen."
      : MESSAGES[code] ?? "Utbyttehandlingen kunne ikke fullføres. Kontroller opplysningene.";
  }
  return "Forbindelsen til utbyttetjenesten ble brutt. Prøv samme forespørsel igjen.";
}

export function shareholderLoanActionErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError) {
    const code = error.problem?.code;
    return code === undefined
      ? "Tjenesten for aksjonærlån svarte ikke som forventet. Prøv igjen."
      : SHAREHOLDER_LOAN_MESSAGES[code] ?? "Aksjonærlånet kunne ikke registreres. Kontroller opplysningene.";
  }
  return "Forbindelsen til tjenesten for aksjonærlån ble brutt. Prøv samme forespørsel igjen.";
}

export type ShareholderLoanFormDirection =
  | "shareholder_to_company"
  | "company_to_corporate_shareholder"
  | "company_to_personal_shareholder";

export function shareholderLoanFormPresentation(
  direction: ShareholderLoanFormDirection,
  relatedPartySecurity: boolean,
): { title: string; treatment: string | null; block: string | null } {
  if (direction === "company_to_personal_shareholder") {
    return { title: "Kan ikke registreres i Talli", treatment: null, block: PERSONAL_SHAREHOLDER_LOAN_BLOCK };
  }
  if (relatedPartySecurity) {
    return { title: "Kan ikke registreres i Talli", treatment: null, block: RELATED_PARTY_SECURITY_BLOCK };
  }
  return direction === "shareholder_to_company"
    ? {
        title: "Slik behandles lånet",
        treatment: "Talli registrerer innbetalingen som penger i banken og gjeld til aksjonæren.",
        block: null,
      }
    : {
        title: "Slik behandles lånet",
        treatment: "Talli registrerer utbetalingen som en fordring på selskapsaksjonæren og mindre penger i banken.",
        block: null,
      };
}

export function corporateGovernanceOutcomeMayBeUnknown(error: unknown): boolean {
  return !(error instanceof TalliApiError) || error.status >= 500;
}
