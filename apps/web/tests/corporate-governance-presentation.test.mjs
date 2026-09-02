import assert from "node:assert/strict";
import test from "node:test";

import { TalliApiError } from "@talli/talli-api-client";
import {
  corporateGovernanceActionErrorMessage,
  corporateGovernanceOutcomeMayBeUnknown,
  shareholderLoanActionErrorMessage,
  shareholderLoanFormPresentation,
} from "../features/corporate-governance/presentation.ts";

function apiError(status, code) {
  return new TalliApiError(status, {
    type: "https://talli.no/problems/corporate-governance",
    title: "Request failed",
    status,
    code,
    detail: "Governance request failed.",
    instance: "/api/v1/corporate-governance/owner-dividends/test",
    requestId: "governance-presentation-test",
  });
}

test("governance errors expose stable Norwegian owner guidance", () => {
  assert.equal(
    corporateGovernanceActionErrorMessage(
      apiError(409, "corporate_documents_payment_exceeds_payable"),
    ),
    "Betalingen overstiger gjenstående utbyttegjeld.",
  );
  assert.equal(
    corporateGovernanceActionErrorMessage(
      apiError(403, "corporate_governance_forbidden"),
    ),
    "Bare en godkjent eier kan behandle utbyttet.",
  );
  assert.equal(
    corporateGovernanceActionErrorMessage(apiError(409, "future_code")),
    "Utbyttehandlingen kunne ikke fullføres. Kontroller opplysningene.",
  );
  assert.equal(
    corporateGovernanceActionErrorMessage(new Error("private detail")),
    "Forbindelsen til utbyttetjenesten ble brutt. Prøv samme forespørsel igjen.",
  );
});

test("shareholder-loan form presentation explains treatment without exposing posting policy", () => {
  assert.deepEqual(
    shareholderLoanFormPresentation("shareholder_to_company", false),
    {
      title: "Slik behandles lånet",
      treatment: "Talli registrerer innbetalingen som penger i banken og gjeld til aksjonæren.",
      block: null,
    },
  );
  assert.equal(
    shareholderLoanFormPresentation("company_to_corporate_shareholder", false).treatment,
    "Talli registrerer utbetalingen som en fordring på selskapsaksjonæren og mindre penger i banken.",
  );
  assert.equal(
    shareholderLoanFormPresentation("company_to_personal_shareholder", false).block,
    "Lån fra selskap til personlig aksjonær må håndteres av regnskapsfører.",
  );
  assert.equal(
    shareholderLoanFormPresentation("shareholder_to_company", true).block,
    "Sikkerhet eller garanti mellom nærstående må vurderes av regnskapsfører.",
  );
});

test("shareholder-loan errors never fall through to dividend guidance", () => {
  assert.equal(
    shareholderLoanActionErrorMessage(apiError(422, "personal_shareholder_loan_blocked")),
    "Lån fra selskap til personlig aksjonær må håndteres av regnskapsfører.",
  );
  assert.equal(
    shareholderLoanActionErrorMessage(apiError(422, "related_party_security_blocked")),
    "Sikkerhet eller garanti mellom nærstående må vurderes av regnskapsfører.",
  );
  assert.equal(
    shareholderLoanActionErrorMessage(apiError(409, "future_code")),
    "Aksjonærlånet kunne ikke registreres. Kontroller opplysningene.",
  );
  assert.equal(
    shareholderLoanActionErrorMessage(new Error("private detail")),
    "Forbindelsen til tjenesten for aksjonærlån ble brutt. Prøv samme forespørsel igjen.",
  );
});

test("only transport and server failures preserve an unknown-outcome retry", () => {
  assert.equal(corporateGovernanceOutcomeMayBeUnknown(new Error("timeout")), true);
  assert.equal(corporateGovernanceOutcomeMayBeUnknown(apiError(503, "unavailable")), true);
  assert.equal(
    corporateGovernanceOutcomeMayBeUnknown(
      apiError(409, "corporate_documents_payment_exceeds_payable"),
    ),
    false,
  );
});
