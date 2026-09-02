export {
  approveOwnerDividend,
  finalizeOwnerDividend,
  proposeOwnerDividend,
  recordShareholderLoan,
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
  RecordedShareholderLoanWire,
  ShareholderLoanDirection,
  ShareholderLoanDocumentStatus,
  ShareholderLoanWire,
} from "@talli/talli-api-client";
