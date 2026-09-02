import assert from "node:assert/strict";
import test from "node:test";

import { TalliApiError } from "@talli/talli-api-client";
import {
  corporateGovernanceActionErrorMessage,
  corporateGovernanceOutcomeMayBeUnknown,
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
