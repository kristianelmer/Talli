export {
  BackendConfigurationError,
  companyAccessBackendBaseUrl,
  loadCompanyAccessRecord,
  loadCompanyAccessContext,
  loadOperatorContext,
  searchOperatorCompanyRecords,
  type BackendConfigurationErrorCode,
} from "./transport/load-company-access-context.ts";
export {
  companyAccessActionErrorMessage,
  eligibilityActionErrorMessage,
  eligibilityAdmissionRestartRequired,
  presentCompanyAccessRecord,
  presentCompanyAccessContext,
  presentOperatorCompanyRecord,
  type AcceptedMembershipCompanyPresentation,
  type CompanyAccessPresentation,
  type CompanyRegistryPresentation,
} from "./presentation.ts";
export {
  acceptCompanyInvitation,
  administerCompanyMembership,
  createCompanyInvitation,
  completeInvitationSideEffect,
  listCompanyInvitations,
  listCompanyMemberships,
  listPendingInvitationSideEffects,
  lookupCompanyInvitation,
  resendCompanyInvitation,
  revokeCompanyInvitation,
} from "./transport/company-access-administration.ts";
export {
  admitCompanyYearThroughApi,
  assessCompanyEligibility,
  precheckCompanyEligibility,
  recheckCompanyYearEligibilityThroughApi,
  reacceptCompanyAgreementThroughApi,
} from "./transport/company-access-onboarding.ts";
export {
  finalizeCompanyDeletion,
  listCompanyCancellations,
  requestCompanyCancellation,
  resumeCompanyCancellation,
  reviewCompanyDeletion,
} from "./transport/company-access-cancellation.ts";
export type { EligibilityDecisionResponse } from "@talli/talli-api-client";
export type EligibilityAnswer = import("@talli/talli-api-client").EligibilityDecisionResponse["answers"][string];
