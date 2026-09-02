import { TalliApiError } from "@talli/talli-api-client";

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

export function corporateGovernanceActionErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError) {
    const code = error.problem?.code;
    return code === undefined
      ? "Utbyttetjenesten svarte ikke som forventet. Prøv igjen."
      : MESSAGES[code] ?? "Utbyttehandlingen kunne ikke fullføres. Kontroller opplysningene.";
  }
  return "Forbindelsen til utbyttetjenesten ble brutt. Prøv samme forespørsel igjen.";
}

export function corporateGovernanceOutcomeMayBeUnknown(error: unknown): boolean {
  return !(error instanceof TalliApiError) || error.status >= 500;
}
