export {
  approveOwnerDividend,
  finalizeOwnerDividend,
  proposeAnnualClose,
  proposeOwnerDividend,
  recordShareholderLoan,
  recordOwnerDividendPayment,
  registerOwnerDividendDocuments,
} from "./transport.ts";
export {
  corporateGovernanceActionErrorMessage,
  corporateGovernanceOutcomeMayBeUnknown,
  shareholderLoanActionErrorMessage,
  shareholderLoanFormPresentation,
} from "./presentation.ts";
export type { ShareholderLoanFormDirection } from "./presentation.ts";
export type {
  AnnualCloseProposalWire,
  CorporateCanonicalDecisionWire,
  OwnerDividendApprovalWire,
  OwnerDividendDocumentsWire,
  OwnerDividendFinalizationWire,
  OwnerDividendLifecycleWire,
  OwnerDividendPaymentWire,
  OwnerDividendProposalWire,
  ProposedOwnerDividendWire,
  ProposedAnnualCloseWire,
  RenderedCorporateArtifactWire,
  RecordedShareholderLoanWire,
  ShareholderLoanDirection,
  ShareholderLoanDocumentStatus,
  ShareholderLoanWire,
} from "@talli/talli-api-client";
