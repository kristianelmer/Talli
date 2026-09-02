export {
  approveOwnerDividend,
  finalizeOwnerDividend,
  proposeOwnerDividend,
  recordOwnerDividendPayment,
  registerOwnerDividendDocuments,
} from "./transport.ts";
export {
  corporateGovernanceActionErrorMessage,
  corporateGovernanceOutcomeMayBeUnknown,
} from "./presentation.ts";
export type {
  CorporateCanonicalDecisionWire,
  OwnerDividendApprovalWire,
  OwnerDividendDocumentsWire,
  OwnerDividendFinalizationWire,
  OwnerDividendLifecycleWire,
  OwnerDividendPaymentWire,
  OwnerDividendProposalWire,
  ProposedOwnerDividendWire,
} from "@talli/talli-api-client";
