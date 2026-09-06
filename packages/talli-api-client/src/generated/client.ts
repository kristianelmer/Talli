// Generated from contracts/openapi/talli-v1.json. Do not edit by hand.
// Contract version: 1.0.0

export interface SystemBoundaryStatus {
  apiVersion: string;
  service: string;
  status: "AVAILABLE";
}

export interface CompanyContext {
  aal: "aal2";
  address: string;
  admittedAccountingYear: number | null;
  archiveExportAvailable: boolean;
  city: string;
  companyYearAdmissionId: string | null;
  consequentialOperationsAllowed: boolean;
  createdAt: string;
  createdBy: string;
  currentAgreementAccepted: boolean;
  currentEligibilityDecision: "supported" | "clarify" | "blocked" | null;
  eligibilityNextStep: string | null;
  eligibilityNextStepCode: string | null;
  eligibilityReasonExplanations: string[];
  entityType: string;
  id: string;
  identityConfirmedAt: string | null;
  identityLockedAt: string | null;
  name: string;
  orgNumber: string;
  postalCode: string;
  resourceScope: "owner_sensitive";
  role: "owner";
  source: string;
  statusText: string;
}

export interface CompanyContextResponse {
  companies: CompanyContext[];
  selectedCompany: CompanyContext;
}

export interface CompanyInvitation {
  companyId: string;
  createdAt: string;
  expiresAt: string;
  id: string;
  invitedEmail: string;
  role: "reviewer" | "read_only";
  status: "pending" | "accepted" | "revoked" | "expired";
  updatedAt: string;
}

export interface CompanyInvitationListResponse {
  invitations: CompanyInvitation[];
}

export interface CompanyInvitationResponse {
  deliveryBody: string | null;
  deliverySubject: string | null;
  deliveryToken: string | null;
  invitation: CompanyInvitation;
}

export interface CompanyMembership {
  acceptedAt: string;
  companyId: string;
  role: "reviewer" | "read_only";
  state: "active" | "removed";
  userId: string;
}

export interface CompanyMembershipListResponse {
  memberships: CompanyMembership[];
}

export interface CompanyMembershipResponse {
  membership: CompanyMembership;
}

export interface CompanyOnboardingRequest {
  agreementAccepted: true;
  businessTermsSha256: "afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04";
  businessTermsVersion: "2026-08-30";
  dpaSha256: "1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a";
  dpaVersion: "2026-08-30";
  orgNumber: string;
}

export interface CompanyOnboardingResponse {
  companyId: string;
  currentAgreementAccepted: true;
  replayed: boolean;
}

export interface CompanyAgreementAcceptanceRequest {
  agreementAccepted: true;
  businessTermsSha256: "afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04";
  businessTermsVersion: "2026-08-30";
  companyId: string;
  dpaSha256: "1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a";
  dpaVersion: "2026-08-30";
}

export interface CompanyAgreementAcceptanceResponse {
  companyId: string;
  currentAgreementAccepted: true;
  replayed: boolean;
}

export interface EligibilityPrecheckRequest {
  accountingYear: number;
  orgNumber: string;
}

export interface EligibilityDefinitiveRequest {
  accountingYear: number;
  answers: Record<string, "yes" | "no" | "unknown">;
  capabilityManifestSha256: string;
  capabilityManifestVersion: string;
  expectedPublicFactsSha256: string;
  orgNumber: string;
}

export interface EligibilityPublicFacts {
  entityType: string;
  name: string;
  orgNumber: string;
  source: string;
  statusText: string;
}

export interface EligibilityQuestion {
  answerOptions?: ("yes" | "no" | "unknown")[];
  code: string;
  prompt: string;
}

export interface CompanyYearPromise {
  accountingYear: number;
  customerClaims: string[];
  endsOn: string;
  onlyAccountingAndFilingProduct: true;
  reconstructionRequiredFrom: string;
  startsOn: string;
}

export interface EligibilityDecisionResponse {
  accountingYear: number;
  answers: Record<string, "yes" | "no" | "unknown">;
  answersSha256: string | null;
  capabilityManifestSha256: string;
  capabilityManifestVersion: string;
  companyYearPromise: CompanyYearPromise | null;
  decision: "supported" | "clarify" | "blocked";
  nextStep: string;
  nextStepCode: string;
  provisional: boolean;
  publicFacts: EligibilityPublicFacts;
  publicFactsSha256: string;
  questionCodes: string[];
  questions: EligibilityQuestion[];
  reasonCodes: string[];
  reasonExplanations: string[];
}

export interface CompanyYearAdmissionRequest {
  accountingYear: number;
  agreementAccepted: true;
  answers: Record<string, "yes" | "no" | "unknown">;
  authorityAccepted: true;
  businessTermsSha256: "afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04";
  businessTermsVersion: "2026-08-30";
  capabilityManifestSha256: string;
  capabilityManifestVersion: string;
  companyYearPromiseAccepted: true;
  dpaSha256: "1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a";
  dpaVersion: "2026-08-30";
  expectedPublicFactsSha256: string;
  operationId: string;
  orgNumber: string;
  privacyNoticeSha256: string;
  privacyNoticeVersion: string;
}

export interface CompanyYearAdmissionResponse {
  accountingYear: number;
  capabilityManifestSha256: string;
  capabilityManifestVersion: string;
  companyId: string;
  companyYearAdmissionId: string;
  currentAgreementAccepted: true;
  reconstructFrom: string;
  replayed: boolean;
}

export interface CompanyYearEligibilityRecheckRequest {
  answers?: Record<string, "yes" | "no" | "unknown"> | null;
  operationId: string;
  trigger: "public_fact_changed" | "material_answer_changed" | "manifest_changed" | "before_payment" | "before_filing";
}

export interface CompanyYearEligibilityStateResponse {
  acceptedCapabilityManifestSha256: string;
  acceptedCapabilityManifestVersion: string;
  acceptedCompanyYearPromise: CompanyYearPromise;
  accountingYear: number;
  archiveExportAvailable: true;
  companyId: string;
  companyYearAdmissionId: string;
  companyYearEligibilityAssessmentId: string;
  consequentialOperationsAllowed: boolean;
  currentCapabilityManifestSha256: string;
  currentCapabilityManifestVersion: string;
  decision: "supported" | "clarify" | "blocked";
  nextStep: string;
  nextStepCode: string;
  reasonCodes: string[];
  reasonExplanations: string[];
  replayed: boolean;
  trigger: "public_fact_changed" | "material_answer_changed" | "manifest_changed" | "before_payment" | "before_filing";
}

export interface CompanyAccessRecord {
  address: string;
  city: string;
  createdAt: string;
  createdBy: string;
  entityType: string;
  id: string;
  identityConfirmedAt: string | null;
  identityLockedAt: string | null;
  name: string;
  orgNumber: string;
  postalCode: string;
  role: "owner" | "reviewer" | "read_only";
  source: string;
  statusText: string;
}

export interface CompanyAccessRecordResponse {
  company: CompanyAccessRecord;
}

export interface OperatorContextResponse {
  active: true;
  role: "support" | "admin";
}

export interface OperatorCompanyRecord {
  address: string;
  city: string;
  createdAt: string;
  createdBy: string;
  entityType: string;
  id: string;
  identityConfirmedAt: string | null;
  identityLockedAt: string | null;
  name: string;
  orgNumber: string;
  postalCode: string;
  source: string;
  statusText: string;
}

export interface OperatorCompanySearchResponse {
  companies: OperatorCompanyRecord[];
}

export interface GrantSupportAccessRequest {
  companyId: string;
  expiresAt: string;
  operationId: string;
  operatorUserId: string;
  reason: "customer_request" | "security_incident" | "service_recovery" | "legal_obligation";
  scopes: ("profile" | "filing" | "billing" | "audit" | "cancellation" | "authority" | "documents" | "production")[];
  startsAt: string;
}

export interface RevokeSupportAccessRequest {
  operationId: string;
  reason: "case_closed" | "access_no_longer_needed" | "operator_removed" | "security_response" | "grant_replaced";
}

export interface OpenSupportCaseRequest {
  operationId: string;
}

export interface SupportAccessGrant {
  caseId: string;
  companyId: string;
  expiresAt: string;
  grantedAt: string;
  grantedBy: string;
  operatorUserId: string;
  reason: "customer_request" | "security_incident" | "service_recovery" | "legal_obligation";
  revocationReason: "case_closed" | "access_no_longer_needed" | "operator_removed" | "security_response" | "grant_replaced" | null;
  revokedAt: string | null;
  revokedBy: string | null;
  scopes: ("profile" | "filing" | "billing" | "audit" | "cancellation" | "authority" | "documents" | "production")[];
  startsAt: string;
}

export interface SupportAccessGrantResponse {
  grant: SupportAccessGrant;
}

export interface SupportCaseOpening {
  caseId: string;
  companyId: string;
  openedAt: string;
  openedBy: string;
  operationId: string;
}

export interface SupportCaseOpeningResponse {
  opening: SupportCaseOpening;
}

export interface SupportCompanyResource {
  address: string;
  city: string;
  createdAt: string;
  createdBy: string;
  entityType: string;
  id: string;
  identityConfirmedAt: string | null;
  identityLockedAt: string | null;
  name: string;
  orgNumber: string;
  postalCode: string;
  source: string;
  statusText: string;
}

export interface SupportAuditEventResource {
  action: string;
  actorId: string;
  category: string;
  companyId: string;
  createdAt: string;
  id: string;
  message: string;
}

export interface SupportCancellationResource {
  companyId: string;
  deletedAt: string | null;
  deletedBy: string | null;
  evidence: Record<string, unknown>;
  id: string;
  reason: string;
  requestedAt: string;
  requestedBy: string;
  reviewedAt: string | null;
  reviewedBy: string | null;
  status: string;
  updatedAt: string;
}

export interface SupportFilingSubmissionResource {
  companyId: string;
  filing: string;
  id: string;
  incomeYear: number;
  status: string;
  updatedAt: string;
}

export interface SupportFilingReadinessResource {
  companyId: string;
  hardBlocks: Record<string, unknown>[];
  id: string;
  incomeYear: number;
  obligation: string;
  ready: boolean;
  status: string;
  updatedAt: string;
  warnings: Record<string, unknown>[];
}

export interface SupportBillingAccountResource {
  companyId: string;
  filingPackagePaid: boolean;
  pricingPlan: string;
  refundCompleted: boolean;
  refundEligible: boolean;
  refundProviderRef: string | null;
  subscriptionActive: boolean;
  updatedAt: string;
}

export interface SupportBillingPaymentEventResource {
  amountNok: number;
  companyId: string;
  createdAt: string;
  id: string;
  kind: string;
  provider: string;
  status: string;
}

export interface SupportAuthorityPermissionResource {
  companyId: string;
  id: string;
  obligation: string;
  productionEnabled: boolean;
  updatedAt: string;
}

export interface SupportAuthorityTestRunResource {
  companyId: string;
  environment: string;
  id: string;
  obligation: string;
  recordedAt: string;
  status: string;
  testReference: string;
}

export interface SupportSystemUserRequestResource {
  companyId: string;
  failureCode: string | null;
  id: string;
  obligation: string;
  requestedAt: string | null;
  status: string;
  updatedAt: string;
}

export interface SupportProductionPilotEntitlementResource {
  caseProfile: string;
  companyId: string;
  expiresAt: string;
  id: string;
  incomeYear: number;
  obligation: string;
  startsAt: string;
  status: string;
  updatedAt: string;
  userId: string;
}

export interface SupportFilingApprovalSnapshotResource {
  adapterVersion: string;
  approvedAt: string;
  caseProfile: string;
  companyId: string;
  id: string;
  incomeYear: number;
  invalidatedAt: string | null;
  manifestHash: string;
  obligation: string;
  payloadHash: string;
}

export interface SupportProductionFilingSubmissionResource {
  adapterVersion: string;
  caseProfile: string;
  companyId: string;
  createdAt: string;
  failureClass: string | null;
  id: string;
  incomeYear: number;
  obligation: string;
  status: string;
  updatedAt: string;
}

export interface SupportProductionFilingEventResource {
  attempt: number;
  createdAt: string;
  failureClass: string | null;
  id: string;
  operationName: string;
  operationState: string;
  resultingStatus: string;
  submissionId: string;
}

export interface SupportProductionFeedbackArtifactResource {
  byteLength: number;
  classification: string;
  companyId: string;
  contentType: string;
  documentId: string;
  id: string;
  retrievedAt: string;
  sha256: string;
  submissionId: string;
}

export interface SupportDocumentResource {
  companyId: string;
  createdAt: string;
  documentType: string;
  id: string;
  incomeYear: number;
  linkedTo: string;
  name: string;
  retentionYears: number;
  status: string;
  storageKey: string;
}

export interface SupportStorageObjectResource {
  bucketId: string;
  createdAt: string;
  id: string;
  name: string;
}

export interface SupportDeletionReviewResource {
  cancellationId: string;
  companyId: string;
  decision: string;
  evidenceReference: string;
  id: string;
  reviewedAt: string;
  supportCaseId: string;
}

export interface SupportCaseResources {
  auditEvents: SupportAuditEventResource[];
  authorityPermissions: SupportAuthorityPermissionResource[];
  authorityTestRuns: SupportAuthorityTestRunResource[];
  billingAccounts: SupportBillingAccountResource[];
  billingPaymentEvents: SupportBillingPaymentEventResource[];
  companies: SupportCompanyResource[];
  companyCancellations: SupportCancellationResource[];
  companyDeletionReviews: SupportDeletionReviewResource[];
  documents: SupportDocumentResource[];
  filingApprovalSnapshots: SupportFilingApprovalSnapshotResource[];
  filingReadinessSnapshots: SupportFilingReadinessResource[];
  filingSubmissions: SupportFilingSubmissionResource[];
  productionFeedbackArtifacts: SupportProductionFeedbackArtifactResource[];
  productionFilingEvents: SupportProductionFilingEventResource[];
  productionFilingSubmissions: SupportProductionFilingSubmissionResource[];
  productionPilotEntitlements: SupportProductionPilotEntitlementResource[];
  storageObjects: SupportStorageObjectResource[];
  systemUserRequests: SupportSystemUserRequestResource[];
}

export interface SupportCaseSnapshotResponse {
  caseId: string;
  companyId: string;
  resources: SupportCaseResources;
  scopes: ("profile" | "filing" | "billing" | "audit" | "cancellation" | "authority" | "documents" | "production")[];
}

export interface AcceptCompanyInvitationRequest {
  operationId: string;
  token: string;
}

export interface CreateCompanyInvitationRequest {
  companyId: string;
  invitedEmail: string;
  operationId: string;
  role: "reviewer" | "read_only";
}

export interface InvitationLookup {
  companyName: string;
  expiresAt: string;
  role: "reviewer" | "read_only";
}

export interface InvitationTokenRequest {
  token: string;
}

export interface CompanyInvitationCommandRequest {
  companyId: string;
  expectedUpdatedAt: string;
  operationId: string;
}

export interface AdministerCompanyMembershipRequest {
  companyId: string;
  expectedRole: "reviewer" | "read_only";
  operationId: string;
  role?: "reviewer" | "read_only" | null;
  state?: "active" | "removed" | null;
}

export interface InvitationSideEffectContinuation {
  commandName: "create_invitation" | "accept_invitation" | "revoke_invitation" | "resend_invitation";
  companyId: string;
  deliveryBody: string | null;
  deliverySubject: string | null;
  deliveryToken: string | null;
  invitation: CompanyInvitation | null;
  membership: CompanyMembership | null;
  operationId: string;
}

export interface InvitationSideEffectContinuationList {
  continuations: InvitationSideEffectContinuation[];
}

export interface InvitationSideEffectCompletion {
  completed: true;
  operationId: string;
}

export interface CompanyCancellationEvidence {
  archiveDownloadPath?: string | null;
  archiveExportedAt?: string | null;
  archiveIncomeYear?: number | null;
  corporateEvidenceComplete?: boolean | null;
  corporateObjectKeys?: string[];
  legalReviewRequired?: boolean;
  missingCorporateObjectKeys?: string[];
  missingDocumentIds?: string[];
  retentionClasses?: string[];
}

export interface CompanyCancellation {
  companyId: string;
  deletedAt: string | null;
  deletedBy: string | null;
  evidence: CompanyCancellationEvidence;
  id: string;
  reason: string;
  requestedAt: string;
  requestedBy: string;
  reviewedAt: string | null;
  reviewedBy: string | null;
  status: "export_required" | "retention_hold" | "deletion_approved" | "deleted" | "superseded";
  updatedAt: string;
}

export interface CompanyCancellationListResponse {
  cancellations: CompanyCancellation[];
}

export interface CompanyCancellationResponse {
  cancellation: CompanyCancellation;
}

export interface CompanyDeletionReview {
  cancellationId: string;
  cancellationRevision: string;
  companyId: string;
  decision: "approved" | "rejected";
  evidenceReference: string;
  id: string;
  operationId: string;
  reviewedAt: string;
  reviewedBy: string;
}

export interface CompanyDeletionReviewResponse {
  cancellation: CompanyCancellation;
  review: CompanyDeletionReview;
}

export interface RequestCompanyCancellationRequest {
  companyId: string;
  incomeYear: number;
  operationId: string;
  reason: string;
}

export interface ResumeCompanyCancellationRequest {
  companyId: string;
  expectedUpdatedAt: string;
  incomeYear: number;
  operationId: string;
}

export interface ReviewCompanyDeletionRequest {
  companyId: string;
  decision: "approved" | "rejected";
  evidenceReference: string;
  expectedUpdatedAt: string;
  operationId: string;
}

export interface FinalizeCompanyDeletionRequest {
  companyId: string;
  expectedUpdatedAt: string;
  operationId: string;
}

export interface AdministrativeCostEntryWire {
  companyId: string;
  entryId: string;
  entryKind: "ADMINISTRATIVE_COST";
  incomeYear: number;
  postedAt: string;
  replayed: boolean;
}

export type AdministrativeCostCategory = "BANK_FEE" | "ACCOUNTING_FEE" | "SOFTWARE" | "PUBLIC_FEE" | "LEGAL_ADVISORY" | "OTHER_ADMIN_COST";

export type CompanyYearCloseGapCode = "SOURCE_INCOMPLETE" | "JOURNAL_UNBALANCED" | "DUPLICATE_POSTING_FOUND" | "UNSUPPORTED_TRANSACTION" | "BANK_NOT_RECONCILED" | "UNRESOLVED_BANK_ROW" | "MATERIAL_BALANCE_UNDOCUMENTED" | "REPORTING_NOT_RECONCILED" | "CHECK_EVIDENCE_INCOMPLETE" | "PERIOD_END_UNSUPPORTED";

export type CompanyYearCloseState = "BLOCKED" | "CLOSED";

export interface LedgerAdministrativeCostWire {
  amount: LedgerMoneyWire;
  bankTransactionId: string;
  category: AdministrativeCostCategory;
  companyId: string;
  documentId?: string | null;
  incomeYear: number;
  paidDate: string;
  payee: string;
}

export interface LedgerCompanyYearCloseAssessmentWire {
  assessmentId: string;
  closeLockId: string | null;
  companyId: string;
  evidenceDigest: string;
  gapCodes: CompanyYearCloseGapCode[];
  incomeYear: number;
  isCurrent: boolean;
  ledgerStateDigest: string;
  periodEnd: string;
  reconstructionAssessmentId: string;
  recordedAt: string;
  replayed: boolean;
  state: CompanyYearCloseState;
}

export type LedgerEntryKind = "OPENING_BALANCE" | "ADMINISTRATIVE_COST" | "MANUAL_JOURNAL" | "BANK_RULE_SUGGESTION" | "DIVIDEND_RECEIVED" | "OWNER_DIVIDEND_DECLARED" | "OWNER_DIVIDEND_PAYMENT" | "SHARE_PURCHASE" | "SHARE_SALE" | "SHAREHOLDER_LOAN" | "TAX_SETTLEMENT" | "BANK_INTEREST" | "BANK_LOAN" | "CAPITAL_INCREASE" | "CAPITAL_REDUCTION" | "COMPANY_TAX_ACCRUAL" | "GROUP_CONTRIBUTION" | "INTERCOMPANY_LOAN" | "INVESTMENT_MEASUREMENT" | "CORRECTION_REVERSAL";

export interface LedgerEntryPageWire {
  items: LedgerEntryViewWire[];
  page: LedgerPageWire;
}

export interface LedgerEntryViewWire {
  companyId: string;
  createdAt?: string;
  entryId: string;
  entryKind: LedgerEntryKind;
  incomeYear: number;
  lines: LedgerLineWire[];
  memo: string;
  postedAt: string;
  postedBy: string;
  riskFlags: LedgerRiskFlagWire[];
  sourceCapability?: LedgerSourceCapability;
  sourceRecordId?: string;
  warningAcceptedAt: string | null;
  warningAcceptedBy: string | null;
}

export interface LedgerLineWire {
  account: string;
  credit: LedgerMoneyWire;
  debit: LedgerMoneyWire;
  description: string;
}

export interface LedgerLockPeriodWire {
  companyId: string;
  incomeYear: number;
  reason: string;
}

export interface LedgerManualJournalWire {
  companyId: string;
  incomeYear: number;
  lines: LedgerLineWire[];
  memo: string;
  warningAccepted: boolean;
}

export interface LedgerMoneyWire {
  amount: string;
  currency: "NOK";
}

export interface LedgerFactReferenceWire {
  capability: LedgerSourceCapability;
  factSha256: string;
  recordId: string;
  revision: number;
}

export type OpeningBalanceCategory = "SUBSIDIARY_LOAN_RECEIVABLE" | "GROUP_COMPANY_LOAN_RECEIVABLE" | "CORPORATE_SHAREHOLDER_LOAN_RECEIVABLE" | "BANK" | "RESTRICTED_BANK" | "SUBSIDIARY_INVESTMENT" | "ASSOCIATE_INVESTMENT" | "OTHER_LONG_TERM_INVESTMENT" | "CURRENT_LISTED_SHARE_INVESTMENT" | "CURRENT_FUND_INVESTMENT" | "SUBSCRIPTION_RECEIVABLE" | "DIVIDEND_RECEIVABLE" | "GROUP_CONTRIBUTION_RECEIVABLE" | "TAX_RECEIVABLE" | "ACCRUED_INTEREST_RECEIVABLE" | "DEFERRED_TAX_ASSET" | "REGISTERED_SHARE_CAPITAL" | "SHARE_PREMIUM" | "UNREGISTERED_CAPITAL_INCREASE" | "UNREGISTERED_CAPITAL_REDUCTION" | "OTHER_PAID_IN_EQUITY" | "RETAINED_EARNINGS" | "UNCOVERED_LOSS" | "OTHER_EQUITY" | "LONG_TERM_BANK_LOAN_PAYABLE" | "SHORT_TERM_BANK_LOAN_PAYABLE" | "OWNER_LOAN_PAYABLE" | "INTERCOMPANY_LOAN_PAYABLE" | "SUPPLIER_PAYABLE" | "CURRENT_TAX_PAYABLE" | "DEFERRED_TAX_LIABILITY" | "ACCRUED_INTEREST_PAYABLE" | "DIVIDEND_PAYABLE" | "GROUP_CONTRIBUTION_PAYABLE";

export type OpeningPositionMode = "NEW_COMPANY" | "PRIOR_CLOSE_RECONSTRUCTION";

export type BankLoanMaturity = "LONG_TERM" | "SHORT_TERM";

export type InvestmentClassification = "SUBSIDIARY" | "ASSOCIATE" | "OTHER_LONG_TERM" | "CURRENT_LISTED_SHARE" | "CURRENT_FUND";

export type CapitalIncreasePhase = "BINDING_SUBSCRIPTION" | "RESTRICTED_PAYMENT" | "REGISTERED";

export type CapitalReductionRecognition = "DECIDED_NOT_REGISTERED" | "REGISTERED" | "FIRST_RECOGNIZED_AFTER_REGISTRATION";

export interface OpeningClassifiedBalanceWire {
  amount: LedgerMoneyWire;
  category: OpeningBalanceCategory;
  componentKind: "CLASSIFIED_BALANCE";
  corroboratingSources: LedgerFactReferenceWire[];
  primarySource: LedgerFactReferenceWire;
  referenceId: string;
}

export interface OpeningBankLoanWire {
  amount: LedgerMoneyWire;
  componentKind: "BANK_LOAN";
  corroboratingSources: LedgerFactReferenceWire[];
  loanReferenceId: string;
  maturity: BankLoanMaturity;
  primarySource: LedgerFactReferenceWire;
}

export interface OpeningInvestmentWire {
  amount: LedgerMoneyWire;
  classification: InvestmentClassification;
  componentKind: "INVESTMENT";
  corroboratingSources: LedgerFactReferenceWire[];
  investmentReferenceId: string;
  primarySource: LedgerFactReferenceWire;
}

export interface OpeningCapitalIncreaseWire {
  capitalIncreaseReferenceId: string;
  componentKind: "CAPITAL_INCREASE";
  corroboratingSources: LedgerFactReferenceWire[];
  nominalIncrease: LedgerMoneyWire;
  phase: CapitalIncreasePhase;
  primarySource: LedgerFactReferenceWire;
  sharePremium: LedgerMoneyWire;
}

export interface OpeningCapitalReductionWire {
  capitalReductionReferenceId: string;
  componentKind: "CAPITAL_REDUCTION";
  corroboratingSources: LedgerFactReferenceWire[];
  nominalReduction: LedgerMoneyWire;
  primarySource: LedgerFactReferenceWire;
  recognition: CapitalReductionRecognition;
}

export interface OpeningDividendReceivableWire {
  amount: LedgerMoneyWire;
  componentKind: "DIVIDEND_RECEIVABLE";
  corroboratingSources: LedgerFactReferenceWire[];
  decisionReferenceId: string;
  primarySource: LedgerFactReferenceWire;
}

export interface OpeningDividendPayableWire {
  amount: LedgerMoneyWire;
  componentKind: "DIVIDEND_PAYABLE";
  corroboratingSources: LedgerFactReferenceWire[];
  decisionReferenceId: string;
  primarySource: LedgerFactReferenceWire;
}

export interface NewYearShareholderWire {
  name: string;
  nationalId?: string | null;
  orgNumber?: string | null;
  shareCount: number;
  shareholderKind: "norwegian_person" | "norwegian_company";
}

export interface NewYearOpeningEntryWire {
  companyId: string;
  entryId: string;
  entryKind: "OPENING_BALANCE";
  incomeYear: number;
  postedAt: string;
  replayed: boolean;
}

export interface NewYearStartResultWire {
  postedEntry: NewYearOpeningEntryWire;
  setupId: string;
}

export interface NewYearStartWire {
  bankBalance: LedgerMoneyWire;
  companyId: string;
  incomeYear: number;
  nominalValue: LedgerMoneyWire;
  openingBasis?: LedgerFactReferenceWire | null;
  openingComponents?: (OpeningClassifiedBalanceWire | OpeningBankLoanWire | OpeningInvestmentWire | OpeningCapitalIncreaseWire | OpeningCapitalReductionWire | OpeningDividendReceivableWire | OpeningDividendPayableWire)[] | null;
  openingMode?: OpeningPositionMode;
  shareCapital: LedgerMoneyWire;
  shareCount: number;
  shareholders: NewYearShareholderWire[];
}

export interface LedgerOpeningShareholderWire {
  companyId: string;
  name: string;
  nationalId: string | null;
  orgNumber: string | null;
  setupId: string;
  shareCount: number;
  shareholderId: string;
  shareholderKind: "norwegian_person" | "norwegian_company";
}

export interface LedgerOpeningSnapshotPageWire {
  hasMore: boolean;
  items: LedgerOpeningSnapshotWire[];
  nextCursor: string | null;
}

export interface LedgerOpeningSnapshotWire {
  bankBalance: LedgerMoneyWire;
  companyId: string;
  createdAt: string;
  createdBy: string;
  incomeYear: number;
  lockedAt: string;
  nominalValue: LedgerMoneyWire;
  setupId: string;
  shareCapital: LedgerMoneyWire;
  shareCount: number;
  shareholders: LedgerOpeningShareholderWire[];
}

export interface LedgerPageWire {
  hasMore: boolean;
  nextCursor: string | null;
}

export interface LedgerPeriodLockPageWire {
  items: LedgerPeriodLockWire[];
  page: LedgerPageWire;
}

export interface LedgerPeriodLockWire {
  companyId: string;
  incomeYear: number;
  lockedAt: string;
  lockedBy: string;
  periodLockId: string;
  reason: string;
  replayed: boolean;
}

export interface LedgerReconstructionAssessmentWire {
  asOf: string;
  assessmentId: string;
  companyId: string;
  economicFactCount: number | null;
  economicFactsDigest: string | null;
  evidenceDigest: string;
  gapCodes: ReconstructionGapCode[];
  incomeYear: number;
  ledgerStateDigest: string | null;
  recordedAt: string;
  sourceEvidenceCount: number | null;
  sourceEvidenceDigest: string | null;
  state: ReconstructionState;
}

export type ReconstructionGapCode = "PRIOR_CLOSING_MISMATCH" | "BANK_MOVEMENTS_INCOMPLETE" | "BANK_NOT_RECONCILED" | "INVESTMENTS_UNCONFIRMED" | "SHAREHOLDERS_UNCONFIRMED" | "LOANS_UNCONFIRMED" | "EQUITY_UNCONFIRMED" | "TAX_HISTORY_UNCONFIRMED" | "CURRENT_ACTIVITY_INCOMPLETE" | "DOCUMENTS_INCOMPLETE" | "UNSUPPORTED_ACTIVITY_FOUND";

export interface LedgerPostedEntryWire {
  companyId: string;
  entryId: string;
  entryKind: LedgerEntryKind;
  incomeYear: number;
  postedAt: string;
  replayed: boolean;
}

export interface LedgerRiskFlagWire {
  account: string;
  code: LedgerRiskCode;
}

export type LedgerRiskCode = "MANUAL_JOURNAL_SENSITIVE_ACCOUNT";

export type LedgerSourceCapability = "LEDGER" | "BANKING" | "INVESTMENTS" | "CORPORATE_GOVERNANCE" | "SHAREHOLDER_REGISTER_FILING" | "COMPANY_TAX_FILING" | "ANNUAL_ACCOUNTS_FILING" | "DOCUMENTS";

export interface LedgerTaxSettlementWire {
  actionId: string;
  amount: LedgerMoneyWire;
  bankTransactionId?: string | null;
  companyId: string;
  documentId?: string | null;
  documentStatus: "attached" | "missing_accepted_warning" | "not_required";
  incomeYear: number;
  settlementDate: string;
  settlementKind: TaxSettlementKind;
}

export interface LedgerWriterResultWire {
  postedEntry: LedgerPostedEntryWire | null;
  replayed: boolean;
}

export type ReconstructionState = "BLOCKED" | "READY";

export type TaxSettlementKind = "payable" | "payment" | "refund";

export type InvestmentActivityKind = "share_purchase" | "share_sale" | "dividend_received" | "fund_distribution_received";

export type InvestmentCorrectionTargetKind = "economic_event" | "cash_settlement";

export interface InvestmentFactReferenceWire {
  capability: InvestmentSourceCapability;
  factSha256: string;
  recordId: string;
  revision: number;
}

export type InvestmentSourceCapability = "BANKING" | "DOCUMENTS";

export interface InvestmentCorrectionPageWire {
  items: InvestmentCorrectionWire[];
  page: InvestmentsPageWire;
}

export interface InvestmentCorrectionWire {
  companyId: string;
  createdAt: string;
  createdBy: string;
  documentFacts: InvestmentFactReferenceWire[];
  evidenceDigest: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  id: string;
  incomeYear: number;
  legacy: boolean;
  legacyBankTransactionId: string | null;
  legacyDocumentId: string | null;
  legacyDocumentStatus: InvestmentDocumentStatus | null;
  originalActivityKind: InvestmentActivityKind;
  originalRecordId: string;
  ownerAttested: boolean;
  reason: string;
  replacementAccountingEntryId: string;
  replacementActivityKind: InvestmentActivityKind;
  replacementRecordId: string;
  reversalAccountingEntryId: string;
  targetKind: InvestmentCorrectionTargetKind;
}

export interface InvestmentActivityPageWire {
  items: InvestmentActivityWire[];
  page: InvestmentsPageWire;
}

export interface InvestmentActivityWire {
  accountingClassification: InvestmentAccountingClassification;
  accountingEntryId: string | null;
  acquisitionLotId: string | null;
  actionDate: string;
  activityKind: InvestmentActivityKind;
  bankTransactionId: string | null;
  bookGainOrLoss: LedgerMoneyWire | null;
  calculationId: string;
  capitalizedCost: LedgerMoneyWire | null;
  companyId: string;
  createdAt: string;
  createdBy: string;
  declaredDate: string | null;
  deductibleLoss: LedgerMoneyWire | null;
  dividendPortion: LedgerMoneyWire | null;
  documentId: string | null;
  documentStatus: InvestmentDocumentStatus;
  entitlementDate: string | null;
  evidenceDigest: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  exemptGain: LedgerMoneyWire | null;
  fifoCostBasisReduction: LedgerMoneyWire | null;
  fifoTaxBasisReduction: LedgerMoneyWire | null;
  fundEquityRatioBasisPoints: number | null;
  fundName: string | null;
  fundTaxStatementReference: string | null;
  gainOrLoss: LedgerMoneyWire | null;
  grossAmount: LedgerMoneyWire | null;
  groupEvidenceReference: string | null;
  groupExceptionApplied: boolean | null;
  groupExceptionClaimed: boolean | null;
  id: string;
  incomeYear: number;
  interestPortion: LedgerMoneyWire | null;
  investmentKey: string;
  investmentKind: InvestmentKind;
  investmentName: string;
  lawfulDividendConfirmed: boolean | null;
  netProceeds: LedgerMoneyWire | null;
  nonDeductibleLoss: LedgerMoneyWire | null;
  openingFundEquityRatioBasisPoints: number | null;
  orgNumber: string | null;
  ownerAttested: boolean;
  payingCompanyName: string | null;
  positionId: string;
  proceeds: LedgerMoneyWire | null;
  purchaseAmount: LedgerMoneyWire | null;
  remainingCostBasis: LedgerMoneyWire | null;
  remainingShareCount: string | null;
  remainingTaxBasis: LedgerMoneyWire | null;
  shareCount: string | null;
  soldShareCount: string | null;
  taxGainOrLoss: LedgerMoneyWire | null;
  taxTreatment: InvestmentTaxTreatment;
  taxableAddBack: LedgerMoneyWire | null;
  taxableGain: LedgerMoneyWire | null;
  totalTaxableIncome: LedgerMoneyWire | null;
  transactionCosts: LedgerMoneyWire | null;
  yearEndOwnershipBasisPoints: number | null;
  yearEndVotingBasisPoints: number | null;
}

export interface InvestmentLifecycleEventPageWire {
  items: InvestmentLifecycleEventWire[];
  page: InvestmentsPageWire;
}

export interface InvestmentLifecycleEventWire {
  accountingClassification: InvestmentAccountingClassification;
  acquisitionLotId: string | null;
  activityKind: InvestmentActivityKind;
  bankFact: InvestmentFactReferenceWire | null;
  bookGainOrLoss: LedgerMoneyWire | null;
  calculationId: string;
  capitalizedCost: LedgerMoneyWire | null;
  companyId: string;
  createdAt: string;
  createdBy: string;
  deductibleLoss: LedgerMoneyWire | null;
  dividendPortion: LedgerMoneyWire | null;
  documentFacts: InvestmentFactReferenceWire[];
  entitlementDate: string | null;
  evidenceDigest: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  exemptGain: LedgerMoneyWire | null;
  expectedSettlementAmount: LedgerMoneyWire;
  fifoCostBasisReduction: LedgerMoneyWire | null;
  fifoTaxBasisReduction: LedgerMoneyWire | null;
  fundEquityRatioBasisPoints: number | null;
  fundName: string | null;
  fundTaxStatementReference: string | null;
  grossAmount: LedgerMoneyWire | null;
  groupEvidenceReference: string | null;
  groupExceptionApplied: boolean | null;
  groupExceptionClaimed: boolean | null;
  id: string;
  incomeYear: number;
  interestPortion: LedgerMoneyWire | null;
  investmentKey: string;
  investmentKind: InvestmentKind;
  investmentName: string;
  lawfulDividendConfirmed: boolean | null;
  netProceeds: LedgerMoneyWire | null;
  nonDeductibleLoss: LedgerMoneyWire | null;
  openingFundEquityRatioBasisPoints: number | null;
  orgNumber: string | null;
  ownerAttested: boolean;
  payingCompanyName: string | null;
  positionCreated: boolean | null;
  positionId: string;
  proceeds: LedgerMoneyWire | null;
  purchaseAmount: LedgerMoneyWire | null;
  recognitionAccountingEntryId: string;
  recognitionDate: string;
  remainingCostBasis: LedgerMoneyWire | null;
  remainingShareCount: string | null;
  remainingTaxBasis: LedgerMoneyWire | null;
  settlementAccountingEntryId: string | null;
  settlementAmount: LedgerMoneyWire | null;
  settlementBalanceKind: InvestmentSettlementBalanceKind;
  settlementDate: string | null;
  settlementId: string | null;
  shareCount: string | null;
  soldShareCount: string | null;
  taxGainOrLoss: LedgerMoneyWire | null;
  taxTreatment: InvestmentTaxTreatment;
  taxableAddBack: LedgerMoneyWire | null;
  taxableGain: LedgerMoneyWire | null;
  totalTaxableIncome: LedgerMoneyWire | null;
  transactionCosts: LedgerMoneyWire | null;
  yearEndOwnershipBasisPoints: number | null;
  yearEndVotingBasisPoints: number | null;
}

export interface AcquisitionLotPageWire {
  items: AcquisitionLotWire[];
  page: InvestmentsPageWire;
}

export interface AcquisitionLotWire {
  acquisitionActionId: string;
  acquisitionDate: string;
  acquisitionYearFundEquityRatioBasisPoints: number | null;
  companyId: string;
  createdAt: string;
  createdBy: string;
  fundTaxStatementReference: string | null;
  id: string;
  originalCostBasis: LedgerMoneyWire;
  originalShareCount: string;
  originalTaxBasis: LedgerMoneyWire;
  positionId: string;
  remainingCostBasis: LedgerMoneyWire;
  remainingShareCount: string;
  remainingTaxBasis: LedgerMoneyWire;
}

export type InvestmentAccountingClassification = "subsidiary" | "associate" | "other_long_term" | "current_listed_share" | "current_fund";

export type InvestmentDocumentStatus = "attached" | "missing_accepted_warning" | "not_required";

export type InvestmentEvidenceMode = "linked_sources" | "manual_fallback";

export type InvestmentKind = "norwegian_private_company" | "norwegian_listed_share" | "norwegian_equity_fund";

export type InvestmentLotHistoryStatus = "complete" | "needs_reconstruction";

export type InvestmentMeasurementRule = "lower_of_cost_and_fair_value" | "cost_with_evidenced_impairment";

export type InvestmentSettlementBalanceKind = "purchase_payable" | "sale_receivable" | "dividend_receivable" | "fund_distribution_receivable";

export type InvestmentTaxTreatment = "fritaksmetoden";

export type InvestmentTradingProfile = "low_volume_non_active" | "active_or_high_volume" | "unknown";

export interface InvestmentPositionPageWire {
  items: InvestmentPositionWire[];
  page: InvestmentsPageWire;
}

export interface InvestmentPositionMovementWire {
  movement_date: string;
  movement_type: string;
  share_delta: string;
  [key: string]: unknown;
}

export interface InvestmentPositionWire {
  accountingClassification: InvestmentAccountingClassification;
  companyId: string;
  costBasis: LedgerMoneyWire;
  createdAt: string;
  createdBy: string;
  fundEquityRatioBasisPoints: number | null;
  fundTaxStatementReference: string | null;
  id: string;
  investmentKey: string;
  kind: InvestmentKind;
  lotHistoryStatus: InvestmentLotHistoryStatus;
  movementCount: number;
  movements: InvestmentPositionMovementWire[];
  name: string;
  orgNumber: string | null;
  shareCount: string;
  taxBasis: LedgerMoneyWire;
  taxTreatment: InvestmentTaxTreatment;
  updatedAt: string;
}

export interface InvestmentYearEndMeasurementPageWire {
  items: InvestmentYearEndMeasurementViewWire[];
  page: InvestmentsPageWire;
}

export interface InvestmentYearEndMeasurementViewWire {
  accountingEntryId: string | null;
  asOf: string;
  calculationId: string;
  closingBookValue: LedgerMoneyWire;
  companyId: string;
  createdAt: string;
  createdBy: string;
  evidenceDigest: string;
  id: string;
  impairmentAmount: LedgerMoneyWire;
  incomeYear: number;
  measurementRule: InvestmentMeasurementRule;
  observedOrRecoverableValue: LedgerMoneyWire;
  positionId: string;
  preMeasurementBookValue: LedgerMoneyWire;
  quantity: string;
  reversalAmount: LedgerMoneyWire;
  sourceBookCost: LedgerMoneyWire;
  taxBasis: LedgerMoneyWire;
  taxValue: LedgerMoneyWire;
}

export interface InvestmentsPageWire {
  hasMore: boolean;
  nextCursor: string | null;
}

export interface InvestmentsEconomicEventResultWire {
  eventId: string;
  expectedSettlementAmount: LedgerMoneyWire;
  positionId: string;
  recognitionAccountingEntryId: string;
  replayed: boolean;
  settlementBalanceKind: InvestmentSettlementBalanceKind;
}

export interface InvestmentsCashSettlementResultWire {
  eventId: string;
  replayed: boolean;
  settlementAccountingEntryId: string;
  settlementId: string;
}

export interface InvestmentsRecognizeSharePurchaseWire {
  accountingClassification: InvestmentAccountingClassification;
  acquisitionDate: string;
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  documentFacts?: InvestmentFactReferenceWire[];
  equalShareRightsConfirmed?: boolean | null;
  eventId: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  fundEquityRatioBasisPoints?: number | null;
  fundTaxStatementReference?: string | null;
  incomeYear: number;
  investmentKey: string;
  investmentKind: InvestmentKind;
  investmentName: string;
  nonActiveTradingConfirmed: boolean;
  orgNumber?: string | null;
  ownerAttested: boolean;
  purchaseAmount: LedgerMoneyWire;
  shareClassCode?: string | null;
  shareCount: string;
  singleShareClassConfirmed?: boolean | null;
  tradingProfile: InvestmentTradingProfile;
  transactionCosts: LedgerMoneyWire;
  unusualShareRightsAbsentConfirmed?: boolean | null;
}

export interface InvestmentsRecognizeShareSaleWire {
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  documentFacts?: InvestmentFactReferenceWire[];
  eventId: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  fundTaxStatementReference?: string | null;
  incomeYear: number;
  ownerAttested: boolean;
  positionId: string;
  proceeds: LedgerMoneyWire;
  saleDate: string;
  saleYearFundEquityRatioBasisPoints?: number | null;
  soldShareCount: string;
  transactionCosts: LedgerMoneyWire;
}

export interface InvestmentsRecognizeReceivedDividendWire {
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  declaredDate: string;
  documentFacts?: InvestmentFactReferenceWire[];
  eventId: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  grossAmount: LedgerMoneyWire;
  groupEvidenceReference?: string | null;
  groupExceptionClaimed: boolean;
  incomeYear: number;
  lawfulDividendConfirmed: boolean;
  ownerAttested: boolean;
  payingCompanyName: string;
  positionId: string;
  yearEndOwnershipBasisPoints?: number | null;
  yearEndVotingBasisPoints?: number | null;
}

export interface InvestmentsRecognizeReceivedFundDistributionWire {
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  documentFacts?: InvestmentFactReferenceWire[];
  entitlementDate: string;
  eventId: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  fundName: string;
  fundTaxStatementReference: string;
  grossAmount: LedgerMoneyWire;
  incomeYear: number;
  openingFundEquityRatioBasisPoints: number;
  ownerAttested: boolean;
  positionId: string;
}

export interface InvestmentsSettleCashWire {
  amount: LedgerMoneyWire;
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  documentFacts?: InvestmentFactReferenceWire[];
  eventId: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  incomeYear: number;
  ownerAttested: boolean;
  settlementDate: string;
  settlementId: string;
}

export interface InvestmentsYearEndMeasurementResultWire {
  accountingEntryId: string | null;
  closingBookValue: LedgerMoneyWire;
  measurementId: string;
  measurementRule: InvestmentMeasurementRule;
  positionId: string;
  replayed: boolean;
  taxBasis: LedgerMoneyWire;
  taxValue: LedgerMoneyWire;
}

export interface InvestmentsYearEndMeasurementWire {
  asOf: string;
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  documentFacts?: InvestmentFactReferenceWire[];
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  incomeYear: number;
  measurementId: string;
  observedOrRecoverableValue: LedgerMoneyWire;
  ownerAttested: boolean;
  positionId: string;
  taxValue: LedgerMoneyWire;
}

export interface InvestmentsCorrectionResultWire {
  correctionId: string;
  originalRecordId: string;
  replacementAccountingEntryId: string;
  replacementRecordId: string;
  replayed: boolean;
  reversalAccountingEntryId: string;
  targetKind: InvestmentCorrectionTargetKind;
}

export interface InvestmentsCorrectionWire {
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  correctionDate: string;
  correctionId: string;
  documentFacts?: InvestmentFactReferenceWire[];
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  incomeYear: number;
  originalActivityKind: InvestmentActivityKind;
  originalRecordId: string;
  originalSettlementId?: string | null;
  ownerAttested: boolean;
  reason: string;
  replacement: InvestmentsSharePurchaseRecognitionWire | InvestmentsShareSaleRecognitionWire | InvestmentsDividendRecognitionWire | InvestmentsFundDistributionRecognitionWire | InvestmentsCashSettlementWire;
  replacementSettlement?: InvestmentsReplacementCashSettlementWire | null;
  settlementCorrectionId?: string | null;
  targetKind: InvestmentCorrectionTargetKind;
}

export interface InvestmentsSharePurchaseRecognitionWire {
  accountingClassification: InvestmentAccountingClassification;
  acquisitionDate: string;
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  documentFacts?: InvestmentFactReferenceWire[];
  equalShareRightsConfirmed?: boolean | null;
  eventId: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  fundEquityRatioBasisPoints?: number | null;
  fundTaxStatementReference?: string | null;
  incomeYear: number;
  investmentKey: string;
  investmentKind: InvestmentKind;
  investmentName: string;
  nonActiveTradingConfirmed: boolean;
  orgNumber?: string | null;
  ownerAttested: boolean;
  purchaseAmount: LedgerMoneyWire;
  replacementKind: "share_purchase";
  shareClassCode?: string | null;
  shareCount: string;
  singleShareClassConfirmed?: boolean | null;
  tradingProfile: InvestmentTradingProfile;
  transactionCosts: LedgerMoneyWire;
  unusualShareRightsAbsentConfirmed?: boolean | null;
}

export interface InvestmentsShareSaleRecognitionWire {
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  documentFacts?: InvestmentFactReferenceWire[];
  eventId: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  fundTaxStatementReference?: string | null;
  incomeYear: number;
  ownerAttested: boolean;
  positionId: string;
  proceeds: LedgerMoneyWire;
  replacementKind: "share_sale";
  saleDate: string;
  saleYearFundEquityRatioBasisPoints?: number | null;
  soldShareCount: string;
  transactionCosts: LedgerMoneyWire;
}

export interface InvestmentsDividendRecognitionWire {
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  declaredDate: string;
  documentFacts?: InvestmentFactReferenceWire[];
  eventId: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  grossAmount: LedgerMoneyWire;
  groupEvidenceReference?: string | null;
  groupExceptionClaimed: boolean;
  incomeYear: number;
  lawfulDividendConfirmed: boolean;
  ownerAttested: boolean;
  payingCompanyName: string;
  positionId: string;
  replacementKind: "dividend_received";
  yearEndOwnershipBasisPoints?: number | null;
  yearEndVotingBasisPoints?: number | null;
}

export interface InvestmentsFundDistributionRecognitionWire {
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  documentFacts?: InvestmentFactReferenceWire[];
  entitlementDate: string;
  eventId: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  fundName: string;
  fundTaxStatementReference: string;
  grossAmount: LedgerMoneyWire;
  incomeYear: number;
  openingFundEquityRatioBasisPoints: number;
  ownerAttested: boolean;
  positionId: string;
  replacementKind: "fund_distribution_received";
}

export interface InvestmentsCashSettlementWire {
  amount: LedgerMoneyWire;
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  documentFacts?: InvestmentFactReferenceWire[];
  eventId: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  incomeYear: number;
  ownerAttested: boolean;
  replacementKind: "cash_settlement";
  settlementDate: string;
  settlementId: string;
}

export interface InvestmentsReplacementCashSettlementWire {
  amount: LedgerMoneyWire;
  bankFact?: InvestmentFactReferenceWire | null;
  companyId: string;
  documentFacts?: InvestmentFactReferenceWire[];
  eventId: string;
  evidenceMode: InvestmentEvidenceMode;
  evidenceReference: string;
  incomeYear: number;
  ownerAttested: boolean;
  replacementKind: "cash_settlement";
  settlementDate: string;
  settlementId: string;
}

export interface ShareSaleAllocationPageWire {
  items: ShareSaleAllocationWire[];
  page: InvestmentsPageWire;
}

export interface ShareSaleAllocationWire {
  acquisitionDate: string;
  allocatedBookCostBasis: LedgerMoneyWire;
  allocatedCostBasis: LedgerMoneyWire;
  allocatedNetProceeds: LedgerMoneyWire;
  allocatedShareCount: string;
  allocatedTaxBasis: LedgerMoneyWire;
  allocationOrder: number;
  averageFundEquityRatioBasisPoints: string | null;
  companyId: string;
  createdAt: string;
  createdBy: string;
  deductibleLoss: LedgerMoneyWire;
  exemptGain: LedgerMoneyWire;
  id: string;
  lotId: string;
  nonDeductibleLoss: LedgerMoneyWire;
  positionId: string;
  saleActionId: string;
  taxGainOrLoss: LedgerMoneyWire;
  taxableGain: LedgerMoneyWire;
}

export interface DocumentBackupObjectWire {
  byteLength: number | null;
  contentSha256: string | null;
  contentType: string;
  createdAt: string;
  createdBy: string;
  documentId: string;
  documentType: string;
  linkedTo: string;
  name: string;
  removalReason: string | null;
  removedAt: string | null;
  retentionYears: number;
  status: string;
  storageKey: string;
}

export interface DocumentBackupProjectionWire {
  companyId: string;
  incomeYear: number;
  objects: DocumentBackupObjectWire[];
}

export interface DocumentBeginUploadWire {
  byteLength: number;
  companyId: string;
  contentType: string;
  documentId: string;
  documentType: "bank_statement" | "accounting_document" | "corporate_document" | "authority_feedback";
  fileName: string;
  finalStatus?: "attached" | "generated_unsigned" | "signed_owner_attested" | "stored";
  headerBase64: string;
  incomeYear: number;
  linkedTo: string;
}

export interface DocumentListWire {
  documents: DocumentWire[];
}

export interface DocumentRemovalRequestWire {
  reason?: string;
}

export type DocumentTransferKind = "preview" | "download";

export interface DocumentTransferRequestWire {
  kind: DocumentTransferKind;
}

export interface DocumentTransferWire {
  document: DocumentWire;
  expiresInSeconds: number;
  kind: DocumentTransferKind;
  signedUrl: string;
}

export interface DocumentUploadTransferWire {
  bucket: "company-documents";
  document: DocumentWire;
  signedUrl: string;
  storageKey: string;
  token: string;
}

export interface DocumentWire {
  byteLength: number | null;
  companyId: string;
  contentSha256: string | null;
  contentType: string;
  createdAt: string;
  createdBy: string;
  documentType: string;
  id: string;
  incomeYear: number;
  linkedTo: string;
  name: string;
  removalReason: string | null;
  removedAt: string | null;
  retentionYears: number;
  status: string;
  storageKey: string;
}

export type AnnualCloseEventKind = "signing_requested" | "rejected" | "superseded";

export interface AnnualCloseEventWire {
  companyId: string;
  decisionHash: string;
  documentSetId: string;
  eventId: string;
  eventKind: AnnualCloseEventKind;
  metadata: Record<string, string>;
}

export interface AnnualCloseFinalizationWire {
  companyId: string;
  decisionHash: string;
  documentSetId: string;
  finalizationId: string;
}

export interface AnnualCloseLifecycleWire {
  companyId: string;
  decisionHash: string;
  decisionId: string;
  documentSetId: string;
  finalizationId: string | null;
  generatedArtifactHashes: Record<string, string>;
  incomeYear: number;
  replayed: boolean;
  signedArtifactHashes: Record<string, string>;
  state: OwnerDividendState;
}

export interface AnnualCloseProposalWire {
  annualBasis: CorporateAnnualBasisWire;
  annualResultAllocationOre: number;
  boardMeeting: CorporateBoardMeetingWire;
  boardParticipants: CorporateBoardParticipantWire[];
  company: CorporateCompanyFactsWire;
  companyId: string;
  decisionId: string;
  documentSetId: string;
  fullBoardParticipationConfirmed: boolean;
  generalMeeting: CorporateGeneralMeetingWire;
  incomeYear: number;
  oneShareClassConfirmed: boolean;
  prudentEquityAndLiquidityConfirmed: boolean;
  reviewedFacts: CorporateReviewedFactsWire;
  shareholderBallots: CorporateShareholderBallotWire[];
  shareholders: CorporateShareholderWire[];
  supportedDividendBasisConfirmed: boolean;
  unanimousBoardConfirmed: boolean;
}

export interface AnnualCloseSignedArtifactWire {
  artifactKind: "annual_board_minutes" | "annual_general_meeting_minutes";
  byteLength: number;
  companyId: string;
  contentSha256: string;
  decisionHash: string;
  documentSetId: string;
  filename: string;
  signedArtifactId: string;
  signedDocumentId: string;
  unsignedArtifactId: string;
}

export type BoardRole = "chair" | "member";

export type BoardTreatmentMethod = "physical" | "video" | "written";

export interface BankLoanEventFactsWire {
  factType: "bank_loan";
  fee: LedgerMoneyWire;
  interest: LedgerMoneyWire;
  lenderAllocationConfirmed: boolean;
  lenderName: string;
  noComplexTerms: boolean;
  norwegianLender: boolean;
  ordinaryTerms: boolean;
  principal: LedgerMoneyWire;
  signedAgreement: boolean;
}

export interface CashCapitalIncreaseEventFactsWire {
  bindingSubscription: boolean;
  cashOnly: boolean;
  factType: "cash_capital_increase";
  fullTimelyPayment: boolean;
  independentConfirmation: boolean;
  issueCostsResolved: boolean;
  issuedShareCount: number;
  noDirectUseException: boolean;
  noSpecialTerms: boolean;
  nominalIncrease: LedgerMoneyWire;
  norwegianSubscribersOnly: boolean;
  registerReconciled: boolean;
  sharePremium: LedgerMoneyWire;
  singleOrdinaryClass: boolean;
}

export interface CorporateAnnualBasisWire {
  annualDataSha256: string;
  availableDistributionOre: number;
  cashOre: number;
  equityOre: number;
  governanceBasisSha256: string;
  incomeYear: number;
  latestApproved: boolean;
  resultAfterTaxOre: number;
  sourceId: string;
}

export type CorporateArtifactKind = "dividend_board_proposal" | "dividend_general_meeting_minutes" | "annual_board_minutes" | "annual_general_meeting_minutes";

export interface CorporateArtifactRecordWire {
  artifactId: string;
  artifactKind: CorporateArtifactKind;
  byteLength: number;
  companyId: string;
  contentSha256: string;
  createdAt: string;
  createdBy: string;
  documentId: string;
  documentSetId: string;
  incomeYear: number;
  supersedesArtifactId: string | null;
  variant: CorporateArtifactVariant;
}

export type CorporateArtifactVariant = "unsigned" | "signed_owner_attested";

export interface CorporateBoardMeetingWire {
  meetingDate: string;
  meetingTime: string;
  place: string;
  treatmentMethod: BoardTreatmentMethod;
}

export interface CorporateBoardParticipantWire {
  name: string;
  order: number;
  participantId: string;
  role: BoardRole;
}

export interface CorporateCanonicalBoardParticipantWire {
  name: string;
  participantId: string;
  role: BoardRole;
}

export interface CorporateCanonicalDecisionWire {
  annualBasisYear: number;
  annualCloseSourceId: string;
  annualResultAllocationOre: number;
  boardMeeting: CorporateBoardMeetingWire;
  boardParticipants: CorporateCanonicalBoardParticipantWire[];
  companyId: string;
  confirmations: CorporateOwnerDividendConfirmationsWire;
  decisionHash: string;
  decisionId: string;
  decisionKind: "owner_dividend" | "annual_close";
  dividend: CorporateOwnerDividendFactsWire | null;
  documentSetId: string;
  financialTotals: CorporateFinancialTotalsWire;
  generalMeeting: CorporateGeneralMeetingWire;
  incomeYear: number;
  legalName: string;
  oneShareClassConfirmed: boolean;
  organizationNumber: string;
  shareholders: CorporateCanonicalShareholderWire[];
  sourceHash: string;
  templateFamily: string;
  templateVersion: string;
  totalCompanyShares: number;
}

export interface CorporateCanonicalShareholderWire {
  name: string;
  representedShareCount: number;
  shareCount: number;
  shareholderId: string;
  vote: ShareholderVote;
}

export type CorporateDecisionKind = "owner_dividend" | "annual_close";

export interface CorporateDecisionFactsWire {
  annualBasis: CorporateAnnualBasisWire;
  company: CorporateCompanyFactsWire;
  reviewedFacts: CorporateReviewedFactsWire;
  shareholders: CorporateShareholderWire[];
}

export interface CorporateDecisionRecordWire {
  annualCloseSourceId: string;
  canonicalInput: Record<string, unknown>;
  companyId: string;
  createdAt: string;
  createdBy: string;
  decisionHash: string;
  decisionId: string;
  decisionKind: CorporateDecisionKind;
  documentSetId: string;
  incomeYear: number;
  sourceHash: string;
  supersedesDecisionId: string | null;
}

export interface CorporateDocumentReadinessBlockerWire {
  code: string;
  message: string;
}

export interface CorporateDocumentReadinessWire {
  accountingPolicyVersion: string | null;
  annualSubmissionReady: boolean;
  blockers: CorporateDocumentReadinessBlockerWire[];
  companyId: string;
  currentSourceHash: string | null;
  currentSourceMatches: boolean | null;
  decisionHash: string | null;
  decisionId: string | null;
  decisionKind: CorporateDecisionKind;
  declaredAmountOre: number | null;
  documentSetId: string | null;
  finalizationId: string | null;
  finalized: boolean;
  generatedArtifactHashes: Record<string, string>;
  incomeYear: number;
  paidAmountOre: number | null;
  readyForSigning: boolean;
  remainingAmountOre: number | null;
  requiredSigners: Record<string, string[]>;
  signedArtifactHashes: Record<string, string>;
  sourceHash: string | null;
  state: OwnerDividendState | null;
}

export interface CorporateDocumentSetRecordWire {
  companyId: string;
  createdAt: string;
  createdBy: string;
  decisionHash: string;
  decisionId: string;
  documentSetId: string;
  incomeYear: number;
  supersedesDocumentSetId: string | null;
  templateFamily: string;
  templateVersion: string;
}

export interface CorporateEventRecordWire {
  actorId: string;
  artifactId: string | null;
  companyId: string;
  contentSha256: string | null;
  createdAt: string;
  decisionHash: string;
  decisionId: string;
  documentSetId: string;
  eventId: string;
  eventKind: string;
  idempotencyKey: string;
  incomeYear: number;
  metadata: Record<string, unknown>;
  occurredAt: string;
}

export interface CorporateFinalizationRecordWire {
  accountingEntryId: string | null;
  accountingPolicyVersion: string | null;
  annualCloseSourceId: string | null;
  companyId: string;
  createdAt: string;
  createdBy: string;
  decisionHash: string;
  decisionId: string;
  finalizationId: string;
  finalizationKind: string;
  holdingActionId: string | null;
  incomeYear: number;
  signedArtifactHashes: Record<string, string>;
}

export interface CorporateCompanyFactsWire {
  legalName: string;
  organizationNumber: string;
}

export interface CorporateFinancialTotalsWire {
  availableDistributionOre: number;
  cashOre: number;
  equityOre: number;
  resultAfterTaxOre: number;
}

export interface CorporateGeneralMeetingWire {
  chairName: string;
  coSignerName: string;
  meetingDate: string;
  meetingForm: MeetingForm;
  meetingTime: string;
  place: string;
}

export interface CorporateOwnerDividendConfirmationsWire {
  fullBoardParticipation: boolean;
  fullShareRepresentation: boolean;
  latestApprovedAnnualAccounts: boolean;
  proportionalAllocation: boolean;
  prudentEquityAndLiquidity: boolean;
  supportedDividendBasis: boolean;
  unanimousBoard: boolean;
  unanimousShareholders: boolean;
}

export interface CorporateOwnerDividendFactsWire {
  allocations: OwnerDividendAllocationWire[];
  amountOre: number;
  liquidityAfterPaymentOre: number;
  paymentDate: string;
}

export interface CorporateLifecycleSnapshotWire {
  artifacts: CorporateArtifactRecordWire[];
  decisions: CorporateDecisionRecordWire[];
  documentSets: CorporateDocumentSetRecordWire[];
  events: CorporateEventRecordWire[];
  finalizations: CorporateFinalizationRecordWire[];
}

export interface CorporateReviewedFactsWire {
  annualDataSha256: string;
  availableDistributionOre: number;
  governanceBasisSha256: string;
  legalName: string;
  organizationNumber: string;
  shareholders: CorporateReviewedShareholderWire[];
  totalCompanyShares: number;
}

export interface CorporateReviewedShareholderWire {
  name: string;
  shareCount: number;
  shareholderId: string;
}

export interface CorporateShareholderBallotWire {
  representedShareCount: number;
  shareholderId: string;
  vote: ShareholderVote;
}

export interface CorporateShareholderWire {
  name: string;
  order: number;
  shareCount: number;
  shareholderId: string;
}

export interface GroupContributionEventFactsWire {
  afterTaxAccountingAmount: LedgerMoneyWire;
  bothNorwegian: boolean;
  consolidationNotRequired: boolean;
  corporateApprovalEvidenced: boolean;
  counterpartyName: string;
  counterpartyOrganizationNumber: string;
  distributionCapacityConfirmed: boolean;
  factType: "group_contribution";
  grossTaxAmount: LedgerMoneyWire;
  impairmentCleared: boolean;
  noEquityMethod: boolean;
  noNonCashOrCircularRoute: boolean;
  ownershipBasisPoints: number;
  perspective: SupportedCorporatePerspective;
  postAcquisitionIncomeProved: boolean;
  prudentEquityAndLiquidityConfirmed: boolean;
  relatedTax: LedgerMoneyWire;
  relationship: SupportedCorporateRelationship;
  votingBasisPoints: number;
  yearEndGroupEligibilityProved: boolean;
}

export interface IntercompanyLoanEventFactsWire {
  approvalOrExemptionEvidenced: boolean;
  armLengthConfirmed: boolean;
  counterpartyName: string;
  counterpartyOrganizationNumber: string;
  factType: "intercompany_loan";
  interestLimitationCleared: boolean;
  noComplexTerms: boolean;
  norwegianCounterparty: boolean;
  ordinaryTerms: boolean;
  perspective: SupportedCorporatePerspective;
  principal: LedgerMoneyWire;
  relationship: SupportedCorporateRelationship;
  signedAgreement: boolean;
}

export interface LossCoverageCapitalReductionEventFactsWire {
  factType: "loss_coverage_capital_reduction";
  lossEvidenced: boolean;
  lossOnly: boolean;
  newShareCapital: LedgerMoneyWire;
  noCreditorNotice: boolean;
  noSimultaneousCapitalChange: boolean;
  noValueTransfer: boolean;
  nominalReduction: LedgerMoneyWire;
  oldShareCapital: LedgerMoneyWire;
  otherEquityExhausted: boolean;
  registerReconciled: boolean;
  singleOrdinaryClass: boolean;
  unchangedOwnersAndShareCount: boolean;
}

export type MeetingForm = "physical" | "video";

export interface OwnerDividendAllocationWire {
  amountOre: number;
  shareholderId: string;
}

export interface OwnerDividendApprovalWire {
  approvalEventId: string;
  companyId: string;
  decisionHash: string;
  documentSetId: string;
}

export interface OwnerDividendArtifactWire {
  artifactId: string;
  artifactKind: CorporateArtifactKind;
  byteLength: number;
  contentSha256: string;
  documentId: string;
}

export interface OwnerDividendDocumentsWire {
  artifacts: OwnerDividendArtifactWire[];
  companyId: string;
  decisionHash: string;
  documentSetId: string;
}

export type OwnerDividendEventKind = "signing_requested" | "rejected" | "superseded";

export interface OwnerDividendEventWire {
  companyId: string;
  decisionHash: string;
  documentSetId: string;
  eventId: string;
  eventKind: OwnerDividendEventKind;
  metadata: Record<string, string>;
}

export interface OwnerDividendFinalizationWire {
  companyId: string;
  decisionHash: string;
  documentSetId: string;
  finalizationId: string;
  holdingActionId: string;
  incomeYear: number;
  ledgerEntryId: string;
}

export interface OwnerDividendLifecycleWire {
  accountingEntryId: string | null;
  companyId: string;
  decisionHash: string;
  decisionId: string;
  declaredAmountOre: number;
  documentSetId: string;
  finalizationId: string | null;
  incomeYear: number;
  paidAmountOre: number;
  remainingAmountOre: number;
  replayed: boolean;
  state: OwnerDividendState;
}

export interface OwnerDividendPaymentWire {
  bankTransactionId: string;
  companyId: string;
  decisionHash: string;
  documentSetId: string;
  holdingActionId: string;
  incomeYear: number;
  ledgerEntryId: string;
  paymentEventId: string;
}

export interface OwnerDividendProposalWire {
  annualBasis: CorporateAnnualBasisWire;
  boardMeeting: CorporateBoardMeetingWire;
  boardParticipants: CorporateBoardParticipantWire[];
  company: CorporateCompanyFactsWire;
  companyId: string;
  decisionId: string;
  dividendAmountOre: number;
  documentSetId: string;
  fullBoardParticipationConfirmed: boolean;
  generalMeeting: CorporateGeneralMeetingWire;
  incomeYear: number;
  oneShareClassConfirmed: boolean;
  paymentDate: string;
  prudentEquityAndLiquidityConfirmed: boolean;
  reviewedFacts: CorporateReviewedFactsWire;
  shareholderBallots: CorporateShareholderBallotWire[];
  shareholders: CorporateShareholderWire[];
  supportedDividendBasisConfirmed: boolean;
  unanimousBoardConfirmed: boolean;
}

export interface OwnerDividendSignedArtifactWire {
  artifactKind: "dividend_board_proposal" | "dividend_general_meeting_minutes";
  byteLength: number;
  companyId: string;
  contentSha256: string;
  decisionHash: string;
  documentSetId: string;
  filename: string;
  signedArtifactId: string;
  signedDocumentId: string;
  unsignedArtifactId: string;
}

export interface OwnerLoanEventFactsWire {
  approvalOrExemptionEvidenced: boolean;
  factType: "owner_loan";
  interestAndTaxTreatmentCleared: boolean;
  noComplexTerms: boolean;
  noSecurityOrConversion: boolean;
  norwegianOwner: boolean;
  ordinaryTerms: boolean;
  ownerIsRecordedShareholder: boolean;
  ownerName: string;
  principal: LedgerMoneyWire;
  signedAgreement: boolean;
}

export type OwnerDividendState = "proposed" | "documents_registered" | "facts_approved" | "signing_requested" | "signed_owner_attested" | "finalized" | "partially_paid" | "paid" | "rejected" | "superseded";

export interface ProposedOwnerDividendWire {
  artifacts: RenderedCorporateArtifactWire[];
  decision: CorporateCanonicalDecisionWire;
  replayed: boolean;
  state: OwnerDividendState;
}

export interface ProposedAnnualCloseWire {
  artifacts: RenderedCorporateArtifactWire[];
  decision: CorporateCanonicalDecisionWire;
  replayed: boolean;
  state: OwnerDividendState;
}

export interface RenderedCorporateArtifactWire {
  artifactKind: CorporateArtifactKind;
  byteLength: number;
  contentBase64: string;
  contentSha256: string;
  decisionHash: string;
  filename: string;
}

export interface RecordedShareholderLoanWire {
  accountingEntryId: string;
  actionId: string;
  amountOre: number;
  bankTransactionId: string | null;
  companyId: string;
  counterpartyName: string;
  direction: ShareholderLoanDirection;
  documentId: string | null;
  documentStatus: ShareholderLoanDocumentStatus;
  incomeYear: number;
  interestModelled: boolean;
  loanDate: string;
  relatedPartySecurity: boolean;
  replayed: boolean;
}

export interface RecordedSupportedCorporateEventWire {
  accountingEntryId: string;
  bankTransactionId: string | null;
  canonicalFacts: Record<string, unknown>;
  companyId: string;
  correctionOfEventId: string | null;
  documentFacts: SupportedCorporateDocumentFactWire[];
  eventDate: string;
  eventId: string;
  eventKind: SupportedCorporateEventKind;
  eventReference: string;
  factsSha256: string;
  finalizationSha256: string;
  incomeYear: number;
  lifecycleState: "finalized";
  phase: SupportedCorporateEventPhase;
  policyVersion: "corporate-governance-supported-events-2026.1";
  recordedAt: string;
  replayed: boolean;
  signedArtifactHashes: Record<string, string>;
}

export interface ReverseSupportedCorporateEventWire {
  companyId: string;
  correctionDocumentFact: SupportedCorporateDocumentFactWire;
  incomeYear: number;
  reason: string;
  reversalDate: string;
}

export interface ReversedSupportedCorporateEventWire {
  companyId: string;
  incomeYear: number;
  originalAccountingEntryId: string;
  originalEventId: string;
  replayed: boolean;
  reversalAccountingEntryId: string;
  reversedAt: string;
}

export type ShareholderLoanDirection = "shareholder_to_company" | "company_to_corporate_shareholder" | "company_to_personal_shareholder";

export type ShareholderLoanDocumentStatus = "attached" | "missing_accepted_warning" | "not_required";

export interface ShareholderLoanWire {
  actionId: string;
  amount: LedgerMoneyWire;
  bankTransactionId: string | null;
  companyId: string;
  counterpartyName: string;
  direction: ShareholderLoanDirection;
  documentId: string | null;
  documentStatus: ShareholderLoanDocumentStatus;
  incomeYear: number;
  interestModelled: boolean;
  ledgerEntryId: string;
  loanDate: string;
  relatedPartySecurity: boolean;
}

export type ShareholderVote = "for" | "against" | "abstain";

export interface SupportedCorporateBankFactWire {
  signedAmount: LedgerMoneyWire;
  sourceSha256: string;
  transactionDate: string;
  transactionId: string;
}

export interface SupportedCorporateDocumentFactWire {
  contentSha256: string;
  documentId: string;
  evidenceKind: SupportedCorporateEvidenceKind;
  revision: number;
}

export type SupportedCorporateEvidenceKind = "signed_decision" | "signed_agreement" | "amended_articles" | "contribution_confirmation" | "registration_receipt" | "shareholder_register" | "tax_calculation" | "lender_statement" | "correction_memo";

export type SupportedCorporateEventKind = "cash_capital_increase" | "loss_coverage_capital_reduction" | "intercompany_loan" | "owner_loan" | "bank_loan" | "group_contribution";

export type SupportedCorporateEventPhase = "binding_subscription" | "restricted_payment" | "registered" | "decided_not_registered" | "first_recognized_after_registration" | "funding" | "disbursement" | "payment" | "decision";

export interface SupportedCorporateEventWire {
  bankFact?: SupportedCorporateBankFactWire | null;
  companyId: string;
  documentFacts: SupportedCorporateDocumentFactWire[];
  eventDate: string;
  eventId: string;
  eventKind: SupportedCorporateEventKind;
  eventReference: string;
  facts: CashCapitalIncreaseEventFactsWire | LossCoverageCapitalReductionEventFactsWire | IntercompanyLoanEventFactsWire | OwnerLoanEventFactsWire | BankLoanEventFactsWire | GroupContributionEventFactsWire;
  incomeYear: number;
  phase: SupportedCorporateEventPhase;
  shareholderRegisterFact?: SupportedCorporateSourceFactWire | null;
  taxCalculationFact?: SupportedCorporateSourceFactWire | null;
}

export type SupportedCorporatePerspective = "lender" | "borrower" | "giver" | "recipient";

export type SupportedCorporateRelationship = "parent_to_subsidiary" | "subsidiary_to_parent" | "sister_to_sister" | "other_same_group";

export interface SupportedCorporateSourceFactWire {
  factSha256: string;
  recordId: string;
  revision: number;
}

export interface AcceptBankFileWire {
  companyId: string;
  documentSha256: string;
  incomeYear: number;
}

export interface AcceptBankSuggestionWire {
  acceptanceId: string;
  bankTransactionId: string;
  companyId: string;
  expectedRuleVersion: string;
  expectedSuggestion: BankSuggestionKind;
  incomeYear: number;
}

export interface AcceptedBankSuggestionWire {
  acceptanceId: string;
  acceptedAt: string;
  acceptedBy: string;
  accountingEntryId: string;
  bankTransactionId: string;
  replayed: boolean;
  suggestion: BankSuggestionWire;
}

export interface BankAccountWire {
  accountId: string;
  accountKind: string;
  connectionId: string;
  currency: "NOK";
  displayName: string;
  earliestCoveredDate: string | null;
  lastSuccessAt: string | null;
  latestCoveredDate: string | null;
  maskedAccount: string;
  status: string;
}

export interface BankConnectionActionWire {
  companyId: string;
  connectorId: string;
  incomeYear: number;
}

export interface BankConnectionListWire {
  items: BankConnectionWire[];
}

export interface BankConnectionWire {
  accounts: BankAccountWire[];
  companyId: string;
  connectionId: string;
  connectorId: string;
  consentExpiresOn: string | null;
  lastFailureCode: string | null;
  lastSuccessAt: string | null;
  status: string;
}

export interface BankConsentRedirectWire {
  redirectUrl: string;
  state: string;
}

export interface BankFileColumnMappingWire {
  amount: string;
  balance?: string | null;
  bookingDate: string;
  reference?: string | null;
  state?: string | null;
  text: string;
  valueDate?: string | null;
}

export interface BankFilePreviewResultWire {
  accountMask: string | null;
  closingBalance: LedgerMoneyWire | null;
  correctionCount: number;
  currency: "NOK";
  documentSha256: string;
  duplicateCount: number;
  ignoredCount: number;
  intervalEnd: string;
  intervalStart: string;
  openingBalance: LedgerMoneyWire | null;
  replayed: boolean;
  sourceFileId: string;
  transactionCount: number;
}

export interface BankFilePreviewWire {
  accountId: string;
  columnMapping?: BankFileColumnMappingWire | null;
  companyId: string;
  content: string;
  dataFormat: SupportedBankDataFormat;
  filename: string;
  incomeYear: number;
  sourceFileId: string;
}

export interface BankStatementImportResultWire {
  duplicateCount: number;
  importedCount: number;
  replayed: boolean;
}

export interface BankStatementImportWire {
  companyId: string;
  dataFormat: SupportedBankDataFormat;
  incomeYear: number;
  statementText: string;
}

export interface BankSuggestionAcceptancePageWire {
  items: AcceptedBankSuggestionWire[];
  page: BankingPageWire;
}

export type BankSuggestionKind = "BANK_FEE" | "SYSTEM_SUBSCRIPTION" | "DEPOSIT_INTEREST";

export interface BankSuggestionWire {
  kind: string;
  reason: string;
  ruleVersion: string;
}

export type BankSyncMode = "INITIAL_BACKFILL" | "NIGHTLY" | "ON_DEMAND" | "ANNUAL_CLOSE" | "RECOVERY";

export interface BankSyncResultWire {
  attemptId: string;
  duplicateCount: number;
  importedCount: number;
  pageCount: number;
  replayed: boolean;
  updatedCount: number;
}

export interface BankSyncWire {
  companyId: string;
  connectorId: string;
  dateFrom: string;
  dateTo: string;
  incomeYear: number;
  mode: BankSyncMode;
}

export interface BankTransactionPageWire {
  items: BankTransactionWire[];
  page: BankingPageWire;
}

export interface BankTransactionWire {
  amount: LedgerMoneyWire;
  balance: LedgerMoneyWire | null;
  companyId: string;
  createdAt: string;
  incomeYear: number;
  matchedActionReference: string | null;
  matchedEntryId: string | null;
  sourceHash: string;
  suggestion: BankSuggestionWire | null;
  text: string;
  transactionDate: string;
  transactionId: string;
  warningAccepted: boolean;
}

export interface BankingPageWire {
  hasMore: boolean;
  nextCursor: string | null;
}

export type SupportedBankDataFormat = "CSV" | "CAMT053";

export interface StartBankConnectionWire {
  bankKey: string;
  companyId: string;
  connectionId: string;
  connectorId: string;
  incomeYear: number;
  returnUrl: string;
}

export interface AnnualCheckoutCommandWire {
  companyId: string;
  consentVersion: string;
  incomeYear: number;
  offerVersion: string;
  purchaseAccepted: boolean;
  recurringConsent: boolean;
  termsDigest: string;
}

export interface AnnualCheckoutObservationCommandWire {
  companyId: string;
  purchaseId: string;
}

export interface AnnualCheckoutWire {
  capturedMinor: number;
  checkoutUrl: string | null;
  companyId: string;
  incomeYear: number;
  offer: AnnualBillingOfferWire;
  purchaseId: string;
  refundedMinor: number;
  status: AnnualPurchaseStatus;
}

export interface AnnualAgreementCleanupCommandWire {
  companyId: string;
  purchaseId: string;
}

export interface AnnualAgreementCleanupWire {
  companyId: string;
  purchaseId: string;
  status: "deferred" | "pending" | "unknown" | "confirmed";
}

export interface AnnualBillingOfferWire {
  companyId: string;
  currency: "NOK";
  exportThrough: string;
  grossMinor: number;
  incomeYear: number;
  netMinor: number;
  offerVersion: string;
  paidThrough: string;
  priceChangeNoticeBy: string;
  renewalDate: string;
  renewalReminderBy: string;
  termsDigest: string;
  termsText: string;
  vatBasisPoints: number;
  vatMinor: number;
}

export interface AnnualPurchaseSummaryWire {
  acceptedAt: string;
  capturedAt: string | null;
  capturedMinor: number;
  companyId: string;
  currency: "NOK";
  exportThrough: string;
  grossMinor: number;
  incomeYear: number;
  netMinor: number;
  offerVersion: string;
  paidThrough: string;
  purchaseId: string;
  recurringConsent: boolean;
  refundedMinor: number;
  renewalCanceledAt: string | null;
  renewalDate: string;
  status: AnnualPurchaseStatus;
  termsDigest: string;
  termsText: string;
  vatBasisPoints: number;
  vatMinor: number;
}

export type AnnualPurchaseStatus = "pending" | "paid" | "failed" | "refunded";

export interface AnnualBillingSnapshotWire {
  nextPurchaseId: string | null;
  offer: AnnualBillingOfferWire;
  purchases: AnnualPurchaseSummaryWire[];
}

export interface AnnualRenewalCancellationCommandWire {
  companyId: string;
  purchaseId: string;
}

export interface AnnualRenewalCancellationWire {
  cancellationId: string;
  companyId: string;
  effectiveAt: string;
  exportThrough: string;
  incomeYear: number;
  paidThrough: string;
  purchaseId: string;
  requestedAt: string;
}

export interface BillingAccountWire {
  companyId: string;
  createdAt: string;
  filingPackageNok: number;
  filingPackagePaid: boolean;
  filingPackagePaymentReference: string | null;
  founderCohortNumber: number | null;
  monthlyNok: number;
  noChargeReason: string | null;
  pricingPlan: BillingPlan;
  providerCustomerReference: string | null;
  refundCompleted: boolean;
  refundEligible: boolean;
  refundProviderReference: string | null;
  subscriptionActive: boolean;
  subscriptionProviderReference: string | null;
  supportedCase: boolean;
  updatedAt: string;
  updatedBy: string;
}

export interface BillingCompanyWire {
  companyId: string;
}

export interface BillingConfigureWire {
  companyId: string;
  founderCohortNumber?: number | null;
  pricingPlan: BillingPlan;
}

export interface BillingEntitlementDecisionWire {
  allowed: boolean;
  billingExempt: boolean;
  chargeAllowed: boolean;
  companyId: string;
  incomeYear: number;
  message: string;
  obligation: BillingObligation;
  pilotEntitlementId: string | null;
  readinessAllowed: boolean;
  status: BillingStatus;
}

export interface BillingFilingPackageWire {
  companyId: string;
  incomeYear: number;
  obligation?: BillingObligation;
}

export type BillingObligation = "aksjonaerregisteroppgaven" | "skattemelding" | "aarsregnskap";

export type BillingPaymentKind = "subscription" | "subscription_cancellation" | "filing_package" | "refund";

export interface BillingPaymentEventWire {
  amountNok: number;
  companyId: string;
  createdAt: string;
  createdBy: string;
  eventId: string;
  idempotencyKey: string;
  incomeYear: number | null;
  kind: BillingPaymentKind;
  provider: string;
  providerReference: string;
  replayed: boolean;
  status: BillingPaymentStatus;
}

export type BillingPaymentStatus = "created" | "succeeded" | "failed" | "refunded" | "canceled";

export interface BillingPilotEntitlementCommandWire {
  billingExempt: boolean;
  companyId: string;
  entitlementId?: string | null;
  evidenceReference: string;
  expiresAt: string;
  incomeYear: number;
  startsAt: string;
  status: ProductionPilotStatus;
  systemUserRequestId: string;
  userId: string;
}

export interface BillingPilotEntitlementWire {
  approvedBy: string;
  billingExempt: boolean;
  caseProfile: string;
  companyId: string;
  createdAt: string;
  entitlementId: string;
  evidenceReference: string;
  expiresAt: string;
  incomeYear: number;
  obligation: BillingObligation;
  startsAt: string;
  status: ProductionPilotStatus;
  systemUserExternalReference: string;
  systemUserRequestId: string;
  updatedAt: string;
  userId: string;
}

export type BillingPlan = "founder" | "standard";

export interface BillingPricingWire {
  filingPackageNok: number;
  monthlyNok: number;
  plan: BillingPlan;
}

export interface BillingSnapshotWire {
  accounts: BillingAccountWire[];
  paymentEvents: BillingPaymentEventWire[];
  pilotEntitlements: BillingPilotEntitlementWire[];
  pricing: BillingPricingWire[];
}

export type BillingStatus = "annual_billing_unavailable" | "active" | "subscription_required" | "filing_package_required" | "ready_for_production_filing" | "unsupported_case" | "refund_eligible" | "pilot_entitlement_active";

export interface BillingUnsupportedWire {
  companyId: string;
  reason: string;
}

export type ProductionPilotStatus = "pending" | "active" | "suspended" | "completed" | "revoked";

export interface MarketingFunnelReportResponse {
  counts: Record<string, number>;
  medianSeconds: Record<string, number | number | null>;
  rates: Record<string, number | number | null>;
  repeatedSignals: MarketingRepeatedSignalWire[];
  supportBySurface: Record<string, number>;
  windowEnd: string;
  windowStart: string;
}

export interface MarketingMeasurementEventResponse {
  accepted: true;
  duplicate: boolean;
}

export interface MarketingMeasurementEventWire {
  anonymousSessionHash: string;
  campaignSource: "direct" | "organic" | "community" | "partner" | "approved_campaign" | "unknown";
  clientEventId: string;
  consentVersion: "marketing-analytics-v1";
  event: "home_view" | "eligibility_start" | "provisional_supported" | "provisional_clarify" | "provisional_blocked" | "definitive_eligible" | "definitive_blocked" | "signup_start" | "unsupported_exit";
  firstLayerNoticeSha256: string;
  firstLayerNoticeVersion: string;
  privacyNoticeSha256: string;
  privacyNoticeVersion: string;
  reason: "unknown_material_facts" | "unsupported_company" | "unsupported_activity" | "missing_required_facts" | "new_unsupported_condition" | null;
  releaseSha256: string;
  surface: "homepage" | "eligibility" | "signup";
}

export interface MarketingMeasurementWithdrawalRequest {
  anonymousSessionHash: string;
}

export interface MarketingMeasurementWithdrawalResponse {
  deletedEventCount: number;
}

export interface MarketingRepeatedSignalWire {
  count: number;
  event: "home_view" | "eligibility_start" | "provisional_supported" | "provisional_clarify" | "provisional_blocked" | "definitive_eligible" | "definitive_blocked" | "signup_start" | "unsupported_exit";
  reason: "unknown_material_facts" | "unsupported_company" | "unsupported_activity" | "missing_required_facts" | "new_unsupported_condition";
  surface: "homepage" | "eligibility" | "signup";
}

export interface ProblemDetails {
  code: string;
  detail: string;
  instance: string;
  requestId: string;
  status: number;
  title: string;
  type: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function hasOnlyProperties(
  value: Record<string, unknown>,
  allowedProperties: readonly string[],
): boolean {
  return Object.keys(value).every((property) => allowedProperties.includes(property));
}

function isUuid(value: unknown): value is string {
  return typeof value === "string"
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(value);
}

function isDateTime(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/u.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, , offsetHourText, offsetMinuteText] = match;
  const [year, month, day, hour, minute, second] = [yearText, monthText, dayText, hourText, minuteText, secondText].map(Number);
  if (hour > 23 || minute > 59 || second > 59) return false;
  if (offsetHourText !== undefined && (Number(offsetHourText) > 23 || Number(offsetMinuteText) > 59)) return false;
  const calendar = new Date(0);
  calendar.setUTCHours(0, 0, 0, 0);
  calendar.setUTCFullYear(year, month - 1, day);
  calendar.setUTCHours(hour, minute, second, 0);
  return calendar.getUTCFullYear() === year
    && calendar.getUTCMonth() === month - 1
    && calendar.getUTCDate() === day
    && !Number.isNaN(Date.parse(value));
}

function isSystemBoundaryStatus(value: unknown): value is SystemBoundaryStatus {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["apiVersion","service","status"]) &&
    typeof value.apiVersion === "string" &&
    typeof value.service === "string" &&
    value.status === "AVAILABLE"
  );
}

function isCompanyContext(value: unknown): value is CompanyContext {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["aal","address","admittedAccountingYear","archiveExportAvailable","city","companyYearAdmissionId","consequentialOperationsAllowed","createdAt","createdBy","currentAgreementAccepted","currentEligibilityDecision","eligibilityNextStep","eligibilityNextStepCode","eligibilityReasonExplanations","entityType","id","identityConfirmedAt","identityLockedAt","name","orgNumber","postalCode","resourceScope","role","source","statusText"]) &&
    value.aal === "aal2" &&
    typeof value.address === "string" &&
    (typeof value.admittedAccountingYear === "number" && Number.isInteger(value.admittedAccountingYear) || value.admittedAccountingYear === null) &&
    typeof value.archiveExportAvailable === "boolean" &&
    typeof value.city === "string" &&
    (isUuid(value.companyYearAdmissionId) || value.companyYearAdmissionId === null) &&
    typeof value.consequentialOperationsAllowed === "boolean" &&
    typeof value.createdAt === "string" &&
    typeof value.createdBy === "string" &&
    typeof value.currentAgreementAccepted === "boolean" &&
    ((value.currentEligibilityDecision === "supported" || value.currentEligibilityDecision === "clarify" || value.currentEligibilityDecision === "blocked") || value.currentEligibilityDecision === null) &&
    (typeof value.eligibilityNextStep === "string" || value.eligibilityNextStep === null) &&
    (typeof value.eligibilityNextStepCode === "string" || value.eligibilityNextStepCode === null) &&
    Array.isArray(value.eligibilityReasonExplanations) && value.eligibilityReasonExplanations.every((item) => typeof item === "string") &&
    typeof value.entityType === "string" &&
    typeof value.id === "string" &&
    (typeof value.identityConfirmedAt === "string" || value.identityConfirmedAt === null) &&
    (typeof value.identityLockedAt === "string" || value.identityLockedAt === null) &&
    typeof value.name === "string" &&
    typeof value.orgNumber === "string" &&
    typeof value.postalCode === "string" &&
    value.resourceScope === "owner_sensitive" &&
    value.role === "owner" &&
    typeof value.source === "string" &&
    typeof value.statusText === "string"
  );
}

function isCompanyContextResponse(value: unknown): value is CompanyContextResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companies","selectedCompany"]) &&
    Array.isArray(value.companies) && value.companies.every((item) => isCompanyContext(item)) &&
    isCompanyContext(value.selectedCompany)
  );
}

function isCompanyInvitation(value: unknown): value is CompanyInvitation {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","createdAt","expiresAt","id","invitedEmail","role","status","updatedAt"]) &&
    typeof value.companyId === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.expiresAt === "string" &&
    typeof value.id === "string" &&
    typeof value.invitedEmail === "string" &&
    (value.role === "reviewer" || value.role === "read_only") &&
    (value.status === "pending" || value.status === "accepted" || value.status === "revoked" || value.status === "expired") &&
    typeof value.updatedAt === "string"
  );
}

function isCompanyInvitationListResponse(value: unknown): value is CompanyInvitationListResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["invitations"]) &&
    Array.isArray(value.invitations) && value.invitations.every((item) => isCompanyInvitation(item))
  );
}

function isCompanyInvitationResponse(value: unknown): value is CompanyInvitationResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["deliveryBody","deliverySubject","deliveryToken","invitation"]) &&
    (typeof value.deliveryBody === "string" || value.deliveryBody === null) &&
    (typeof value.deliverySubject === "string" || value.deliverySubject === null) &&
    (typeof value.deliveryToken === "string" || value.deliveryToken === null) &&
    isCompanyInvitation(value.invitation)
  );
}

function isCompanyMembership(value: unknown): value is CompanyMembership {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["acceptedAt","companyId","role","state","userId"]) &&
    typeof value.acceptedAt === "string" &&
    typeof value.companyId === "string" &&
    (value.role === "reviewer" || value.role === "read_only") &&
    (value.state === "active" || value.state === "removed") &&
    typeof value.userId === "string"
  );
}

function isCompanyMembershipListResponse(value: unknown): value is CompanyMembershipListResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["memberships"]) &&
    Array.isArray(value.memberships) && value.memberships.every((item) => isCompanyMembership(item))
  );
}

function isCompanyMembershipResponse(value: unknown): value is CompanyMembershipResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["membership"]) &&
    isCompanyMembership(value.membership)
  );
}

function isCompanyOnboardingResponse(value: unknown): value is CompanyOnboardingResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","currentAgreementAccepted","replayed"]) &&
    isUuid(value.companyId) &&
    value.currentAgreementAccepted === true &&
    typeof value.replayed === "boolean"
  );
}

function isCompanyAgreementAcceptanceResponse(value: unknown): value is CompanyAgreementAcceptanceResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","currentAgreementAccepted","replayed"]) &&
    isUuid(value.companyId) &&
    value.currentAgreementAccepted === true &&
    typeof value.replayed === "boolean"
  );
}

function isEligibilityPublicFacts(value: unknown): value is EligibilityPublicFacts {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["entityType","name","orgNumber","source","statusText"]) &&
    typeof value.entityType === "string" &&
    typeof value.name === "string" &&
    typeof value.orgNumber === "string" &&
    typeof value.source === "string" &&
    typeof value.statusText === "string"
  );
}

function isEligibilityQuestion(value: unknown): value is EligibilityQuestion {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["answerOptions","code","prompt"]) &&
    (value.answerOptions === undefined || Array.isArray(value.answerOptions) && value.answerOptions.every((item) => (item === "yes" || item === "no" || item === "unknown"))) &&
    typeof value.code === "string" &&
    typeof value.prompt === "string"
  );
}

function isCompanyYearPromise(value: unknown): value is CompanyYearPromise {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingYear","customerClaims","endsOn","onlyAccountingAndFilingProduct","reconstructionRequiredFrom","startsOn"]) &&
    typeof value.accountingYear === "number" && Number.isInteger(value.accountingYear) &&
    Array.isArray(value.customerClaims) && value.customerClaims.every((item) => typeof item === "string") &&
    typeof value.endsOn === "string" &&
    value.onlyAccountingAndFilingProduct === true &&
    typeof value.reconstructionRequiredFrom === "string" &&
    typeof value.startsOn === "string"
  );
}

function isEligibilityDecisionResponse(value: unknown): value is EligibilityDecisionResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingYear","answers","answersSha256","capabilityManifestSha256","capabilityManifestVersion","companyYearPromise","decision","nextStep","nextStepCode","provisional","publicFacts","publicFactsSha256","questionCodes","questions","reasonCodes","reasonExplanations"]) &&
    typeof value.accountingYear === "number" && Number.isInteger(value.accountingYear) &&
    isRecord(value.answers) && Object.values(value.answers).every((item) => (item === "yes" || item === "no" || item === "unknown")) &&
    (typeof value.answersSha256 === "string" || value.answersSha256 === null) &&
    typeof value.capabilityManifestSha256 === "string" &&
    typeof value.capabilityManifestVersion === "string" &&
    (isCompanyYearPromise(value.companyYearPromise) || value.companyYearPromise === null) &&
    (value.decision === "supported" || value.decision === "clarify" || value.decision === "blocked") &&
    typeof value.nextStep === "string" &&
    typeof value.nextStepCode === "string" &&
    typeof value.provisional === "boolean" &&
    isEligibilityPublicFacts(value.publicFacts) &&
    typeof value.publicFactsSha256 === "string" &&
    Array.isArray(value.questionCodes) && value.questionCodes.every((item) => typeof item === "string") &&
    Array.isArray(value.questions) && value.questions.every((item) => isEligibilityQuestion(item)) &&
    Array.isArray(value.reasonCodes) && value.reasonCodes.every((item) => typeof item === "string") &&
    Array.isArray(value.reasonExplanations) && value.reasonExplanations.every((item) => typeof item === "string")
  );
}

function isCompanyYearAdmissionResponse(value: unknown): value is CompanyYearAdmissionResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingYear","capabilityManifestSha256","capabilityManifestVersion","companyId","companyYearAdmissionId","currentAgreementAccepted","reconstructFrom","replayed"]) &&
    typeof value.accountingYear === "number" && Number.isInteger(value.accountingYear) &&
    typeof value.capabilityManifestSha256 === "string" &&
    typeof value.capabilityManifestVersion === "string" &&
    isUuid(value.companyId) &&
    isUuid(value.companyYearAdmissionId) &&
    value.currentAgreementAccepted === true &&
    typeof value.reconstructFrom === "string" &&
    typeof value.replayed === "boolean"
  );
}

function isCompanyYearEligibilityStateResponse(value: unknown): value is CompanyYearEligibilityStateResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["acceptedCapabilityManifestSha256","acceptedCapabilityManifestVersion","acceptedCompanyYearPromise","accountingYear","archiveExportAvailable","companyId","companyYearAdmissionId","companyYearEligibilityAssessmentId","consequentialOperationsAllowed","currentCapabilityManifestSha256","currentCapabilityManifestVersion","decision","nextStep","nextStepCode","reasonCodes","reasonExplanations","replayed","trigger"]) &&
    typeof value.acceptedCapabilityManifestSha256 === "string" &&
    typeof value.acceptedCapabilityManifestVersion === "string" &&
    isCompanyYearPromise(value.acceptedCompanyYearPromise) &&
    typeof value.accountingYear === "number" && Number.isInteger(value.accountingYear) &&
    value.archiveExportAvailable === true &&
    isUuid(value.companyId) &&
    isUuid(value.companyYearAdmissionId) &&
    isUuid(value.companyYearEligibilityAssessmentId) &&
    typeof value.consequentialOperationsAllowed === "boolean" &&
    typeof value.currentCapabilityManifestSha256 === "string" &&
    typeof value.currentCapabilityManifestVersion === "string" &&
    (value.decision === "supported" || value.decision === "clarify" || value.decision === "blocked") &&
    typeof value.nextStep === "string" &&
    typeof value.nextStepCode === "string" &&
    Array.isArray(value.reasonCodes) && value.reasonCodes.every((item) => typeof item === "string") &&
    Array.isArray(value.reasonExplanations) && value.reasonExplanations.every((item) => typeof item === "string") &&
    typeof value.replayed === "boolean" &&
    (value.trigger === "public_fact_changed" || value.trigger === "material_answer_changed" || value.trigger === "manifest_changed" || value.trigger === "before_payment" || value.trigger === "before_filing")
  );
}

function isCompanyAccessRecord(value: unknown): value is CompanyAccessRecord {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["address","city","createdAt","createdBy","entityType","id","identityConfirmedAt","identityLockedAt","name","orgNumber","postalCode","role","source","statusText"]) &&
    typeof value.address === "string" &&
    typeof value.city === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.createdBy === "string" &&
    typeof value.entityType === "string" &&
    typeof value.id === "string" &&
    (typeof value.identityConfirmedAt === "string" || value.identityConfirmedAt === null) &&
    (typeof value.identityLockedAt === "string" || value.identityLockedAt === null) &&
    typeof value.name === "string" &&
    typeof value.orgNumber === "string" &&
    typeof value.postalCode === "string" &&
    (value.role === "owner" || value.role === "reviewer" || value.role === "read_only") &&
    typeof value.source === "string" &&
    typeof value.statusText === "string"
  );
}

function isCompanyAccessRecordResponse(value: unknown): value is CompanyAccessRecordResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["company"]) &&
    isCompanyAccessRecord(value.company)
  );
}

function isOperatorContextResponse(value: unknown): value is OperatorContextResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["active","role"]) &&
    value.active === true &&
    (value.role === "support" || value.role === "admin")
  );
}

function isOperatorCompanyRecord(value: unknown): value is OperatorCompanyRecord {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["address","city","createdAt","createdBy","entityType","id","identityConfirmedAt","identityLockedAt","name","orgNumber","postalCode","source","statusText"]) &&
    typeof value.address === "string" &&
    typeof value.city === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.createdBy === "string" &&
    typeof value.entityType === "string" &&
    typeof value.id === "string" &&
    (typeof value.identityConfirmedAt === "string" || value.identityConfirmedAt === null) &&
    (typeof value.identityLockedAt === "string" || value.identityLockedAt === null) &&
    typeof value.name === "string" &&
    typeof value.orgNumber === "string" &&
    typeof value.postalCode === "string" &&
    typeof value.source === "string" &&
    typeof value.statusText === "string"
  );
}

function isOperatorCompanySearchResponse(value: unknown): value is OperatorCompanySearchResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companies"]) &&
    Array.isArray(value.companies) && value.companies.every((item) => isOperatorCompanyRecord(item))
  );
}

function isSupportAccessGrant(value: unknown): value is SupportAccessGrant {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["caseId","companyId","expiresAt","grantedAt","grantedBy","operatorUserId","reason","revocationReason","revokedAt","revokedBy","scopes","startsAt"]) &&
    isUuid(value.caseId) &&
    isUuid(value.companyId) &&
    isDateTime(value.expiresAt) &&
    isDateTime(value.grantedAt) &&
    isUuid(value.grantedBy) &&
    isUuid(value.operatorUserId) &&
    (value.reason === "customer_request" || value.reason === "security_incident" || value.reason === "service_recovery" || value.reason === "legal_obligation") &&
    ((value.revocationReason === "case_closed" || value.revocationReason === "access_no_longer_needed" || value.revocationReason === "operator_removed" || value.revocationReason === "security_response" || value.revocationReason === "grant_replaced") || value.revocationReason === null) &&
    (isDateTime(value.revokedAt) || value.revokedAt === null) &&
    (isUuid(value.revokedBy) || value.revokedBy === null) &&
    Array.isArray(value.scopes) && value.scopes.every((item) => (item === "profile" || item === "filing" || item === "billing" || item === "audit" || item === "cancellation" || item === "authority" || item === "documents" || item === "production")) &&
    isDateTime(value.startsAt)
  );
}

function isSupportAccessGrantResponse(value: unknown): value is SupportAccessGrantResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["grant"]) &&
    isSupportAccessGrant(value.grant)
  );
}

function isSupportCaseOpening(value: unknown): value is SupportCaseOpening {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["caseId","companyId","openedAt","openedBy","operationId"]) &&
    isUuid(value.caseId) &&
    isUuid(value.companyId) &&
    isDateTime(value.openedAt) &&
    isUuid(value.openedBy) &&
    isUuid(value.operationId)
  );
}

function isSupportCaseOpeningResponse(value: unknown): value is SupportCaseOpeningResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["opening"]) &&
    isSupportCaseOpening(value.opening)
  );
}

function isSupportCompanyResource(value: unknown): value is SupportCompanyResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["address","city","createdAt","createdBy","entityType","id","identityConfirmedAt","identityLockedAt","name","orgNumber","postalCode","source","statusText"]) &&
    typeof value.address === "string" &&
    typeof value.city === "string" &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    typeof value.entityType === "string" &&
    isUuid(value.id) &&
    (isDateTime(value.identityConfirmedAt) || value.identityConfirmedAt === null) &&
    (isDateTime(value.identityLockedAt) || value.identityLockedAt === null) &&
    typeof value.name === "string" &&
    typeof value.orgNumber === "string" &&
    typeof value.postalCode === "string" &&
    typeof value.source === "string" &&
    typeof value.statusText === "string"
  );
}

function isSupportAuditEventResource(value: unknown): value is SupportAuditEventResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["action","actorId","category","companyId","createdAt","id","message"]) &&
    typeof value.action === "string" &&
    isUuid(value.actorId) &&
    typeof value.category === "string" &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.id) &&
    typeof value.message === "string"
  );
}

function isSupportCancellationResource(value: unknown): value is SupportCancellationResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","deletedAt","deletedBy","evidence","id","reason","requestedAt","requestedBy","reviewedAt","reviewedBy","status","updatedAt"]) &&
    isUuid(value.companyId) &&
    (isDateTime(value.deletedAt) || value.deletedAt === null) &&
    (isUuid(value.deletedBy) || value.deletedBy === null) &&
    isRecord(value.evidence) &&
    isUuid(value.id) &&
    typeof value.reason === "string" &&
    isDateTime(value.requestedAt) &&
    isUuid(value.requestedBy) &&
    (isDateTime(value.reviewedAt) || value.reviewedAt === null) &&
    (isUuid(value.reviewedBy) || value.reviewedBy === null) &&
    typeof value.status === "string" &&
    isDateTime(value.updatedAt)
  );
}

function isSupportFilingSubmissionResource(value: unknown): value is SupportFilingSubmissionResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","filing","id","incomeYear","status","updatedAt"]) &&
    isUuid(value.companyId) &&
    typeof value.filing === "string" &&
    isUuid(value.id) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.status === "string" &&
    isDateTime(value.updatedAt)
  );
}

function isSupportFilingReadinessResource(value: unknown): value is SupportFilingReadinessResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","hardBlocks","id","incomeYear","obligation","ready","status","updatedAt","warnings"]) &&
    isUuid(value.companyId) &&
    Array.isArray(value.hardBlocks) && value.hardBlocks.every((item) => isRecord(item)) &&
    isUuid(value.id) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.obligation === "string" &&
    typeof value.ready === "boolean" &&
    typeof value.status === "string" &&
    isDateTime(value.updatedAt) &&
    Array.isArray(value.warnings) && value.warnings.every((item) => isRecord(item))
  );
}

function isSupportBillingAccountResource(value: unknown): value is SupportBillingAccountResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","filingPackagePaid","pricingPlan","refundCompleted","refundEligible","refundProviderRef","subscriptionActive","updatedAt"]) &&
    isUuid(value.companyId) &&
    typeof value.filingPackagePaid === "boolean" &&
    typeof value.pricingPlan === "string" &&
    typeof value.refundCompleted === "boolean" &&
    typeof value.refundEligible === "boolean" &&
    (typeof value.refundProviderRef === "string" || value.refundProviderRef === null) &&
    typeof value.subscriptionActive === "boolean" &&
    isDateTime(value.updatedAt)
  );
}

function isSupportBillingPaymentEventResource(value: unknown): value is SupportBillingPaymentEventResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amountNok","companyId","createdAt","id","kind","provider","status"]) &&
    typeof value.amountNok === "number" && Number.isInteger(value.amountNok) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.id) &&
    typeof value.kind === "string" &&
    typeof value.provider === "string" &&
    typeof value.status === "string"
  );
}

function isSupportAuthorityPermissionResource(value: unknown): value is SupportAuthorityPermissionResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","id","obligation","productionEnabled","updatedAt"]) &&
    isUuid(value.companyId) &&
    isUuid(value.id) &&
    typeof value.obligation === "string" &&
    typeof value.productionEnabled === "boolean" &&
    isDateTime(value.updatedAt)
  );
}

function isSupportAuthorityTestRunResource(value: unknown): value is SupportAuthorityTestRunResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","environment","id","obligation","recordedAt","status","testReference"]) &&
    isUuid(value.companyId) &&
    typeof value.environment === "string" &&
    isUuid(value.id) &&
    typeof value.obligation === "string" &&
    isDateTime(value.recordedAt) &&
    typeof value.status === "string" &&
    typeof value.testReference === "string"
  );
}

function isSupportSystemUserRequestResource(value: unknown): value is SupportSystemUserRequestResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","failureCode","id","obligation","requestedAt","status","updatedAt"]) &&
    isUuid(value.companyId) &&
    (typeof value.failureCode === "string" || value.failureCode === null) &&
    isUuid(value.id) &&
    typeof value.obligation === "string" &&
    (isDateTime(value.requestedAt) || value.requestedAt === null) &&
    typeof value.status === "string" &&
    isDateTime(value.updatedAt)
  );
}

function isSupportProductionPilotEntitlementResource(value: unknown): value is SupportProductionPilotEntitlementResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["caseProfile","companyId","expiresAt","id","incomeYear","obligation","startsAt","status","updatedAt","userId"]) &&
    typeof value.caseProfile === "string" &&
    isUuid(value.companyId) &&
    isDateTime(value.expiresAt) &&
    isUuid(value.id) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.obligation === "string" &&
    isDateTime(value.startsAt) &&
    typeof value.status === "string" &&
    isDateTime(value.updatedAt) &&
    isUuid(value.userId)
  );
}

function isSupportFilingApprovalSnapshotResource(value: unknown): value is SupportFilingApprovalSnapshotResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["adapterVersion","approvedAt","caseProfile","companyId","id","incomeYear","invalidatedAt","manifestHash","obligation","payloadHash"]) &&
    typeof value.adapterVersion === "string" &&
    isDateTime(value.approvedAt) &&
    typeof value.caseProfile === "string" &&
    isUuid(value.companyId) &&
    isUuid(value.id) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    (isDateTime(value.invalidatedAt) || value.invalidatedAt === null) &&
    typeof value.manifestHash === "string" &&
    typeof value.obligation === "string" &&
    typeof value.payloadHash === "string"
  );
}

function isSupportProductionFilingSubmissionResource(value: unknown): value is SupportProductionFilingSubmissionResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["adapterVersion","caseProfile","companyId","createdAt","failureClass","id","incomeYear","obligation","status","updatedAt"]) &&
    typeof value.adapterVersion === "string" &&
    typeof value.caseProfile === "string" &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    (typeof value.failureClass === "string" || value.failureClass === null) &&
    isUuid(value.id) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.obligation === "string" &&
    typeof value.status === "string" &&
    isDateTime(value.updatedAt)
  );
}

function isSupportProductionFilingEventResource(value: unknown): value is SupportProductionFilingEventResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["attempt","createdAt","failureClass","id","operationName","operationState","resultingStatus","submissionId"]) &&
    typeof value.attempt === "number" && Number.isInteger(value.attempt) &&
    isDateTime(value.createdAt) &&
    (typeof value.failureClass === "string" || value.failureClass === null) &&
    isUuid(value.id) &&
    typeof value.operationName === "string" &&
    typeof value.operationState === "string" &&
    typeof value.resultingStatus === "string" &&
    isUuid(value.submissionId)
  );
}

function isSupportProductionFeedbackArtifactResource(value: unknown): value is SupportProductionFeedbackArtifactResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["byteLength","classification","companyId","contentType","documentId","id","retrievedAt","sha256","submissionId"]) &&
    typeof value.byteLength === "number" && Number.isInteger(value.byteLength) &&
    typeof value.classification === "string" &&
    isUuid(value.companyId) &&
    typeof value.contentType === "string" &&
    isUuid(value.documentId) &&
    isUuid(value.id) &&
    isDateTime(value.retrievedAt) &&
    typeof value.sha256 === "string" &&
    isUuid(value.submissionId)
  );
}

function isSupportDocumentResource(value: unknown): value is SupportDocumentResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","createdAt","documentType","id","incomeYear","linkedTo","name","retentionYears","status","storageKey"]) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    typeof value.documentType === "string" &&
    isUuid(value.id) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.linkedTo === "string" &&
    typeof value.name === "string" &&
    typeof value.retentionYears === "number" && Number.isInteger(value.retentionYears) &&
    typeof value.status === "string" &&
    typeof value.storageKey === "string"
  );
}

function isSupportStorageObjectResource(value: unknown): value is SupportStorageObjectResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bucketId","createdAt","id","name"]) &&
    typeof value.bucketId === "string" &&
    isDateTime(value.createdAt) &&
    isUuid(value.id) &&
    typeof value.name === "string"
  );
}

function isSupportDeletionReviewResource(value: unknown): value is SupportDeletionReviewResource {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["cancellationId","companyId","decision","evidenceReference","id","reviewedAt","supportCaseId"]) &&
    isUuid(value.cancellationId) &&
    isUuid(value.companyId) &&
    typeof value.decision === "string" &&
    typeof value.evidenceReference === "string" &&
    isUuid(value.id) &&
    isDateTime(value.reviewedAt) &&
    isUuid(value.supportCaseId)
  );
}

function isSupportCaseResources(value: unknown): value is SupportCaseResources {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["auditEvents","authorityPermissions","authorityTestRuns","billingAccounts","billingPaymentEvents","companies","companyCancellations","companyDeletionReviews","documents","filingApprovalSnapshots","filingReadinessSnapshots","filingSubmissions","productionFeedbackArtifacts","productionFilingEvents","productionFilingSubmissions","productionPilotEntitlements","storageObjects","systemUserRequests"]) &&
    Array.isArray(value.auditEvents) && value.auditEvents.every((item) => isSupportAuditEventResource(item)) &&
    Array.isArray(value.authorityPermissions) && value.authorityPermissions.every((item) => isSupportAuthorityPermissionResource(item)) &&
    Array.isArray(value.authorityTestRuns) && value.authorityTestRuns.every((item) => isSupportAuthorityTestRunResource(item)) &&
    Array.isArray(value.billingAccounts) && value.billingAccounts.every((item) => isSupportBillingAccountResource(item)) &&
    Array.isArray(value.billingPaymentEvents) && value.billingPaymentEvents.every((item) => isSupportBillingPaymentEventResource(item)) &&
    Array.isArray(value.companies) && value.companies.every((item) => isSupportCompanyResource(item)) &&
    Array.isArray(value.companyCancellations) && value.companyCancellations.every((item) => isSupportCancellationResource(item)) &&
    Array.isArray(value.companyDeletionReviews) && value.companyDeletionReviews.every((item) => isSupportDeletionReviewResource(item)) &&
    Array.isArray(value.documents) && value.documents.every((item) => isSupportDocumentResource(item)) &&
    Array.isArray(value.filingApprovalSnapshots) && value.filingApprovalSnapshots.every((item) => isSupportFilingApprovalSnapshotResource(item)) &&
    Array.isArray(value.filingReadinessSnapshots) && value.filingReadinessSnapshots.every((item) => isSupportFilingReadinessResource(item)) &&
    Array.isArray(value.filingSubmissions) && value.filingSubmissions.every((item) => isSupportFilingSubmissionResource(item)) &&
    Array.isArray(value.productionFeedbackArtifacts) && value.productionFeedbackArtifacts.every((item) => isSupportProductionFeedbackArtifactResource(item)) &&
    Array.isArray(value.productionFilingEvents) && value.productionFilingEvents.every((item) => isSupportProductionFilingEventResource(item)) &&
    Array.isArray(value.productionFilingSubmissions) && value.productionFilingSubmissions.every((item) => isSupportProductionFilingSubmissionResource(item)) &&
    Array.isArray(value.productionPilotEntitlements) && value.productionPilotEntitlements.every((item) => isSupportProductionPilotEntitlementResource(item)) &&
    Array.isArray(value.storageObjects) && value.storageObjects.every((item) => isSupportStorageObjectResource(item)) &&
    Array.isArray(value.systemUserRequests) && value.systemUserRequests.every((item) => isSupportSystemUserRequestResource(item))
  );
}

function isSupportCaseSnapshotResponse(value: unknown): value is SupportCaseSnapshotResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["caseId","companyId","resources","scopes"]) &&
    isUuid(value.caseId) &&
    isUuid(value.companyId) &&
    isSupportCaseResources(value.resources) &&
    Array.isArray(value.scopes) && value.scopes.every((item) => (item === "profile" || item === "filing" || item === "billing" || item === "audit" || item === "cancellation" || item === "authority" || item === "documents" || item === "production"))
  );
}

function isInvitationLookup(value: unknown): value is InvitationLookup {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyName","expiresAt","role"]) &&
    typeof value.companyName === "string" &&
    typeof value.expiresAt === "string" &&
    (value.role === "reviewer" || value.role === "read_only")
  );
}

function isInvitationSideEffectContinuation(value: unknown): value is InvitationSideEffectContinuation {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["commandName","companyId","deliveryBody","deliverySubject","deliveryToken","invitation","membership","operationId"]) &&
    (value.commandName === "create_invitation" || value.commandName === "accept_invitation" || value.commandName === "revoke_invitation" || value.commandName === "resend_invitation") &&
    typeof value.companyId === "string" &&
    (typeof value.deliveryBody === "string" || value.deliveryBody === null) &&
    (typeof value.deliverySubject === "string" || value.deliverySubject === null) &&
    (typeof value.deliveryToken === "string" || value.deliveryToken === null) &&
    (isCompanyInvitation(value.invitation) || value.invitation === null) &&
    (isCompanyMembership(value.membership) || value.membership === null) &&
    typeof value.operationId === "string"
  );
}

function isInvitationSideEffectContinuationList(value: unknown): value is InvitationSideEffectContinuationList {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["continuations"]) &&
    Array.isArray(value.continuations) && value.continuations.every((item) => isInvitationSideEffectContinuation(item))
  );
}

function isInvitationSideEffectCompletion(value: unknown): value is InvitationSideEffectCompletion {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["completed","operationId"]) &&
    value.completed === true &&
    typeof value.operationId === "string"
  );
}

function isCompanyCancellationEvidence(value: unknown): value is CompanyCancellationEvidence {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["archiveDownloadPath","archiveExportedAt","archiveIncomeYear","corporateEvidenceComplete","corporateObjectKeys","legalReviewRequired","missingCorporateObjectKeys","missingDocumentIds","retentionClasses"]) &&
    (value.archiveDownloadPath === undefined || (typeof value.archiveDownloadPath === "string" || value.archiveDownloadPath === null)) &&
    (value.archiveExportedAt === undefined || (isDateTime(value.archiveExportedAt) || value.archiveExportedAt === null)) &&
    (value.archiveIncomeYear === undefined || ((typeof value.archiveIncomeYear === "number" && Number.isInteger(value.archiveIncomeYear) && value.archiveIncomeYear >= 2000 && value.archiveIncomeYear <= 2100) || value.archiveIncomeYear === null)) &&
    (value.corporateEvidenceComplete === undefined || (typeof value.corporateEvidenceComplete === "boolean" || value.corporateEvidenceComplete === null)) &&
    (value.corporateObjectKeys === undefined || Array.isArray(value.corporateObjectKeys) && value.corporateObjectKeys.every((item) => typeof item === "string")) &&
    (value.legalReviewRequired === undefined || typeof value.legalReviewRequired === "boolean") &&
    (value.missingCorporateObjectKeys === undefined || Array.isArray(value.missingCorporateObjectKeys) && value.missingCorporateObjectKeys.every((item) => typeof item === "string")) &&
    (value.missingDocumentIds === undefined || Array.isArray(value.missingDocumentIds) && value.missingDocumentIds.every((item) => isUuid(item))) &&
    (value.retentionClasses === undefined || Array.isArray(value.retentionClasses) && value.retentionClasses.every((item) => typeof item === "string"))
  );
}

function isCompanyCancellation(value: unknown): value is CompanyCancellation {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","deletedAt","deletedBy","evidence","id","reason","requestedAt","requestedBy","reviewedAt","reviewedBy","status","updatedAt"]) &&
    isUuid(value.companyId) &&
    (isDateTime(value.deletedAt) || value.deletedAt === null) &&
    (isUuid(value.deletedBy) || value.deletedBy === null) &&
    isCompanyCancellationEvidence(value.evidence) &&
    isUuid(value.id) &&
    (typeof value.reason === "string" && value.reason.length >= 1 && value.reason.length <= 1000) &&
    isDateTime(value.requestedAt) &&
    isUuid(value.requestedBy) &&
    (isDateTime(value.reviewedAt) || value.reviewedAt === null) &&
    (isUuid(value.reviewedBy) || value.reviewedBy === null) &&
    (value.status === "export_required" || value.status === "retention_hold" || value.status === "deletion_approved" || value.status === "deleted" || value.status === "superseded") &&
    isDateTime(value.updatedAt)
  );
}

function isCompanyCancellationListResponse(value: unknown): value is CompanyCancellationListResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["cancellations"]) &&
    Array.isArray(value.cancellations) && value.cancellations.every((item) => isCompanyCancellation(item))
  );
}

function isCompanyCancellationResponse(value: unknown): value is CompanyCancellationResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["cancellation"]) &&
    isCompanyCancellation(value.cancellation)
  );
}

function isCompanyDeletionReview(value: unknown): value is CompanyDeletionReview {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["cancellationId","cancellationRevision","companyId","decision","evidenceReference","id","operationId","reviewedAt","reviewedBy"]) &&
    isUuid(value.cancellationId) &&
    isDateTime(value.cancellationRevision) &&
    isUuid(value.companyId) &&
    (value.decision === "approved" || value.decision === "rejected") &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    isUuid(value.id) &&
    isUuid(value.operationId) &&
    isDateTime(value.reviewedAt) &&
    isUuid(value.reviewedBy)
  );
}

function isCompanyDeletionReviewResponse(value: unknown): value is CompanyDeletionReviewResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["cancellation","review"]) &&
    isCompanyCancellation(value.cancellation) &&
    isCompanyDeletionReview(value.review)
  );
}

function isAdministrativeCostEntryWire(value: unknown): value is AdministrativeCostEntryWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","entryId","entryKind","incomeYear","postedAt","replayed"]) &&
    isUuid(value.companyId) &&
    isUuid(value.entryId) &&
    value.entryKind === "ADMINISTRATIVE_COST" &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isDateTime(value.postedAt) &&
    typeof value.replayed === "boolean"
  );
}

function isAdministrativeCostCategory(value: unknown): value is AdministrativeCostCategory {
  return value === "BANK_FEE" || value === "ACCOUNTING_FEE" || value === "SOFTWARE" || value === "PUBLIC_FEE" || value === "LEGAL_ADVISORY" || value === "OTHER_ADMIN_COST";
}

function isCompanyYearCloseGapCode(value: unknown): value is CompanyYearCloseGapCode {
  return value === "SOURCE_INCOMPLETE" || value === "JOURNAL_UNBALANCED" || value === "DUPLICATE_POSTING_FOUND" || value === "UNSUPPORTED_TRANSACTION" || value === "BANK_NOT_RECONCILED" || value === "UNRESOLVED_BANK_ROW" || value === "MATERIAL_BALANCE_UNDOCUMENTED" || value === "REPORTING_NOT_RECONCILED" || value === "CHECK_EVIDENCE_INCOMPLETE" || value === "PERIOD_END_UNSUPPORTED";
}

function isCompanyYearCloseState(value: unknown): value is CompanyYearCloseState {
  return value === "BLOCKED" || value === "CLOSED";
}

function isLedgerAdministrativeCostWire(value: unknown): value is LedgerAdministrativeCostWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","bankTransactionId","category","companyId","documentId","incomeYear","paidDate","payee"]) &&
    isLedgerMoneyWire(value.amount) &&
    (typeof value.bankTransactionId === "string" && value.bankTransactionId.length >= 1 && value.bankTransactionId.length <= 255) &&
    isAdministrativeCostCategory(value.category) &&
    isUuid(value.companyId) &&
    (value.documentId === undefined || ((typeof value.documentId === "string" && value.documentId.length >= 1 && value.documentId.length <= 255) || value.documentId === null)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    typeof value.paidDate === "string" &&
    (typeof value.payee === "string" && value.payee.length >= 1 && value.payee.length <= 255)
  );
}

function isLedgerCompanyYearCloseAssessmentWire(value: unknown): value is LedgerCompanyYearCloseAssessmentWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["assessmentId","closeLockId","companyId","evidenceDigest","gapCodes","incomeYear","isCurrent","ledgerStateDigest","periodEnd","reconstructionAssessmentId","recordedAt","replayed","state"]) &&
    isUuid(value.assessmentId) &&
    (isUuid(value.closeLockId) || value.closeLockId === null) &&
    isUuid(value.companyId) &&
    (typeof value.evidenceDigest === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.evidenceDigest)) &&
    Array.isArray(value.gapCodes) && value.gapCodes.every((item) => isCompanyYearCloseGapCode(item)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    typeof value.isCurrent === "boolean" &&
    (typeof value.ledgerStateDigest === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.ledgerStateDigest)) &&
    typeof value.periodEnd === "string" &&
    isUuid(value.reconstructionAssessmentId) &&
    isDateTime(value.recordedAt) &&
    typeof value.replayed === "boolean" &&
    isCompanyYearCloseState(value.state)
  );
}

function isLedgerEntryKind(value: unknown): value is LedgerEntryKind {
  return value === "OPENING_BALANCE" || value === "ADMINISTRATIVE_COST" || value === "MANUAL_JOURNAL" || value === "BANK_RULE_SUGGESTION" || value === "DIVIDEND_RECEIVED" || value === "OWNER_DIVIDEND_DECLARED" || value === "OWNER_DIVIDEND_PAYMENT" || value === "SHARE_PURCHASE" || value === "SHARE_SALE" || value === "SHAREHOLDER_LOAN" || value === "TAX_SETTLEMENT" || value === "BANK_INTEREST" || value === "BANK_LOAN" || value === "CAPITAL_INCREASE" || value === "CAPITAL_REDUCTION" || value === "COMPANY_TAX_ACCRUAL" || value === "GROUP_CONTRIBUTION" || value === "INTERCOMPANY_LOAN" || value === "INVESTMENT_MEASUREMENT" || value === "CORRECTION_REVERSAL";
}

function isLedgerEntryPageWire(value: unknown): value is LedgerEntryPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items","page"]) &&
    Array.isArray(value.items) && value.items.every((item) => isLedgerEntryViewWire(item)) &&
    isLedgerPageWire(value.page)
  );
}

function isLedgerEntryViewWire(value: unknown): value is LedgerEntryViewWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","createdAt","entryId","entryKind","incomeYear","lines","memo","postedAt","postedBy","riskFlags","sourceCapability","sourceRecordId","warningAcceptedAt","warningAcceptedBy"]) &&
    typeof value.companyId === "string" &&
    (value.createdAt === undefined || isDateTime(value.createdAt)) &&
    typeof value.entryId === "string" &&
    isLedgerEntryKind(value.entryKind) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    Array.isArray(value.lines) && value.lines.every((item) => isLedgerLineWire(item)) &&
    typeof value.memo === "string" &&
    isDateTime(value.postedAt) &&
    typeof value.postedBy === "string" &&
    Array.isArray(value.riskFlags) && value.riskFlags.every((item) => isLedgerRiskFlagWire(item)) &&
    (value.sourceCapability === undefined || isLedgerSourceCapability(value.sourceCapability)) &&
    (value.sourceRecordId === undefined || (typeof value.sourceRecordId === "string" && value.sourceRecordId.length >= 1 && value.sourceRecordId.length <= 255)) &&
    (isDateTime(value.warningAcceptedAt) || value.warningAcceptedAt === null) &&
    (typeof value.warningAcceptedBy === "string" || value.warningAcceptedBy === null) &&
    (value.sourceCapability === undefined) === (value.sourceRecordId === undefined) &&
    (value.sourceCapability === undefined) === (value.createdAt === undefined)
  );
}

function isLedgerLineWire(value: unknown): value is LedgerLineWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["account","credit","debit","description"]) &&
    (typeof value.account === "string" && value.account.length <= 16) &&
    isLedgerMoneyWire(value.credit) &&
    isLedgerMoneyWire(value.debit) &&
    (typeof value.description === "string" && value.description.length <= 500)
  );
}

function isLedgerLockPeriodWire(value: unknown): value is LedgerLockPeriodWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","incomeYear","reason"]) &&
    isUuid(value.companyId) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.reason === "string" && value.reason.length >= 1 && value.reason.length <= 500)
  );
}

function isLedgerManualJournalWire(value: unknown): value is LedgerManualJournalWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","incomeYear","lines","memo","warningAccepted"]) &&
    isUuid(value.companyId) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    Array.isArray(value.lines) && value.lines.every((item) => isLedgerLineWire(item)) && value.lines.length >= 2 && value.lines.length <= 100 &&
    (typeof value.memo === "string" && value.memo.length >= 1 && value.memo.length <= 500) &&
    typeof value.warningAccepted === "boolean"
  );
}

function isLedgerMoneyWire(value: unknown): value is LedgerMoneyWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","currency"]) &&
    (typeof value.amount === "string" && value.amount.length <= 64 && new RegExp("^-?(?:0|[1-9]\\d*)(?:\\.\\d{1,2})?$", "u").test(value.amount)) &&
    value.currency === "NOK"
  );
}

function isLedgerFactReferenceWire(value: unknown): value is LedgerFactReferenceWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["capability","factSha256","recordId","revision"]) &&
    isLedgerSourceCapability(value.capability) &&
    (typeof value.factSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.factSha256)) &&
    (typeof value.recordId === "string" && value.recordId.length >= 1 && value.recordId.length <= 255) &&
    (typeof value.revision === "number" && Number.isInteger(value.revision) && value.revision >= 1)
  );
}

function isOpeningBalanceCategory(value: unknown): value is OpeningBalanceCategory {
  return value === "SUBSIDIARY_LOAN_RECEIVABLE" || value === "GROUP_COMPANY_LOAN_RECEIVABLE" || value === "CORPORATE_SHAREHOLDER_LOAN_RECEIVABLE" || value === "BANK" || value === "RESTRICTED_BANK" || value === "SUBSIDIARY_INVESTMENT" || value === "ASSOCIATE_INVESTMENT" || value === "OTHER_LONG_TERM_INVESTMENT" || value === "CURRENT_LISTED_SHARE_INVESTMENT" || value === "CURRENT_FUND_INVESTMENT" || value === "SUBSCRIPTION_RECEIVABLE" || value === "DIVIDEND_RECEIVABLE" || value === "GROUP_CONTRIBUTION_RECEIVABLE" || value === "TAX_RECEIVABLE" || value === "ACCRUED_INTEREST_RECEIVABLE" || value === "DEFERRED_TAX_ASSET" || value === "REGISTERED_SHARE_CAPITAL" || value === "SHARE_PREMIUM" || value === "UNREGISTERED_CAPITAL_INCREASE" || value === "UNREGISTERED_CAPITAL_REDUCTION" || value === "OTHER_PAID_IN_EQUITY" || value === "RETAINED_EARNINGS" || value === "UNCOVERED_LOSS" || value === "OTHER_EQUITY" || value === "LONG_TERM_BANK_LOAN_PAYABLE" || value === "SHORT_TERM_BANK_LOAN_PAYABLE" || value === "OWNER_LOAN_PAYABLE" || value === "INTERCOMPANY_LOAN_PAYABLE" || value === "SUPPLIER_PAYABLE" || value === "CURRENT_TAX_PAYABLE" || value === "DEFERRED_TAX_LIABILITY" || value === "ACCRUED_INTEREST_PAYABLE" || value === "DIVIDEND_PAYABLE" || value === "GROUP_CONTRIBUTION_PAYABLE";
}

function isOpeningPositionMode(value: unknown): value is OpeningPositionMode {
  return value === "NEW_COMPANY" || value === "PRIOR_CLOSE_RECONSTRUCTION";
}

function isBankLoanMaturity(value: unknown): value is BankLoanMaturity {
  return value === "LONG_TERM" || value === "SHORT_TERM";
}

function isInvestmentClassification(value: unknown): value is InvestmentClassification {
  return value === "SUBSIDIARY" || value === "ASSOCIATE" || value === "OTHER_LONG_TERM" || value === "CURRENT_LISTED_SHARE" || value === "CURRENT_FUND";
}

function isCapitalIncreasePhase(value: unknown): value is CapitalIncreasePhase {
  return value === "BINDING_SUBSCRIPTION" || value === "RESTRICTED_PAYMENT" || value === "REGISTERED";
}

function isCapitalReductionRecognition(value: unknown): value is CapitalReductionRecognition {
  return value === "DECIDED_NOT_REGISTERED" || value === "REGISTERED" || value === "FIRST_RECOGNIZED_AFTER_REGISTRATION";
}

function isOpeningClassifiedBalanceWire(value: unknown): value is OpeningClassifiedBalanceWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","category","componentKind","corroboratingSources","primarySource","referenceId"]) &&
    isLedgerMoneyWire(value.amount) &&
    isOpeningBalanceCategory(value.category) &&
    value.componentKind === "CLASSIFIED_BALANCE" &&
    Array.isArray(value.corroboratingSources) && value.corroboratingSources.every((item) => isLedgerFactReferenceWire(item)) && value.corroboratingSources.length >= 1 &&
    isLedgerFactReferenceWire(value.primarySource) &&
    (typeof value.referenceId === "string" && value.referenceId.length >= 1 && value.referenceId.length <= 255)
  );
}

function isOpeningBankLoanWire(value: unknown): value is OpeningBankLoanWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","componentKind","corroboratingSources","loanReferenceId","maturity","primarySource"]) &&
    isLedgerMoneyWire(value.amount) &&
    value.componentKind === "BANK_LOAN" &&
    Array.isArray(value.corroboratingSources) && value.corroboratingSources.every((item) => isLedgerFactReferenceWire(item)) && value.corroboratingSources.length >= 1 &&
    (typeof value.loanReferenceId === "string" && value.loanReferenceId.length >= 1 && value.loanReferenceId.length <= 255) &&
    isBankLoanMaturity(value.maturity) &&
    isLedgerFactReferenceWire(value.primarySource)
  );
}

function isOpeningInvestmentWire(value: unknown): value is OpeningInvestmentWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","classification","componentKind","corroboratingSources","investmentReferenceId","primarySource"]) &&
    isLedgerMoneyWire(value.amount) &&
    isInvestmentClassification(value.classification) &&
    value.componentKind === "INVESTMENT" &&
    Array.isArray(value.corroboratingSources) && value.corroboratingSources.every((item) => isLedgerFactReferenceWire(item)) && value.corroboratingSources.length >= 1 &&
    (typeof value.investmentReferenceId === "string" && value.investmentReferenceId.length >= 1 && value.investmentReferenceId.length <= 255) &&
    isLedgerFactReferenceWire(value.primarySource)
  );
}

function isOpeningCapitalIncreaseWire(value: unknown): value is OpeningCapitalIncreaseWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["capitalIncreaseReferenceId","componentKind","corroboratingSources","nominalIncrease","phase","primarySource","sharePremium"]) &&
    (typeof value.capitalIncreaseReferenceId === "string" && value.capitalIncreaseReferenceId.length >= 1 && value.capitalIncreaseReferenceId.length <= 255) &&
    value.componentKind === "CAPITAL_INCREASE" &&
    Array.isArray(value.corroboratingSources) && value.corroboratingSources.every((item) => isLedgerFactReferenceWire(item)) && value.corroboratingSources.length >= 1 &&
    isLedgerMoneyWire(value.nominalIncrease) &&
    isCapitalIncreasePhase(value.phase) &&
    isLedgerFactReferenceWire(value.primarySource) &&
    isLedgerMoneyWire(value.sharePremium)
  );
}

function isOpeningCapitalReductionWire(value: unknown): value is OpeningCapitalReductionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["capitalReductionReferenceId","componentKind","corroboratingSources","nominalReduction","primarySource","recognition"]) &&
    (typeof value.capitalReductionReferenceId === "string" && value.capitalReductionReferenceId.length >= 1 && value.capitalReductionReferenceId.length <= 255) &&
    value.componentKind === "CAPITAL_REDUCTION" &&
    Array.isArray(value.corroboratingSources) && value.corroboratingSources.every((item) => isLedgerFactReferenceWire(item)) && value.corroboratingSources.length >= 1 &&
    isLedgerMoneyWire(value.nominalReduction) &&
    isLedgerFactReferenceWire(value.primarySource) &&
    isCapitalReductionRecognition(value.recognition)
  );
}

function isOpeningDividendReceivableWire(value: unknown): value is OpeningDividendReceivableWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","componentKind","corroboratingSources","decisionReferenceId","primarySource"]) &&
    isLedgerMoneyWire(value.amount) &&
    value.componentKind === "DIVIDEND_RECEIVABLE" &&
    Array.isArray(value.corroboratingSources) && value.corroboratingSources.every((item) => isLedgerFactReferenceWire(item)) && value.corroboratingSources.length >= 1 &&
    (typeof value.decisionReferenceId === "string" && value.decisionReferenceId.length >= 1 && value.decisionReferenceId.length <= 255) &&
    isLedgerFactReferenceWire(value.primarySource)
  );
}

function isOpeningDividendPayableWire(value: unknown): value is OpeningDividendPayableWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","componentKind","corroboratingSources","decisionReferenceId","primarySource"]) &&
    isLedgerMoneyWire(value.amount) &&
    value.componentKind === "DIVIDEND_PAYABLE" &&
    Array.isArray(value.corroboratingSources) && value.corroboratingSources.every((item) => isLedgerFactReferenceWire(item)) && value.corroboratingSources.length >= 1 &&
    (typeof value.decisionReferenceId === "string" && value.decisionReferenceId.length >= 1 && value.decisionReferenceId.length <= 255) &&
    isLedgerFactReferenceWire(value.primarySource)
  );
}

function isNewYearShareholderWire(value: unknown): value is NewYearShareholderWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["name","nationalId","orgNumber","shareCount","shareholderKind"]) &&
    (typeof value.name === "string" && value.name.length >= 1 && value.name.length <= 255) &&
    (value.nationalId === undefined || ((typeof value.nationalId === "string" && new RegExp("^\\d{11}$", "u").test(value.nationalId)) || value.nationalId === null)) &&
    (value.orgNumber === undefined || ((typeof value.orgNumber === "string" && new RegExp("^\\d{9}$", "u").test(value.orgNumber)) || value.orgNumber === null)) &&
    (typeof value.shareCount === "number" && Number.isInteger(value.shareCount) && value.shareCount >= 0 && value.shareCount <= 2147483647) &&
    (value.shareholderKind === "norwegian_person" || value.shareholderKind === "norwegian_company")
  );
}

function isNewYearOpeningEntryWire(value: unknown): value is NewYearOpeningEntryWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","entryId","entryKind","incomeYear","postedAt","replayed"]) &&
    isUuid(value.companyId) &&
    isUuid(value.entryId) &&
    value.entryKind === "OPENING_BALANCE" &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isDateTime(value.postedAt) &&
    typeof value.replayed === "boolean"
  );
}

function isNewYearStartResultWire(value: unknown): value is NewYearStartResultWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["postedEntry","setupId"]) &&
    isNewYearOpeningEntryWire(value.postedEntry) &&
    isUuid(value.setupId)
  );
}

function isNewYearStartWire(value: unknown): value is NewYearStartWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankBalance","companyId","incomeYear","nominalValue","openingBasis","openingComponents","openingMode","shareCapital","shareCount","shareholders"]) &&
    isLedgerMoneyWire(value.bankBalance) &&
    isUuid(value.companyId) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isLedgerMoneyWire(value.nominalValue) &&
    (value.openingBasis === undefined || (isLedgerFactReferenceWire(value.openingBasis) || value.openingBasis === null)) &&
    (value.openingComponents === undefined || (Array.isArray(value.openingComponents) && value.openingComponents.every((item) => (isOpeningClassifiedBalanceWire(item) || isOpeningBankLoanWire(item) || isOpeningInvestmentWire(item) || isOpeningCapitalIncreaseWire(item) || isOpeningCapitalReductionWire(item) || isOpeningDividendReceivableWire(item) || isOpeningDividendPayableWire(item))) || value.openingComponents === null)) &&
    (value.openingMode === undefined || isOpeningPositionMode(value.openingMode)) &&
    isLedgerMoneyWire(value.shareCapital) &&
    (typeof value.shareCount === "number" && Number.isInteger(value.shareCount) && value.shareCount <= 2147483647 && value.shareCount > 0) &&
    Array.isArray(value.shareholders) && value.shareholders.every((item) => isNewYearShareholderWire(item)) && value.shareholders.length >= 1 && value.shareholders.length <= 100
  );
}

function isLedgerOpeningShareholderWire(value: unknown): value is LedgerOpeningShareholderWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","name","nationalId","orgNumber","setupId","shareCount","shareholderId","shareholderKind"]) &&
    isUuid(value.companyId) &&
    (typeof value.name === "string" && value.name.length >= 1 && value.name.length <= 255) &&
    ((typeof value.nationalId === "string" && new RegExp("^\\d{11}$", "u").test(value.nationalId)) || value.nationalId === null) &&
    ((typeof value.orgNumber === "string" && new RegExp("^\\d{9}$", "u").test(value.orgNumber)) || value.orgNumber === null) &&
    isUuid(value.setupId) &&
    (typeof value.shareCount === "number" && Number.isInteger(value.shareCount) && value.shareCount >= 0 && value.shareCount <= 2147483647) &&
    isUuid(value.shareholderId) &&
    (value.shareholderKind === "norwegian_person" || value.shareholderKind === "norwegian_company")
  );
}

function isLedgerOpeningSnapshotPageWire(value: unknown): value is LedgerOpeningSnapshotPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["hasMore","items","nextCursor"]) &&
    typeof value.hasMore === "boolean" &&
    Array.isArray(value.items) && value.items.every((item) => isLedgerOpeningSnapshotWire(item)) && value.items.length <= 100 &&
    (typeof value.nextCursor === "string" || value.nextCursor === null)
  );
}

function isLedgerOpeningSnapshotWire(value: unknown): value is LedgerOpeningSnapshotWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankBalance","companyId","createdAt","createdBy","incomeYear","lockedAt","nominalValue","setupId","shareCapital","shareCount","shareholders"]) &&
    isLedgerMoneyWire(value.bankBalance) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isDateTime(value.lockedAt) &&
    isLedgerMoneyWire(value.nominalValue) &&
    isUuid(value.setupId) &&
    isLedgerMoneyWire(value.shareCapital) &&
    (typeof value.shareCount === "number" && Number.isInteger(value.shareCount) && value.shareCount <= 2147483647 && value.shareCount > 0) &&
    Array.isArray(value.shareholders) && value.shareholders.every((item) => isLedgerOpeningShareholderWire(item)) && value.shareholders.length >= 1 && value.shareholders.length <= 100
  );
}

function isLedgerPageWire(value: unknown): value is LedgerPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["hasMore","nextCursor"]) &&
    typeof value.hasMore === "boolean" &&
    (typeof value.nextCursor === "string" || value.nextCursor === null)
  );
}

function isLedgerPeriodLockPageWire(value: unknown): value is LedgerPeriodLockPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items","page"]) &&
    Array.isArray(value.items) && value.items.every((item) => isLedgerPeriodLockWire(item)) &&
    isLedgerPageWire(value.page)
  );
}

function isLedgerPeriodLockWire(value: unknown): value is LedgerPeriodLockWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","incomeYear","lockedAt","lockedBy","periodLockId","reason","replayed"]) &&
    typeof value.companyId === "string" &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    isDateTime(value.lockedAt) &&
    typeof value.lockedBy === "string" &&
    typeof value.periodLockId === "string" &&
    typeof value.reason === "string" &&
    typeof value.replayed === "boolean"
  );
}

function isLedgerReconstructionAssessmentWire(value: unknown): value is LedgerReconstructionAssessmentWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["asOf","assessmentId","companyId","economicFactCount","economicFactsDigest","evidenceDigest","gapCodes","incomeYear","ledgerStateDigest","recordedAt","sourceEvidenceCount","sourceEvidenceDigest","state"]) &&
    typeof value.asOf === "string" &&
    isUuid(value.assessmentId) &&
    isUuid(value.companyId) &&
    ((typeof value.economicFactCount === "number" && Number.isInteger(value.economicFactCount) && value.economicFactCount >= 0) || value.economicFactCount === null) &&
    ((typeof value.economicFactsDigest === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.economicFactsDigest)) || value.economicFactsDigest === null) &&
    (typeof value.evidenceDigest === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.evidenceDigest)) &&
    Array.isArray(value.gapCodes) && value.gapCodes.every((item) => isReconstructionGapCode(item)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    ((typeof value.ledgerStateDigest === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.ledgerStateDigest)) || value.ledgerStateDigest === null) &&
    isDateTime(value.recordedAt) &&
    ((typeof value.sourceEvidenceCount === "number" && Number.isInteger(value.sourceEvidenceCount) && value.sourceEvidenceCount >= 13 && value.sourceEvidenceCount <= 13) || value.sourceEvidenceCount === null) &&
    ((typeof value.sourceEvidenceDigest === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.sourceEvidenceDigest)) || value.sourceEvidenceDigest === null) &&
    isReconstructionState(value.state)
  );
}

function isReconstructionGapCode(value: unknown): value is ReconstructionGapCode {
  return value === "PRIOR_CLOSING_MISMATCH" || value === "BANK_MOVEMENTS_INCOMPLETE" || value === "BANK_NOT_RECONCILED" || value === "INVESTMENTS_UNCONFIRMED" || value === "SHAREHOLDERS_UNCONFIRMED" || value === "LOANS_UNCONFIRMED" || value === "EQUITY_UNCONFIRMED" || value === "TAX_HISTORY_UNCONFIRMED" || value === "CURRENT_ACTIVITY_INCOMPLETE" || value === "DOCUMENTS_INCOMPLETE" || value === "UNSUPPORTED_ACTIVITY_FOUND";
}

function isLedgerPostedEntryWire(value: unknown): value is LedgerPostedEntryWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","entryId","entryKind","incomeYear","postedAt","replayed"]) &&
    typeof value.companyId === "string" &&
    typeof value.entryId === "string" &&
    isLedgerEntryKind(value.entryKind) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    isDateTime(value.postedAt) &&
    typeof value.replayed === "boolean"
  );
}

function isLedgerRiskFlagWire(value: unknown): value is LedgerRiskFlagWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["account","code"]) &&
    typeof value.account === "string" &&
    isLedgerRiskCode(value.code)
  );
}

function isLedgerRiskCode(value: unknown): value is LedgerRiskCode {
  return value === "MANUAL_JOURNAL_SENSITIVE_ACCOUNT";
}

function isLedgerSourceCapability(value: unknown): value is LedgerSourceCapability {
  return value === "LEDGER" || value === "BANKING" || value === "INVESTMENTS" || value === "CORPORATE_GOVERNANCE" || value === "SHAREHOLDER_REGISTER_FILING" || value === "COMPANY_TAX_FILING" || value === "ANNUAL_ACCOUNTS_FILING" || value === "DOCUMENTS";
}

function isLedgerTaxSettlementWire(value: unknown): value is LedgerTaxSettlementWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["actionId","amount","bankTransactionId","companyId","documentId","documentStatus","incomeYear","settlementDate","settlementKind"]) &&
    isUuid(value.actionId) &&
    isLedgerMoneyWire(value.amount) &&
    (value.bankTransactionId === undefined || (isUuid(value.bankTransactionId) || value.bankTransactionId === null)) &&
    isUuid(value.companyId) &&
    (value.documentId === undefined || (isUuid(value.documentId) || value.documentId === null)) &&
    (value.documentStatus === "attached" || value.documentStatus === "missing_accepted_warning" || value.documentStatus === "not_required") &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    typeof value.settlementDate === "string" &&
    isTaxSettlementKind(value.settlementKind)
  );
}

function isLedgerWriterResultWire(value: unknown): value is LedgerWriterResultWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["postedEntry","replayed"]) &&
    (isLedgerPostedEntryWire(value.postedEntry) || value.postedEntry === null) &&
    typeof value.replayed === "boolean"
  );
}

function isReconstructionState(value: unknown): value is ReconstructionState {
  return value === "BLOCKED" || value === "READY";
}

function isTaxSettlementKind(value: unknown): value is TaxSettlementKind {
  return value === "payable" || value === "payment" || value === "refund";
}

function isInvestmentActivityKind(value: unknown): value is InvestmentActivityKind {
  return value === "share_purchase" || value === "share_sale" || value === "dividend_received" || value === "fund_distribution_received";
}

function isInvestmentCorrectionTargetKind(value: unknown): value is InvestmentCorrectionTargetKind {
  return value === "economic_event" || value === "cash_settlement";
}

function isInvestmentFactReferenceWire(value: unknown): value is InvestmentFactReferenceWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["capability","factSha256","recordId","revision"]) &&
    isInvestmentSourceCapability(value.capability) &&
    (typeof value.factSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.factSha256)) &&
    isUuid(value.recordId) &&
    (typeof value.revision === "number" && Number.isInteger(value.revision) && value.revision >= 1)
  );
}

function isInvestmentSourceCapability(value: unknown): value is InvestmentSourceCapability {
  return value === "BANKING" || value === "DOCUMENTS";
}

function isInvestmentCorrectionPageWire(value: unknown): value is InvestmentCorrectionPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items","page"]) &&
    Array.isArray(value.items) && value.items.every((item) => isInvestmentCorrectionWire(item)) &&
    isInvestmentsPageWire(value.page)
  );
}

function isInvestmentCorrectionWire(value: unknown): value is InvestmentCorrectionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","createdAt","createdBy","documentFacts","evidenceDigest","evidenceMode","evidenceReference","id","incomeYear","legacy","legacyBankTransactionId","legacyDocumentId","legacyDocumentStatus","originalActivityKind","originalRecordId","ownerAttested","reason","replacementAccountingEntryId","replacementActivityKind","replacementRecordId","reversalAccountingEntryId","targetKind"]) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) &&
    (typeof value.evidenceDigest === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.evidenceDigest)) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    typeof value.evidenceReference === "string" &&
    isUuid(value.id) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.legacy === "boolean" &&
    (isUuid(value.legacyBankTransactionId) || value.legacyBankTransactionId === null) &&
    (isUuid(value.legacyDocumentId) || value.legacyDocumentId === null) &&
    (isInvestmentDocumentStatus(value.legacyDocumentStatus) || value.legacyDocumentStatus === null) &&
    isInvestmentActivityKind(value.originalActivityKind) &&
    isUuid(value.originalRecordId) &&
    typeof value.ownerAttested === "boolean" &&
    typeof value.reason === "string" &&
    isUuid(value.replacementAccountingEntryId) &&
    isInvestmentActivityKind(value.replacementActivityKind) &&
    isUuid(value.replacementRecordId) &&
    isUuid(value.reversalAccountingEntryId) &&
    isInvestmentCorrectionTargetKind(value.targetKind)
  );
}

function isInvestmentActivityPageWire(value: unknown): value is InvestmentActivityPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items","page"]) &&
    Array.isArray(value.items) && value.items.every((item) => isInvestmentActivityWire(item)) &&
    isInvestmentsPageWire(value.page)
  );
}

function isInvestmentActivityWire(value: unknown): value is InvestmentActivityWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingClassification","accountingEntryId","acquisitionLotId","actionDate","activityKind","bankTransactionId","bookGainOrLoss","calculationId","capitalizedCost","companyId","createdAt","createdBy","declaredDate","deductibleLoss","dividendPortion","documentId","documentStatus","entitlementDate","evidenceDigest","evidenceMode","evidenceReference","exemptGain","fifoCostBasisReduction","fifoTaxBasisReduction","fundEquityRatioBasisPoints","fundName","fundTaxStatementReference","gainOrLoss","grossAmount","groupEvidenceReference","groupExceptionApplied","groupExceptionClaimed","id","incomeYear","interestPortion","investmentKey","investmentKind","investmentName","lawfulDividendConfirmed","netProceeds","nonDeductibleLoss","openingFundEquityRatioBasisPoints","orgNumber","ownerAttested","payingCompanyName","positionId","proceeds","purchaseAmount","remainingCostBasis","remainingShareCount","remainingTaxBasis","shareCount","soldShareCount","taxGainOrLoss","taxTreatment","taxableAddBack","taxableGain","totalTaxableIncome","transactionCosts","yearEndOwnershipBasisPoints","yearEndVotingBasisPoints"]) &&
    isInvestmentAccountingClassification(value.accountingClassification) &&
    (isUuid(value.accountingEntryId) || value.accountingEntryId === null) &&
    (isUuid(value.acquisitionLotId) || value.acquisitionLotId === null) &&
    typeof value.actionDate === "string" &&
    isInvestmentActivityKind(value.activityKind) &&
    (isUuid(value.bankTransactionId) || value.bankTransactionId === null) &&
    (isLedgerMoneyWire(value.bookGainOrLoss) || value.bookGainOrLoss === null) &&
    (typeof value.calculationId === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.calculationId)) &&
    (isLedgerMoneyWire(value.capitalizedCost) || value.capitalizedCost === null) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    (typeof value.declaredDate === "string" || value.declaredDate === null) &&
    (isLedgerMoneyWire(value.deductibleLoss) || value.deductibleLoss === null) &&
    (isLedgerMoneyWire(value.dividendPortion) || value.dividendPortion === null) &&
    (isUuid(value.documentId) || value.documentId === null) &&
    isInvestmentDocumentStatus(value.documentStatus) &&
    (typeof value.entitlementDate === "string" || value.entitlementDate === null) &&
    (typeof value.evidenceDigest === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.evidenceDigest)) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    typeof value.evidenceReference === "string" &&
    (isLedgerMoneyWire(value.exemptGain) || value.exemptGain === null) &&
    (isLedgerMoneyWire(value.fifoCostBasisReduction) || value.fifoCostBasisReduction === null) &&
    (isLedgerMoneyWire(value.fifoTaxBasisReduction) || value.fifoTaxBasisReduction === null) &&
    (typeof value.fundEquityRatioBasisPoints === "number" && Number.isInteger(value.fundEquityRatioBasisPoints) || value.fundEquityRatioBasisPoints === null) &&
    (typeof value.fundName === "string" || value.fundName === null) &&
    (typeof value.fundTaxStatementReference === "string" || value.fundTaxStatementReference === null) &&
    (isLedgerMoneyWire(value.gainOrLoss) || value.gainOrLoss === null) &&
    (isLedgerMoneyWire(value.grossAmount) || value.grossAmount === null) &&
    (typeof value.groupEvidenceReference === "string" || value.groupEvidenceReference === null) &&
    (typeof value.groupExceptionApplied === "boolean" || value.groupExceptionApplied === null) &&
    (typeof value.groupExceptionClaimed === "boolean" || value.groupExceptionClaimed === null) &&
    isUuid(value.id) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    (isLedgerMoneyWire(value.interestPortion) || value.interestPortion === null) &&
    typeof value.investmentKey === "string" &&
    isInvestmentKind(value.investmentKind) &&
    typeof value.investmentName === "string" &&
    (typeof value.lawfulDividendConfirmed === "boolean" || value.lawfulDividendConfirmed === null) &&
    (isLedgerMoneyWire(value.netProceeds) || value.netProceeds === null) &&
    (isLedgerMoneyWire(value.nonDeductibleLoss) || value.nonDeductibleLoss === null) &&
    (typeof value.openingFundEquityRatioBasisPoints === "number" && Number.isInteger(value.openingFundEquityRatioBasisPoints) || value.openingFundEquityRatioBasisPoints === null) &&
    (typeof value.orgNumber === "string" || value.orgNumber === null) &&
    typeof value.ownerAttested === "boolean" &&
    (typeof value.payingCompanyName === "string" || value.payingCompanyName === null) &&
    isUuid(value.positionId) &&
    (isLedgerMoneyWire(value.proceeds) || value.proceeds === null) &&
    (isLedgerMoneyWire(value.purchaseAmount) || value.purchaseAmount === null) &&
    (isLedgerMoneyWire(value.remainingCostBasis) || value.remainingCostBasis === null) &&
    ((typeof value.remainingShareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.remainingShareCount)) || value.remainingShareCount === null) &&
    (isLedgerMoneyWire(value.remainingTaxBasis) || value.remainingTaxBasis === null) &&
    ((typeof value.shareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.shareCount)) || value.shareCount === null) &&
    ((typeof value.soldShareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.soldShareCount)) || value.soldShareCount === null) &&
    (isLedgerMoneyWire(value.taxGainOrLoss) || value.taxGainOrLoss === null) &&
    isInvestmentTaxTreatment(value.taxTreatment) &&
    (isLedgerMoneyWire(value.taxableAddBack) || value.taxableAddBack === null) &&
    (isLedgerMoneyWire(value.taxableGain) || value.taxableGain === null) &&
    (isLedgerMoneyWire(value.totalTaxableIncome) || value.totalTaxableIncome === null) &&
    (isLedgerMoneyWire(value.transactionCosts) || value.transactionCosts === null) &&
    (typeof value.yearEndOwnershipBasisPoints === "number" && Number.isInteger(value.yearEndOwnershipBasisPoints) || value.yearEndOwnershipBasisPoints === null) &&
    (typeof value.yearEndVotingBasisPoints === "number" && Number.isInteger(value.yearEndVotingBasisPoints) || value.yearEndVotingBasisPoints === null)
  );
}

function isInvestmentLifecycleEventPageWire(value: unknown): value is InvestmentLifecycleEventPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items","page"]) &&
    Array.isArray(value.items) && value.items.every((item) => isInvestmentLifecycleEventWire(item)) &&
    isInvestmentsPageWire(value.page)
  );
}

function isInvestmentLifecycleEventWire(value: unknown): value is InvestmentLifecycleEventWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingClassification","acquisitionLotId","activityKind","bankFact","bookGainOrLoss","calculationId","capitalizedCost","companyId","createdAt","createdBy","deductibleLoss","dividendPortion","documentFacts","entitlementDate","evidenceDigest","evidenceMode","evidenceReference","exemptGain","expectedSettlementAmount","fifoCostBasisReduction","fifoTaxBasisReduction","fundEquityRatioBasisPoints","fundName","fundTaxStatementReference","grossAmount","groupEvidenceReference","groupExceptionApplied","groupExceptionClaimed","id","incomeYear","interestPortion","investmentKey","investmentKind","investmentName","lawfulDividendConfirmed","netProceeds","nonDeductibleLoss","openingFundEquityRatioBasisPoints","orgNumber","ownerAttested","payingCompanyName","positionCreated","positionId","proceeds","purchaseAmount","recognitionAccountingEntryId","recognitionDate","remainingCostBasis","remainingShareCount","remainingTaxBasis","settlementAccountingEntryId","settlementAmount","settlementBalanceKind","settlementDate","settlementId","shareCount","soldShareCount","taxGainOrLoss","taxTreatment","taxableAddBack","taxableGain","totalTaxableIncome","transactionCosts","yearEndOwnershipBasisPoints","yearEndVotingBasisPoints"]) &&
    isInvestmentAccountingClassification(value.accountingClassification) &&
    (isUuid(value.acquisitionLotId) || value.acquisitionLotId === null) &&
    isInvestmentActivityKind(value.activityKind) &&
    (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null) &&
    (isLedgerMoneyWire(value.bookGainOrLoss) || value.bookGainOrLoss === null) &&
    (typeof value.calculationId === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.calculationId)) &&
    (isLedgerMoneyWire(value.capitalizedCost) || value.capitalizedCost === null) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    (isLedgerMoneyWire(value.deductibleLoss) || value.deductibleLoss === null) &&
    (isLedgerMoneyWire(value.dividendPortion) || value.dividendPortion === null) &&
    Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) &&
    (typeof value.entitlementDate === "string" || value.entitlementDate === null) &&
    (typeof value.evidenceDigest === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.evidenceDigest)) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    typeof value.evidenceReference === "string" &&
    (isLedgerMoneyWire(value.exemptGain) || value.exemptGain === null) &&
    isLedgerMoneyWire(value.expectedSettlementAmount) &&
    (isLedgerMoneyWire(value.fifoCostBasisReduction) || value.fifoCostBasisReduction === null) &&
    (isLedgerMoneyWire(value.fifoTaxBasisReduction) || value.fifoTaxBasisReduction === null) &&
    (typeof value.fundEquityRatioBasisPoints === "number" && Number.isInteger(value.fundEquityRatioBasisPoints) || value.fundEquityRatioBasisPoints === null) &&
    (typeof value.fundName === "string" || value.fundName === null) &&
    (typeof value.fundTaxStatementReference === "string" || value.fundTaxStatementReference === null) &&
    (isLedgerMoneyWire(value.grossAmount) || value.grossAmount === null) &&
    (typeof value.groupEvidenceReference === "string" || value.groupEvidenceReference === null) &&
    (typeof value.groupExceptionApplied === "boolean" || value.groupExceptionApplied === null) &&
    (typeof value.groupExceptionClaimed === "boolean" || value.groupExceptionClaimed === null) &&
    isUuid(value.id) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    (isLedgerMoneyWire(value.interestPortion) || value.interestPortion === null) &&
    typeof value.investmentKey === "string" &&
    isInvestmentKind(value.investmentKind) &&
    typeof value.investmentName === "string" &&
    (typeof value.lawfulDividendConfirmed === "boolean" || value.lawfulDividendConfirmed === null) &&
    (isLedgerMoneyWire(value.netProceeds) || value.netProceeds === null) &&
    (isLedgerMoneyWire(value.nonDeductibleLoss) || value.nonDeductibleLoss === null) &&
    (typeof value.openingFundEquityRatioBasisPoints === "number" && Number.isInteger(value.openingFundEquityRatioBasisPoints) || value.openingFundEquityRatioBasisPoints === null) &&
    (typeof value.orgNumber === "string" || value.orgNumber === null) &&
    typeof value.ownerAttested === "boolean" &&
    (typeof value.payingCompanyName === "string" || value.payingCompanyName === null) &&
    (typeof value.positionCreated === "boolean" || value.positionCreated === null) &&
    isUuid(value.positionId) &&
    (isLedgerMoneyWire(value.proceeds) || value.proceeds === null) &&
    (isLedgerMoneyWire(value.purchaseAmount) || value.purchaseAmount === null) &&
    isUuid(value.recognitionAccountingEntryId) &&
    typeof value.recognitionDate === "string" &&
    (isLedgerMoneyWire(value.remainingCostBasis) || value.remainingCostBasis === null) &&
    ((typeof value.remainingShareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.remainingShareCount)) || value.remainingShareCount === null) &&
    (isLedgerMoneyWire(value.remainingTaxBasis) || value.remainingTaxBasis === null) &&
    (isUuid(value.settlementAccountingEntryId) || value.settlementAccountingEntryId === null) &&
    (isLedgerMoneyWire(value.settlementAmount) || value.settlementAmount === null) &&
    isInvestmentSettlementBalanceKind(value.settlementBalanceKind) &&
    (typeof value.settlementDate === "string" || value.settlementDate === null) &&
    (isUuid(value.settlementId) || value.settlementId === null) &&
    ((typeof value.shareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.shareCount)) || value.shareCount === null) &&
    ((typeof value.soldShareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.soldShareCount)) || value.soldShareCount === null) &&
    (isLedgerMoneyWire(value.taxGainOrLoss) || value.taxGainOrLoss === null) &&
    isInvestmentTaxTreatment(value.taxTreatment) &&
    (isLedgerMoneyWire(value.taxableAddBack) || value.taxableAddBack === null) &&
    (isLedgerMoneyWire(value.taxableGain) || value.taxableGain === null) &&
    (isLedgerMoneyWire(value.totalTaxableIncome) || value.totalTaxableIncome === null) &&
    (isLedgerMoneyWire(value.transactionCosts) || value.transactionCosts === null) &&
    (typeof value.yearEndOwnershipBasisPoints === "number" && Number.isInteger(value.yearEndOwnershipBasisPoints) || value.yearEndOwnershipBasisPoints === null) &&
    (typeof value.yearEndVotingBasisPoints === "number" && Number.isInteger(value.yearEndVotingBasisPoints) || value.yearEndVotingBasisPoints === null)
  );
}

function isAcquisitionLotPageWire(value: unknown): value is AcquisitionLotPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items","page"]) &&
    Array.isArray(value.items) && value.items.every((item) => isAcquisitionLotWire(item)) &&
    isInvestmentsPageWire(value.page)
  );
}

function isAcquisitionLotWire(value: unknown): value is AcquisitionLotWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["acquisitionActionId","acquisitionDate","acquisitionYearFundEquityRatioBasisPoints","companyId","createdAt","createdBy","fundTaxStatementReference","id","originalCostBasis","originalShareCount","originalTaxBasis","positionId","remainingCostBasis","remainingShareCount","remainingTaxBasis"]) &&
    isUuid(value.acquisitionActionId) &&
    typeof value.acquisitionDate === "string" &&
    (typeof value.acquisitionYearFundEquityRatioBasisPoints === "number" && Number.isInteger(value.acquisitionYearFundEquityRatioBasisPoints) || value.acquisitionYearFundEquityRatioBasisPoints === null) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    (typeof value.fundTaxStatementReference === "string" || value.fundTaxStatementReference === null) &&
    isUuid(value.id) &&
    isLedgerMoneyWire(value.originalCostBasis) &&
    (typeof value.originalShareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.originalShareCount)) &&
    isLedgerMoneyWire(value.originalTaxBasis) &&
    isUuid(value.positionId) &&
    isLedgerMoneyWire(value.remainingCostBasis) &&
    (typeof value.remainingShareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.remainingShareCount)) &&
    isLedgerMoneyWire(value.remainingTaxBasis)
  );
}

function isInvestmentAccountingClassification(value: unknown): value is InvestmentAccountingClassification {
  return value === "subsidiary" || value === "associate" || value === "other_long_term" || value === "current_listed_share" || value === "current_fund";
}

function isInvestmentDocumentStatus(value: unknown): value is InvestmentDocumentStatus {
  return value === "attached" || value === "missing_accepted_warning" || value === "not_required";
}

function isInvestmentEvidenceMode(value: unknown): value is InvestmentEvidenceMode {
  return value === "linked_sources" || value === "manual_fallback";
}

function isInvestmentKind(value: unknown): value is InvestmentKind {
  return value === "norwegian_private_company" || value === "norwegian_listed_share" || value === "norwegian_equity_fund";
}

function isInvestmentLotHistoryStatus(value: unknown): value is InvestmentLotHistoryStatus {
  return value === "complete" || value === "needs_reconstruction";
}

function isInvestmentMeasurementRule(value: unknown): value is InvestmentMeasurementRule {
  return value === "lower_of_cost_and_fair_value" || value === "cost_with_evidenced_impairment";
}

function isInvestmentSettlementBalanceKind(value: unknown): value is InvestmentSettlementBalanceKind {
  return value === "purchase_payable" || value === "sale_receivable" || value === "dividend_receivable" || value === "fund_distribution_receivable";
}

function isInvestmentTaxTreatment(value: unknown): value is InvestmentTaxTreatment {
  return value === "fritaksmetoden";
}

function isInvestmentTradingProfile(value: unknown): value is InvestmentTradingProfile {
  return value === "low_volume_non_active" || value === "active_or_high_volume" || value === "unknown";
}

function isInvestmentPositionPageWire(value: unknown): value is InvestmentPositionPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items","page"]) &&
    Array.isArray(value.items) && value.items.every((item) => isInvestmentPositionWire(item)) &&
    isInvestmentsPageWire(value.page)
  );
}

function isInvestmentPositionMovementWire(value: unknown): value is InvestmentPositionMovementWire {
  return (
    isRecord(value) &&
    typeof value.movement_date === "string" &&
    typeof value.movement_type === "string" &&
    (typeof value.share_delta === "string" && new RegExp("^-?(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.share_delta))
  );
}

function isInvestmentPositionWire(value: unknown): value is InvestmentPositionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingClassification","companyId","costBasis","createdAt","createdBy","fundEquityRatioBasisPoints","fundTaxStatementReference","id","investmentKey","kind","lotHistoryStatus","movementCount","movements","name","orgNumber","shareCount","taxBasis","taxTreatment","updatedAt"]) &&
    isInvestmentAccountingClassification(value.accountingClassification) &&
    isUuid(value.companyId) &&
    isLedgerMoneyWire(value.costBasis) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    (typeof value.fundEquityRatioBasisPoints === "number" && Number.isInteger(value.fundEquityRatioBasisPoints) || value.fundEquityRatioBasisPoints === null) &&
    (typeof value.fundTaxStatementReference === "string" || value.fundTaxStatementReference === null) &&
    isUuid(value.id) &&
    typeof value.investmentKey === "string" &&
    isInvestmentKind(value.kind) &&
    isInvestmentLotHistoryStatus(value.lotHistoryStatus) &&
    typeof value.movementCount === "number" && Number.isInteger(value.movementCount) &&
    Array.isArray(value.movements) && value.movements.every((item) => isInvestmentPositionMovementWire(item)) &&
    typeof value.name === "string" &&
    (typeof value.orgNumber === "string" || value.orgNumber === null) &&
    (typeof value.shareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.shareCount)) &&
    isLedgerMoneyWire(value.taxBasis) &&
    isInvestmentTaxTreatment(value.taxTreatment) &&
    isDateTime(value.updatedAt)
  );
}

function isInvestmentYearEndMeasurementPageWire(value: unknown): value is InvestmentYearEndMeasurementPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items","page"]) &&
    Array.isArray(value.items) && value.items.every((item) => isInvestmentYearEndMeasurementViewWire(item)) &&
    isInvestmentsPageWire(value.page)
  );
}

function isInvestmentYearEndMeasurementViewWire(value: unknown): value is InvestmentYearEndMeasurementViewWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingEntryId","asOf","calculationId","closingBookValue","companyId","createdAt","createdBy","evidenceDigest","id","impairmentAmount","incomeYear","measurementRule","observedOrRecoverableValue","positionId","preMeasurementBookValue","quantity","reversalAmount","sourceBookCost","taxBasis","taxValue"]) &&
    (isUuid(value.accountingEntryId) || value.accountingEntryId === null) &&
    typeof value.asOf === "string" &&
    (typeof value.calculationId === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.calculationId)) &&
    isLedgerMoneyWire(value.closingBookValue) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    (typeof value.evidenceDigest === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.evidenceDigest)) &&
    isUuid(value.id) &&
    isLedgerMoneyWire(value.impairmentAmount) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    isInvestmentMeasurementRule(value.measurementRule) &&
    isLedgerMoneyWire(value.observedOrRecoverableValue) &&
    isUuid(value.positionId) &&
    isLedgerMoneyWire(value.preMeasurementBookValue) &&
    (typeof value.quantity === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.quantity)) &&
    isLedgerMoneyWire(value.reversalAmount) &&
    isLedgerMoneyWire(value.sourceBookCost) &&
    isLedgerMoneyWire(value.taxBasis) &&
    isLedgerMoneyWire(value.taxValue)
  );
}

function isInvestmentsPageWire(value: unknown): value is InvestmentsPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["hasMore","nextCursor"]) &&
    typeof value.hasMore === "boolean" &&
    (typeof value.nextCursor === "string" || value.nextCursor === null)
  );
}

function isInvestmentsEconomicEventResultWire(value: unknown): value is InvestmentsEconomicEventResultWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["eventId","expectedSettlementAmount","positionId","recognitionAccountingEntryId","replayed","settlementBalanceKind"]) &&
    isUuid(value.eventId) &&
    isLedgerMoneyWire(value.expectedSettlementAmount) &&
    isUuid(value.positionId) &&
    isUuid(value.recognitionAccountingEntryId) &&
    typeof value.replayed === "boolean" &&
    isInvestmentSettlementBalanceKind(value.settlementBalanceKind)
  );
}

function isInvestmentsCashSettlementResultWire(value: unknown): value is InvestmentsCashSettlementResultWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["eventId","replayed","settlementAccountingEntryId","settlementId"]) &&
    isUuid(value.eventId) &&
    typeof value.replayed === "boolean" &&
    isUuid(value.settlementAccountingEntryId) &&
    isUuid(value.settlementId)
  );
}

function isInvestmentsRecognizeSharePurchaseWire(value: unknown): value is InvestmentsRecognizeSharePurchaseWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingClassification","acquisitionDate","bankFact","companyId","documentFacts","equalShareRightsConfirmed","eventId","evidenceMode","evidenceReference","fundEquityRatioBasisPoints","fundTaxStatementReference","incomeYear","investmentKey","investmentKind","investmentName","nonActiveTradingConfirmed","orgNumber","ownerAttested","purchaseAmount","shareClassCode","shareCount","singleShareClassConfirmed","tradingProfile","transactionCosts","unusualShareRightsAbsentConfirmed"]) &&
    isInvestmentAccountingClassification(value.accountingClassification) &&
    typeof value.acquisitionDate === "string" &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    (value.equalShareRightsConfirmed === undefined || (typeof value.equalShareRightsConfirmed === "boolean" || value.equalShareRightsConfirmed === null)) &&
    isUuid(value.eventId) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    (value.fundEquityRatioBasisPoints === undefined || ((typeof value.fundEquityRatioBasisPoints === "number" && Number.isInteger(value.fundEquityRatioBasisPoints) && value.fundEquityRatioBasisPoints >= 0 && value.fundEquityRatioBasisPoints <= 10000) || value.fundEquityRatioBasisPoints === null)) &&
    (value.fundTaxStatementReference === undefined || ((typeof value.fundTaxStatementReference === "string" && value.fundTaxStatementReference.length >= 1 && value.fundTaxStatementReference.length <= 255) || value.fundTaxStatementReference === null)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.investmentKey === "string" && value.investmentKey.length >= 1 && value.investmentKey.length <= 255) &&
    isInvestmentKind(value.investmentKind) &&
    (typeof value.investmentName === "string" && value.investmentName.length >= 1 && value.investmentName.length <= 255) &&
    typeof value.nonActiveTradingConfirmed === "boolean" &&
    (value.orgNumber === undefined || ((typeof value.orgNumber === "string" && new RegExp("^\\d{9}$", "u").test(value.orgNumber)) || value.orgNumber === null)) &&
    typeof value.ownerAttested === "boolean" &&
    isLedgerMoneyWire(value.purchaseAmount) &&
    (value.shareClassCode === undefined || ((typeof value.shareClassCode === "string" && value.shareClassCode.length >= 1 && value.shareClassCode.length <= 80) || value.shareClassCode === null)) &&
    (typeof value.shareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.shareCount)) &&
    (value.singleShareClassConfirmed === undefined || (typeof value.singleShareClassConfirmed === "boolean" || value.singleShareClassConfirmed === null)) &&
    isInvestmentTradingProfile(value.tradingProfile) &&
    isLedgerMoneyWire(value.transactionCosts) &&
    (value.unusualShareRightsAbsentConfirmed === undefined || (typeof value.unusualShareRightsAbsentConfirmed === "boolean" || value.unusualShareRightsAbsentConfirmed === null))
  );
}

function isInvestmentsRecognizeShareSaleWire(value: unknown): value is InvestmentsRecognizeShareSaleWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankFact","companyId","documentFacts","eventId","evidenceMode","evidenceReference","fundTaxStatementReference","incomeYear","ownerAttested","positionId","proceeds","saleDate","saleYearFundEquityRatioBasisPoints","soldShareCount","transactionCosts"]) &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    isUuid(value.eventId) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    (value.fundTaxStatementReference === undefined || ((typeof value.fundTaxStatementReference === "string" && value.fundTaxStatementReference.length >= 1 && value.fundTaxStatementReference.length <= 255) || value.fundTaxStatementReference === null)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    typeof value.ownerAttested === "boolean" &&
    isUuid(value.positionId) &&
    isLedgerMoneyWire(value.proceeds) &&
    typeof value.saleDate === "string" &&
    (value.saleYearFundEquityRatioBasisPoints === undefined || ((typeof value.saleYearFundEquityRatioBasisPoints === "number" && Number.isInteger(value.saleYearFundEquityRatioBasisPoints) && value.saleYearFundEquityRatioBasisPoints >= 0 && value.saleYearFundEquityRatioBasisPoints <= 10000) || value.saleYearFundEquityRatioBasisPoints === null)) &&
    (typeof value.soldShareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.soldShareCount)) &&
    isLedgerMoneyWire(value.transactionCosts)
  );
}

function isInvestmentsRecognizeReceivedDividendWire(value: unknown): value is InvestmentsRecognizeReceivedDividendWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankFact","companyId","declaredDate","documentFacts","eventId","evidenceMode","evidenceReference","grossAmount","groupEvidenceReference","groupExceptionClaimed","incomeYear","lawfulDividendConfirmed","ownerAttested","payingCompanyName","positionId","yearEndOwnershipBasisPoints","yearEndVotingBasisPoints"]) &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    typeof value.declaredDate === "string" &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    isUuid(value.eventId) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    isLedgerMoneyWire(value.grossAmount) &&
    (value.groupEvidenceReference === undefined || ((typeof value.groupEvidenceReference === "string" && value.groupEvidenceReference.length >= 1 && value.groupEvidenceReference.length <= 255) || value.groupEvidenceReference === null)) &&
    typeof value.groupExceptionClaimed === "boolean" &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    typeof value.lawfulDividendConfirmed === "boolean" &&
    typeof value.ownerAttested === "boolean" &&
    (typeof value.payingCompanyName === "string" && value.payingCompanyName.length >= 1 && value.payingCompanyName.length <= 255) &&
    isUuid(value.positionId) &&
    (value.yearEndOwnershipBasisPoints === undefined || ((typeof value.yearEndOwnershipBasisPoints === "number" && Number.isInteger(value.yearEndOwnershipBasisPoints) && value.yearEndOwnershipBasisPoints >= 0 && value.yearEndOwnershipBasisPoints <= 10000) || value.yearEndOwnershipBasisPoints === null)) &&
    (value.yearEndVotingBasisPoints === undefined || ((typeof value.yearEndVotingBasisPoints === "number" && Number.isInteger(value.yearEndVotingBasisPoints) && value.yearEndVotingBasisPoints >= 0 && value.yearEndVotingBasisPoints <= 10000) || value.yearEndVotingBasisPoints === null))
  );
}

function isInvestmentsRecognizeReceivedFundDistributionWire(value: unknown): value is InvestmentsRecognizeReceivedFundDistributionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankFact","companyId","documentFacts","entitlementDate","eventId","evidenceMode","evidenceReference","fundName","fundTaxStatementReference","grossAmount","incomeYear","openingFundEquityRatioBasisPoints","ownerAttested","positionId"]) &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    typeof value.entitlementDate === "string" &&
    isUuid(value.eventId) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    (typeof value.fundName === "string" && value.fundName.length >= 1 && value.fundName.length <= 255) &&
    (typeof value.fundTaxStatementReference === "string" && value.fundTaxStatementReference.length >= 1 && value.fundTaxStatementReference.length <= 255) &&
    isLedgerMoneyWire(value.grossAmount) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.openingFundEquityRatioBasisPoints === "number" && Number.isInteger(value.openingFundEquityRatioBasisPoints) && value.openingFundEquityRatioBasisPoints >= 0 && value.openingFundEquityRatioBasisPoints <= 10000) &&
    typeof value.ownerAttested === "boolean" &&
    isUuid(value.positionId)
  );
}

function isInvestmentsSettleCashWire(value: unknown): value is InvestmentsSettleCashWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","bankFact","companyId","documentFacts","eventId","evidenceMode","evidenceReference","incomeYear","ownerAttested","settlementDate","settlementId"]) &&
    isLedgerMoneyWire(value.amount) &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    isUuid(value.eventId) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    typeof value.ownerAttested === "boolean" &&
    typeof value.settlementDate === "string" &&
    isUuid(value.settlementId)
  );
}

function isInvestmentsYearEndMeasurementResultWire(value: unknown): value is InvestmentsYearEndMeasurementResultWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingEntryId","closingBookValue","measurementId","measurementRule","positionId","replayed","taxBasis","taxValue"]) &&
    (isUuid(value.accountingEntryId) || value.accountingEntryId === null) &&
    isLedgerMoneyWire(value.closingBookValue) &&
    isUuid(value.measurementId) &&
    isInvestmentMeasurementRule(value.measurementRule) &&
    isUuid(value.positionId) &&
    typeof value.replayed === "boolean" &&
    isLedgerMoneyWire(value.taxBasis) &&
    isLedgerMoneyWire(value.taxValue)
  );
}

function isInvestmentsYearEndMeasurementWire(value: unknown): value is InvestmentsYearEndMeasurementWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["asOf","bankFact","companyId","documentFacts","evidenceMode","evidenceReference","incomeYear","measurementId","observedOrRecoverableValue","ownerAttested","positionId","taxValue"]) &&
    typeof value.asOf === "string" &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isUuid(value.measurementId) &&
    isLedgerMoneyWire(value.observedOrRecoverableValue) &&
    typeof value.ownerAttested === "boolean" &&
    isUuid(value.positionId) &&
    isLedgerMoneyWire(value.taxValue)
  );
}

function isInvestmentsCorrectionResultWire(value: unknown): value is InvestmentsCorrectionResultWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["correctionId","originalRecordId","replacementAccountingEntryId","replacementRecordId","replayed","reversalAccountingEntryId","targetKind"]) &&
    isUuid(value.correctionId) &&
    isUuid(value.originalRecordId) &&
    isUuid(value.replacementAccountingEntryId) &&
    isUuid(value.replacementRecordId) &&
    typeof value.replayed === "boolean" &&
    isUuid(value.reversalAccountingEntryId) &&
    isInvestmentCorrectionTargetKind(value.targetKind)
  );
}

function isInvestmentsCorrectionWire(value: unknown): value is InvestmentsCorrectionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankFact","companyId","correctionDate","correctionId","documentFacts","evidenceMode","evidenceReference","incomeYear","originalActivityKind","originalRecordId","originalSettlementId","ownerAttested","reason","replacement","replacementSettlement","settlementCorrectionId","targetKind"]) &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    typeof value.correctionDate === "string" &&
    isUuid(value.correctionId) &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isInvestmentActivityKind(value.originalActivityKind) &&
    isUuid(value.originalRecordId) &&
    (value.originalSettlementId === undefined || (isUuid(value.originalSettlementId) || value.originalSettlementId === null)) &&
    typeof value.ownerAttested === "boolean" &&
    (typeof value.reason === "string" && value.reason.length >= 1 && value.reason.length <= 500) &&
    (isInvestmentsSharePurchaseRecognitionWire(value.replacement) || isInvestmentsShareSaleRecognitionWire(value.replacement) || isInvestmentsDividendRecognitionWire(value.replacement) || isInvestmentsFundDistributionRecognitionWire(value.replacement) || isInvestmentsCashSettlementWire(value.replacement)) &&
    (value.replacementSettlement === undefined || (isInvestmentsReplacementCashSettlementWire(value.replacementSettlement) || value.replacementSettlement === null)) &&
    (value.settlementCorrectionId === undefined || (isUuid(value.settlementCorrectionId) || value.settlementCorrectionId === null)) &&
    isInvestmentCorrectionTargetKind(value.targetKind)
  );
}

function isInvestmentsSharePurchaseRecognitionWire(value: unknown): value is InvestmentsSharePurchaseRecognitionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingClassification","acquisitionDate","bankFact","companyId","documentFacts","equalShareRightsConfirmed","eventId","evidenceMode","evidenceReference","fundEquityRatioBasisPoints","fundTaxStatementReference","incomeYear","investmentKey","investmentKind","investmentName","nonActiveTradingConfirmed","orgNumber","ownerAttested","purchaseAmount","replacementKind","shareClassCode","shareCount","singleShareClassConfirmed","tradingProfile","transactionCosts","unusualShareRightsAbsentConfirmed"]) &&
    isInvestmentAccountingClassification(value.accountingClassification) &&
    typeof value.acquisitionDate === "string" &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    (value.equalShareRightsConfirmed === undefined || (typeof value.equalShareRightsConfirmed === "boolean" || value.equalShareRightsConfirmed === null)) &&
    isUuid(value.eventId) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    (value.fundEquityRatioBasisPoints === undefined || ((typeof value.fundEquityRatioBasisPoints === "number" && Number.isInteger(value.fundEquityRatioBasisPoints) && value.fundEquityRatioBasisPoints >= 0 && value.fundEquityRatioBasisPoints <= 10000) || value.fundEquityRatioBasisPoints === null)) &&
    (value.fundTaxStatementReference === undefined || ((typeof value.fundTaxStatementReference === "string" && value.fundTaxStatementReference.length >= 1 && value.fundTaxStatementReference.length <= 255) || value.fundTaxStatementReference === null)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.investmentKey === "string" && value.investmentKey.length >= 1 && value.investmentKey.length <= 255) &&
    isInvestmentKind(value.investmentKind) &&
    (typeof value.investmentName === "string" && value.investmentName.length >= 1 && value.investmentName.length <= 255) &&
    typeof value.nonActiveTradingConfirmed === "boolean" &&
    (value.orgNumber === undefined || ((typeof value.orgNumber === "string" && new RegExp("^\\d{9}$", "u").test(value.orgNumber)) || value.orgNumber === null)) &&
    typeof value.ownerAttested === "boolean" &&
    isLedgerMoneyWire(value.purchaseAmount) &&
    value.replacementKind === "share_purchase" &&
    (value.shareClassCode === undefined || ((typeof value.shareClassCode === "string" && value.shareClassCode.length >= 1 && value.shareClassCode.length <= 80) || value.shareClassCode === null)) &&
    (typeof value.shareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.shareCount)) &&
    (value.singleShareClassConfirmed === undefined || (typeof value.singleShareClassConfirmed === "boolean" || value.singleShareClassConfirmed === null)) &&
    isInvestmentTradingProfile(value.tradingProfile) &&
    isLedgerMoneyWire(value.transactionCosts) &&
    (value.unusualShareRightsAbsentConfirmed === undefined || (typeof value.unusualShareRightsAbsentConfirmed === "boolean" || value.unusualShareRightsAbsentConfirmed === null))
  );
}

function isInvestmentsShareSaleRecognitionWire(value: unknown): value is InvestmentsShareSaleRecognitionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankFact","companyId","documentFacts","eventId","evidenceMode","evidenceReference","fundTaxStatementReference","incomeYear","ownerAttested","positionId","proceeds","replacementKind","saleDate","saleYearFundEquityRatioBasisPoints","soldShareCount","transactionCosts"]) &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    isUuid(value.eventId) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    (value.fundTaxStatementReference === undefined || ((typeof value.fundTaxStatementReference === "string" && value.fundTaxStatementReference.length >= 1 && value.fundTaxStatementReference.length <= 255) || value.fundTaxStatementReference === null)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    typeof value.ownerAttested === "boolean" &&
    isUuid(value.positionId) &&
    isLedgerMoneyWire(value.proceeds) &&
    value.replacementKind === "share_sale" &&
    typeof value.saleDate === "string" &&
    (value.saleYearFundEquityRatioBasisPoints === undefined || ((typeof value.saleYearFundEquityRatioBasisPoints === "number" && Number.isInteger(value.saleYearFundEquityRatioBasisPoints) && value.saleYearFundEquityRatioBasisPoints >= 0 && value.saleYearFundEquityRatioBasisPoints <= 10000) || value.saleYearFundEquityRatioBasisPoints === null)) &&
    (typeof value.soldShareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.soldShareCount)) &&
    isLedgerMoneyWire(value.transactionCosts)
  );
}

function isInvestmentsDividendRecognitionWire(value: unknown): value is InvestmentsDividendRecognitionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankFact","companyId","declaredDate","documentFacts","eventId","evidenceMode","evidenceReference","grossAmount","groupEvidenceReference","groupExceptionClaimed","incomeYear","lawfulDividendConfirmed","ownerAttested","payingCompanyName","positionId","replacementKind","yearEndOwnershipBasisPoints","yearEndVotingBasisPoints"]) &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    typeof value.declaredDate === "string" &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    isUuid(value.eventId) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    isLedgerMoneyWire(value.grossAmount) &&
    (value.groupEvidenceReference === undefined || ((typeof value.groupEvidenceReference === "string" && value.groupEvidenceReference.length >= 1 && value.groupEvidenceReference.length <= 255) || value.groupEvidenceReference === null)) &&
    typeof value.groupExceptionClaimed === "boolean" &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    typeof value.lawfulDividendConfirmed === "boolean" &&
    typeof value.ownerAttested === "boolean" &&
    (typeof value.payingCompanyName === "string" && value.payingCompanyName.length >= 1 && value.payingCompanyName.length <= 255) &&
    isUuid(value.positionId) &&
    value.replacementKind === "dividend_received" &&
    (value.yearEndOwnershipBasisPoints === undefined || ((typeof value.yearEndOwnershipBasisPoints === "number" && Number.isInteger(value.yearEndOwnershipBasisPoints) && value.yearEndOwnershipBasisPoints >= 0 && value.yearEndOwnershipBasisPoints <= 10000) || value.yearEndOwnershipBasisPoints === null)) &&
    (value.yearEndVotingBasisPoints === undefined || ((typeof value.yearEndVotingBasisPoints === "number" && Number.isInteger(value.yearEndVotingBasisPoints) && value.yearEndVotingBasisPoints >= 0 && value.yearEndVotingBasisPoints <= 10000) || value.yearEndVotingBasisPoints === null))
  );
}

function isInvestmentsFundDistributionRecognitionWire(value: unknown): value is InvestmentsFundDistributionRecognitionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankFact","companyId","documentFacts","entitlementDate","eventId","evidenceMode","evidenceReference","fundName","fundTaxStatementReference","grossAmount","incomeYear","openingFundEquityRatioBasisPoints","ownerAttested","positionId","replacementKind"]) &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    typeof value.entitlementDate === "string" &&
    isUuid(value.eventId) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    (typeof value.fundName === "string" && value.fundName.length >= 1 && value.fundName.length <= 255) &&
    (typeof value.fundTaxStatementReference === "string" && value.fundTaxStatementReference.length >= 1 && value.fundTaxStatementReference.length <= 255) &&
    isLedgerMoneyWire(value.grossAmount) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.openingFundEquityRatioBasisPoints === "number" && Number.isInteger(value.openingFundEquityRatioBasisPoints) && value.openingFundEquityRatioBasisPoints >= 0 && value.openingFundEquityRatioBasisPoints <= 10000) &&
    typeof value.ownerAttested === "boolean" &&
    isUuid(value.positionId) &&
    value.replacementKind === "fund_distribution_received"
  );
}

function isInvestmentsCashSettlementWire(value: unknown): value is InvestmentsCashSettlementWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","bankFact","companyId","documentFacts","eventId","evidenceMode","evidenceReference","incomeYear","ownerAttested","replacementKind","settlementDate","settlementId"]) &&
    isLedgerMoneyWire(value.amount) &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    isUuid(value.eventId) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    typeof value.ownerAttested === "boolean" &&
    value.replacementKind === "cash_settlement" &&
    typeof value.settlementDate === "string" &&
    isUuid(value.settlementId)
  );
}

function isInvestmentsReplacementCashSettlementWire(value: unknown): value is InvestmentsReplacementCashSettlementWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","bankFact","companyId","documentFacts","eventId","evidenceMode","evidenceReference","incomeYear","ownerAttested","replacementKind","settlementDate","settlementId"]) &&
    isLedgerMoneyWire(value.amount) &&
    (value.bankFact === undefined || (isInvestmentFactReferenceWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    (value.documentFacts === undefined || Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isInvestmentFactReferenceWire(item)) && value.documentFacts.length <= 50) &&
    isUuid(value.eventId) &&
    isInvestmentEvidenceMode(value.evidenceMode) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    typeof value.ownerAttested === "boolean" &&
    value.replacementKind === "cash_settlement" &&
    typeof value.settlementDate === "string" &&
    isUuid(value.settlementId)
  );
}

function isShareSaleAllocationPageWire(value: unknown): value is ShareSaleAllocationPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items","page"]) &&
    Array.isArray(value.items) && value.items.every((item) => isShareSaleAllocationWire(item)) &&
    isInvestmentsPageWire(value.page)
  );
}

function isShareSaleAllocationWire(value: unknown): value is ShareSaleAllocationWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["acquisitionDate","allocatedBookCostBasis","allocatedCostBasis","allocatedNetProceeds","allocatedShareCount","allocatedTaxBasis","allocationOrder","averageFundEquityRatioBasisPoints","companyId","createdAt","createdBy","deductibleLoss","exemptGain","id","lotId","nonDeductibleLoss","positionId","saleActionId","taxGainOrLoss","taxableGain"]) &&
    typeof value.acquisitionDate === "string" &&
    isLedgerMoneyWire(value.allocatedBookCostBasis) &&
    isLedgerMoneyWire(value.allocatedCostBasis) &&
    isLedgerMoneyWire(value.allocatedNetProceeds) &&
    (typeof value.allocatedShareCount === "string" && new RegExp("^(?:0|[1-9][0-9]{0,25})(?:\\.[0-9]{1,12})?$", "u").test(value.allocatedShareCount)) &&
    isLedgerMoneyWire(value.allocatedTaxBasis) &&
    typeof value.allocationOrder === "number" && Number.isInteger(value.allocationOrder) &&
    (typeof value.averageFundEquityRatioBasisPoints === "string" || value.averageFundEquityRatioBasisPoints === null) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    isLedgerMoneyWire(value.deductibleLoss) &&
    isLedgerMoneyWire(value.exemptGain) &&
    isUuid(value.id) &&
    isUuid(value.lotId) &&
    isLedgerMoneyWire(value.nonDeductibleLoss) &&
    isUuid(value.positionId) &&
    isUuid(value.saleActionId) &&
    isLedgerMoneyWire(value.taxGainOrLoss) &&
    isLedgerMoneyWire(value.taxableGain)
  );
}

function isDocumentBackupObjectWire(value: unknown): value is DocumentBackupObjectWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["byteLength","contentSha256","contentType","createdAt","createdBy","documentId","documentType","linkedTo","name","removalReason","removedAt","retentionYears","status","storageKey"]) &&
    (typeof value.byteLength === "number" && Number.isInteger(value.byteLength) || value.byteLength === null) &&
    (typeof value.contentSha256 === "string" || value.contentSha256 === null) &&
    typeof value.contentType === "string" &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    isUuid(value.documentId) &&
    typeof value.documentType === "string" &&
    typeof value.linkedTo === "string" &&
    typeof value.name === "string" &&
    (typeof value.removalReason === "string" || value.removalReason === null) &&
    (isDateTime(value.removedAt) || value.removedAt === null) &&
    typeof value.retentionYears === "number" && Number.isInteger(value.retentionYears) &&
    typeof value.status === "string" &&
    typeof value.storageKey === "string"
  );
}

function isDocumentBackupProjectionWire(value: unknown): value is DocumentBackupProjectionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","incomeYear","objects"]) &&
    isUuid(value.companyId) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    Array.isArray(value.objects) && value.objects.every((item) => isDocumentBackupObjectWire(item))
  );
}

function isDocumentBeginUploadWire(value: unknown): value is DocumentBeginUploadWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["byteLength","companyId","contentType","documentId","documentType","fileName","finalStatus","headerBase64","incomeYear","linkedTo"]) &&
    (typeof value.byteLength === "number" && Number.isInteger(value.byteLength) && value.byteLength >= 1 && value.byteLength <= 10485760) &&
    isUuid(value.companyId) &&
    (typeof value.contentType === "string" && value.contentType.length <= 100) &&
    isUuid(value.documentId) &&
    (value.documentType === "bank_statement" || value.documentType === "accounting_document" || value.documentType === "corporate_document" || value.documentType === "authority_feedback") &&
    (typeof value.fileName === "string" && value.fileName.length >= 1 && value.fileName.length <= 255) &&
    (value.finalStatus === undefined || (value.finalStatus === "attached" || value.finalStatus === "generated_unsigned" || value.finalStatus === "signed_owner_attested" || value.finalStatus === "stored")) &&
    (typeof value.headerBase64 === "string" && value.headerBase64.length >= 4 && value.headerBase64.length <= 32) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.linkedTo === "string" && value.linkedTo.length >= 1 && value.linkedTo.length <= 200)
  );
}

function isDocumentListWire(value: unknown): value is DocumentListWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["documents"]) &&
    Array.isArray(value.documents) && value.documents.every((item) => isDocumentWire(item))
  );
}

function isDocumentRemovalRequestWire(value: unknown): value is DocumentRemovalRequestWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["reason"]) &&
    (value.reason === undefined || (typeof value.reason === "string" && value.reason.length >= 1 && value.reason.length <= 200))
  );
}

function isDocumentTransferKind(value: unknown): value is DocumentTransferKind {
  return value === "preview" || value === "download";
}

function isDocumentTransferRequestWire(value: unknown): value is DocumentTransferRequestWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["kind"]) &&
    isDocumentTransferKind(value.kind)
  );
}

function isDocumentTransferWire(value: unknown): value is DocumentTransferWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["document","expiresInSeconds","kind","signedUrl"]) &&
    isDocumentWire(value.document) &&
    typeof value.expiresInSeconds === "number" && Number.isInteger(value.expiresInSeconds) &&
    isDocumentTransferKind(value.kind) &&
    typeof value.signedUrl === "string"
  );
}

function isDocumentUploadTransferWire(value: unknown): value is DocumentUploadTransferWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bucket","document","signedUrl","storageKey","token"]) &&
    value.bucket === "company-documents" &&
    isDocumentWire(value.document) &&
    typeof value.signedUrl === "string" &&
    typeof value.storageKey === "string" &&
    typeof value.token === "string"
  );
}

function isDocumentWire(value: unknown): value is DocumentWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["byteLength","companyId","contentSha256","contentType","createdAt","createdBy","documentType","id","incomeYear","linkedTo","name","removalReason","removedAt","retentionYears","status","storageKey"]) &&
    (typeof value.byteLength === "number" && Number.isInteger(value.byteLength) || value.byteLength === null) &&
    isUuid(value.companyId) &&
    (typeof value.contentSha256 === "string" || value.contentSha256 === null) &&
    typeof value.contentType === "string" &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    typeof value.documentType === "string" &&
    isUuid(value.id) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.linkedTo === "string" &&
    typeof value.name === "string" &&
    (typeof value.removalReason === "string" || value.removalReason === null) &&
    (isDateTime(value.removedAt) || value.removedAt === null) &&
    typeof value.retentionYears === "number" && Number.isInteger(value.retentionYears) &&
    typeof value.status === "string" &&
    typeof value.storageKey === "string"
  );
}

function isAnnualCloseEventKind(value: unknown): value is AnnualCloseEventKind {
  return value === "signing_requested" || value === "rejected" || value === "superseded";
}

function isAnnualCloseEventWire(value: unknown): value is AnnualCloseEventWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","decisionHash","documentSetId","eventId","eventKind","metadata"]) &&
    isUuid(value.companyId) &&
    (typeof value.decisionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.decisionHash)) &&
    isUuid(value.documentSetId) &&
    isUuid(value.eventId) &&
    isAnnualCloseEventKind(value.eventKind) &&
    isRecord(value.metadata) && Object.values(value.metadata).every((item) => typeof item === "string")
  );
}

function isAnnualCloseFinalizationWire(value: unknown): value is AnnualCloseFinalizationWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","decisionHash","documentSetId","finalizationId"]) &&
    isUuid(value.companyId) &&
    (typeof value.decisionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.decisionHash)) &&
    isUuid(value.documentSetId) &&
    isUuid(value.finalizationId)
  );
}

function isAnnualCloseLifecycleWire(value: unknown): value is AnnualCloseLifecycleWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","decisionHash","decisionId","documentSetId","finalizationId","generatedArtifactHashes","incomeYear","replayed","signedArtifactHashes","state"]) &&
    isUuid(value.companyId) &&
    typeof value.decisionHash === "string" &&
    isUuid(value.decisionId) &&
    isUuid(value.documentSetId) &&
    (isUuid(value.finalizationId) || value.finalizationId === null) &&
    isRecord(value.generatedArtifactHashes) && Object.values(value.generatedArtifactHashes).every((item) => typeof item === "string") &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.replayed === "boolean" &&
    isRecord(value.signedArtifactHashes) && Object.values(value.signedArtifactHashes).every((item) => typeof item === "string") &&
    isOwnerDividendState(value.state)
  );
}

function isAnnualCloseProposalWire(value: unknown): value is AnnualCloseProposalWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["annualBasis","annualResultAllocationOre","boardMeeting","boardParticipants","company","companyId","decisionId","documentSetId","fullBoardParticipationConfirmed","generalMeeting","incomeYear","oneShareClassConfirmed","prudentEquityAndLiquidityConfirmed","reviewedFacts","shareholderBallots","shareholders","supportedDividendBasisConfirmed","unanimousBoardConfirmed"]) &&
    isCorporateAnnualBasisWire(value.annualBasis) &&
    (typeof value.annualResultAllocationOre === "number" && Number.isInteger(value.annualResultAllocationOre) && value.annualResultAllocationOre >= -9007199254740991 && value.annualResultAllocationOre <= 9007199254740991) &&
    isCorporateBoardMeetingWire(value.boardMeeting) &&
    Array.isArray(value.boardParticipants) && value.boardParticipants.every((item) => isCorporateBoardParticipantWire(item)) && value.boardParticipants.length >= 1 && value.boardParticipants.length <= 100 &&
    isCorporateCompanyFactsWire(value.company) &&
    isUuid(value.companyId) &&
    isUuid(value.decisionId) &&
    isUuid(value.documentSetId) &&
    typeof value.fullBoardParticipationConfirmed === "boolean" &&
    isCorporateGeneralMeetingWire(value.generalMeeting) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2200) &&
    typeof value.oneShareClassConfirmed === "boolean" &&
    typeof value.prudentEquityAndLiquidityConfirmed === "boolean" &&
    isCorporateReviewedFactsWire(value.reviewedFacts) &&
    Array.isArray(value.shareholderBallots) && value.shareholderBallots.every((item) => isCorporateShareholderBallotWire(item)) && value.shareholderBallots.length >= 1 && value.shareholderBallots.length <= 10000 &&
    Array.isArray(value.shareholders) && value.shareholders.every((item) => isCorporateShareholderWire(item)) && value.shareholders.length >= 1 && value.shareholders.length <= 10000 &&
    typeof value.supportedDividendBasisConfirmed === "boolean" &&
    typeof value.unanimousBoardConfirmed === "boolean"
  );
}

function isAnnualCloseSignedArtifactWire(value: unknown): value is AnnualCloseSignedArtifactWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["artifactKind","byteLength","companyId","contentSha256","decisionHash","documentSetId","filename","signedArtifactId","signedDocumentId","unsignedArtifactId"]) &&
    (value.artifactKind === "annual_board_minutes" || value.artifactKind === "annual_general_meeting_minutes") &&
    (typeof value.byteLength === "number" && Number.isInteger(value.byteLength) && value.byteLength >= 1 && value.byteLength <= 10485760) &&
    isUuid(value.companyId) &&
    (typeof value.contentSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.contentSha256)) &&
    (typeof value.decisionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.decisionHash)) &&
    isUuid(value.documentSetId) &&
    (typeof value.filename === "string" && value.filename.length >= 1 && value.filename.length <= 255) &&
    isUuid(value.signedArtifactId) &&
    isUuid(value.signedDocumentId) &&
    isUuid(value.unsignedArtifactId)
  );
}

function isBoardRole(value: unknown): value is BoardRole {
  return value === "chair" || value === "member";
}

function isBoardTreatmentMethod(value: unknown): value is BoardTreatmentMethod {
  return value === "physical" || value === "video" || value === "written";
}

function isBankLoanEventFactsWire(value: unknown): value is BankLoanEventFactsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["factType","fee","interest","lenderAllocationConfirmed","lenderName","noComplexTerms","norwegianLender","ordinaryTerms","principal","signedAgreement"]) &&
    value.factType === "bank_loan" &&
    isLedgerMoneyWire(value.fee) &&
    isLedgerMoneyWire(value.interest) &&
    typeof value.lenderAllocationConfirmed === "boolean" &&
    (typeof value.lenderName === "string" && value.lenderName.length >= 1 && value.lenderName.length <= 255) &&
    typeof value.noComplexTerms === "boolean" &&
    typeof value.norwegianLender === "boolean" &&
    typeof value.ordinaryTerms === "boolean" &&
    isLedgerMoneyWire(value.principal) &&
    typeof value.signedAgreement === "boolean"
  );
}

function isCashCapitalIncreaseEventFactsWire(value: unknown): value is CashCapitalIncreaseEventFactsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bindingSubscription","cashOnly","factType","fullTimelyPayment","independentConfirmation","issueCostsResolved","issuedShareCount","noDirectUseException","noSpecialTerms","nominalIncrease","norwegianSubscribersOnly","registerReconciled","sharePremium","singleOrdinaryClass"]) &&
    typeof value.bindingSubscription === "boolean" &&
    typeof value.cashOnly === "boolean" &&
    value.factType === "cash_capital_increase" &&
    typeof value.fullTimelyPayment === "boolean" &&
    typeof value.independentConfirmation === "boolean" &&
    typeof value.issueCostsResolved === "boolean" &&
    (typeof value.issuedShareCount === "number" && Number.isInteger(value.issuedShareCount) && value.issuedShareCount >= 1) &&
    typeof value.noDirectUseException === "boolean" &&
    typeof value.noSpecialTerms === "boolean" &&
    isLedgerMoneyWire(value.nominalIncrease) &&
    typeof value.norwegianSubscribersOnly === "boolean" &&
    typeof value.registerReconciled === "boolean" &&
    isLedgerMoneyWire(value.sharePremium) &&
    typeof value.singleOrdinaryClass === "boolean"
  );
}

function isCorporateAnnualBasisWire(value: unknown): value is CorporateAnnualBasisWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["annualDataSha256","availableDistributionOre","cashOre","equityOre","governanceBasisSha256","incomeYear","latestApproved","resultAfterTaxOre","sourceId"]) &&
    (typeof value.annualDataSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.annualDataSha256)) &&
    (typeof value.availableDistributionOre === "number" && Number.isInteger(value.availableDistributionOre) && value.availableDistributionOre >= 0 && value.availableDistributionOre <= 9007199254740991) &&
    (typeof value.cashOre === "number" && Number.isInteger(value.cashOre) && value.cashOre >= -9007199254740991 && value.cashOre <= 9007199254740991) &&
    (typeof value.equityOre === "number" && Number.isInteger(value.equityOre) && value.equityOre >= -9007199254740991 && value.equityOre <= 9007199254740991) &&
    (typeof value.governanceBasisSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.governanceBasisSha256)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2200) &&
    typeof value.latestApproved === "boolean" &&
    (typeof value.resultAfterTaxOre === "number" && Number.isInteger(value.resultAfterTaxOre) && value.resultAfterTaxOre >= -9007199254740991 && value.resultAfterTaxOre <= 9007199254740991) &&
    isUuid(value.sourceId)
  );
}

function isCorporateArtifactKind(value: unknown): value is CorporateArtifactKind {
  return value === "dividend_board_proposal" || value === "dividend_general_meeting_minutes" || value === "annual_board_minutes" || value === "annual_general_meeting_minutes";
}

function isCorporateArtifactRecordWire(value: unknown): value is CorporateArtifactRecordWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["artifactId","artifactKind","byteLength","companyId","contentSha256","createdAt","createdBy","documentId","documentSetId","incomeYear","supersedesArtifactId","variant"]) &&
    isUuid(value.artifactId) &&
    isCorporateArtifactKind(value.artifactKind) &&
    typeof value.byteLength === "number" && Number.isInteger(value.byteLength) &&
    isUuid(value.companyId) &&
    typeof value.contentSha256 === "string" &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    isUuid(value.documentId) &&
    isUuid(value.documentSetId) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    (isUuid(value.supersedesArtifactId) || value.supersedesArtifactId === null) &&
    isCorporateArtifactVariant(value.variant)
  );
}

function isCorporateArtifactVariant(value: unknown): value is CorporateArtifactVariant {
  return value === "unsigned" || value === "signed_owner_attested";
}

function isCorporateBoardMeetingWire(value: unknown): value is CorporateBoardMeetingWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["meetingDate","meetingTime","place","treatmentMethod"]) &&
    typeof value.meetingDate === "string" &&
    typeof value.meetingTime === "string" &&
    (typeof value.place === "string" && value.place.length >= 1 && value.place.length <= 255) &&
    isBoardTreatmentMethod(value.treatmentMethod)
  );
}

function isCorporateBoardParticipantWire(value: unknown): value is CorporateBoardParticipantWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["name","order","participantId","role"]) &&
    (typeof value.name === "string" && value.name.length >= 1 && value.name.length <= 255) &&
    (typeof value.order === "number" && Number.isInteger(value.order) && value.order >= 0 && value.order <= 10000) &&
    (typeof value.participantId === "string" && value.participantId.length >= 1 && value.participantId.length <= 255) &&
    isBoardRole(value.role)
  );
}

function isCorporateCanonicalBoardParticipantWire(value: unknown): value is CorporateCanonicalBoardParticipantWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["name","participantId","role"]) &&
    typeof value.name === "string" &&
    typeof value.participantId === "string" &&
    isBoardRole(value.role)
  );
}

function isCorporateCanonicalDecisionWire(value: unknown): value is CorporateCanonicalDecisionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["annualBasisYear","annualCloseSourceId","annualResultAllocationOre","boardMeeting","boardParticipants","companyId","confirmations","decisionHash","decisionId","decisionKind","dividend","documentSetId","financialTotals","generalMeeting","incomeYear","legalName","oneShareClassConfirmed","organizationNumber","shareholders","sourceHash","templateFamily","templateVersion","totalCompanyShares"]) &&
    typeof value.annualBasisYear === "number" && Number.isInteger(value.annualBasisYear) &&
    isUuid(value.annualCloseSourceId) &&
    typeof value.annualResultAllocationOre === "number" && Number.isInteger(value.annualResultAllocationOre) &&
    isCorporateBoardMeetingWire(value.boardMeeting) &&
    Array.isArray(value.boardParticipants) && value.boardParticipants.every((item) => isCorporateCanonicalBoardParticipantWire(item)) &&
    isUuid(value.companyId) &&
    isCorporateOwnerDividendConfirmationsWire(value.confirmations) &&
    typeof value.decisionHash === "string" &&
    isUuid(value.decisionId) &&
    (value.decisionKind === "owner_dividend" || value.decisionKind === "annual_close") &&
    (isCorporateOwnerDividendFactsWire(value.dividend) || value.dividend === null) &&
    isUuid(value.documentSetId) &&
    isCorporateFinancialTotalsWire(value.financialTotals) &&
    isCorporateGeneralMeetingWire(value.generalMeeting) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.legalName === "string" &&
    typeof value.oneShareClassConfirmed === "boolean" &&
    typeof value.organizationNumber === "string" &&
    Array.isArray(value.shareholders) && value.shareholders.every((item) => isCorporateCanonicalShareholderWire(item)) &&
    typeof value.sourceHash === "string" &&
    typeof value.templateFamily === "string" &&
    typeof value.templateVersion === "string" &&
    typeof value.totalCompanyShares === "number" && Number.isInteger(value.totalCompanyShares)
  );
}

function isCorporateCanonicalShareholderWire(value: unknown): value is CorporateCanonicalShareholderWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["name","representedShareCount","shareCount","shareholderId","vote"]) &&
    typeof value.name === "string" &&
    typeof value.representedShareCount === "number" && Number.isInteger(value.representedShareCount) &&
    typeof value.shareCount === "number" && Number.isInteger(value.shareCount) &&
    typeof value.shareholderId === "string" &&
    isShareholderVote(value.vote)
  );
}

function isCorporateDecisionKind(value: unknown): value is CorporateDecisionKind {
  return value === "owner_dividend" || value === "annual_close";
}

function isCorporateDecisionFactsWire(value: unknown): value is CorporateDecisionFactsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["annualBasis","company","reviewedFacts","shareholders"]) &&
    isCorporateAnnualBasisWire(value.annualBasis) &&
    isCorporateCompanyFactsWire(value.company) &&
    isCorporateReviewedFactsWire(value.reviewedFacts) &&
    Array.isArray(value.shareholders) && value.shareholders.every((item) => isCorporateShareholderWire(item))
  );
}

function isCorporateDecisionRecordWire(value: unknown): value is CorporateDecisionRecordWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["annualCloseSourceId","canonicalInput","companyId","createdAt","createdBy","decisionHash","decisionId","decisionKind","documentSetId","incomeYear","sourceHash","supersedesDecisionId"]) &&
    isUuid(value.annualCloseSourceId) &&
    isRecord(value.canonicalInput) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    typeof value.decisionHash === "string" &&
    isUuid(value.decisionId) &&
    isCorporateDecisionKind(value.decisionKind) &&
    isUuid(value.documentSetId) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.sourceHash === "string" &&
    (isUuid(value.supersedesDecisionId) || value.supersedesDecisionId === null)
  );
}

function isCorporateDocumentReadinessBlockerWire(value: unknown): value is CorporateDocumentReadinessBlockerWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["code","message"]) &&
    typeof value.code === "string" &&
    typeof value.message === "string"
  );
}

function isCorporateDocumentReadinessWire(value: unknown): value is CorporateDocumentReadinessWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingPolicyVersion","annualSubmissionReady","blockers","companyId","currentSourceHash","currentSourceMatches","decisionHash","decisionId","decisionKind","declaredAmountOre","documentSetId","finalizationId","finalized","generatedArtifactHashes","incomeYear","paidAmountOre","readyForSigning","remainingAmountOre","requiredSigners","signedArtifactHashes","sourceHash","state"]) &&
    (typeof value.accountingPolicyVersion === "string" || value.accountingPolicyVersion === null) &&
    typeof value.annualSubmissionReady === "boolean" &&
    Array.isArray(value.blockers) && value.blockers.every((item) => isCorporateDocumentReadinessBlockerWire(item)) &&
    isUuid(value.companyId) &&
    (typeof value.currentSourceHash === "string" || value.currentSourceHash === null) &&
    (typeof value.currentSourceMatches === "boolean" || value.currentSourceMatches === null) &&
    (typeof value.decisionHash === "string" || value.decisionHash === null) &&
    (isUuid(value.decisionId) || value.decisionId === null) &&
    isCorporateDecisionKind(value.decisionKind) &&
    (typeof value.declaredAmountOre === "number" && Number.isInteger(value.declaredAmountOre) || value.declaredAmountOre === null) &&
    (isUuid(value.documentSetId) || value.documentSetId === null) &&
    (isUuid(value.finalizationId) || value.finalizationId === null) &&
    typeof value.finalized === "boolean" &&
    isRecord(value.generatedArtifactHashes) && Object.values(value.generatedArtifactHashes).every((item) => typeof item === "string") &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    (typeof value.paidAmountOre === "number" && Number.isInteger(value.paidAmountOre) || value.paidAmountOre === null) &&
    typeof value.readyForSigning === "boolean" &&
    (typeof value.remainingAmountOre === "number" && Number.isInteger(value.remainingAmountOre) || value.remainingAmountOre === null) &&
    isRecord(value.requiredSigners) && Object.values(value.requiredSigners).every((item) => Array.isArray(item) && item.every((item) => typeof item === "string")) &&
    isRecord(value.signedArtifactHashes) && Object.values(value.signedArtifactHashes).every((item) => typeof item === "string") &&
    (typeof value.sourceHash === "string" || value.sourceHash === null) &&
    (isOwnerDividendState(value.state) || value.state === null)
  );
}

function isCorporateDocumentSetRecordWire(value: unknown): value is CorporateDocumentSetRecordWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","createdAt","createdBy","decisionHash","decisionId","documentSetId","incomeYear","supersedesDocumentSetId","templateFamily","templateVersion"]) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    typeof value.decisionHash === "string" &&
    isUuid(value.decisionId) &&
    isUuid(value.documentSetId) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    (isUuid(value.supersedesDocumentSetId) || value.supersedesDocumentSetId === null) &&
    typeof value.templateFamily === "string" &&
    typeof value.templateVersion === "string"
  );
}

function isCorporateEventRecordWire(value: unknown): value is CorporateEventRecordWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["actorId","artifactId","companyId","contentSha256","createdAt","decisionHash","decisionId","documentSetId","eventId","eventKind","idempotencyKey","incomeYear","metadata","occurredAt"]) &&
    isUuid(value.actorId) &&
    (isUuid(value.artifactId) || value.artifactId === null) &&
    isUuid(value.companyId) &&
    (typeof value.contentSha256 === "string" || value.contentSha256 === null) &&
    isDateTime(value.createdAt) &&
    typeof value.decisionHash === "string" &&
    isUuid(value.decisionId) &&
    isUuid(value.documentSetId) &&
    isUuid(value.eventId) &&
    typeof value.eventKind === "string" &&
    typeof value.idempotencyKey === "string" &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    isRecord(value.metadata) &&
    isDateTime(value.occurredAt)
  );
}

function isCorporateFinalizationRecordWire(value: unknown): value is CorporateFinalizationRecordWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingEntryId","accountingPolicyVersion","annualCloseSourceId","companyId","createdAt","createdBy","decisionHash","decisionId","finalizationId","finalizationKind","holdingActionId","incomeYear","signedArtifactHashes"]) &&
    (isUuid(value.accountingEntryId) || value.accountingEntryId === null) &&
    (typeof value.accountingPolicyVersion === "string" || value.accountingPolicyVersion === null) &&
    (isUuid(value.annualCloseSourceId) || value.annualCloseSourceId === null) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    typeof value.decisionHash === "string" &&
    isUuid(value.decisionId) &&
    isUuid(value.finalizationId) &&
    typeof value.finalizationKind === "string" &&
    (isUuid(value.holdingActionId) || value.holdingActionId === null) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    isRecord(value.signedArtifactHashes) && Object.values(value.signedArtifactHashes).every((item) => typeof item === "string")
  );
}

function isCorporateCompanyFactsWire(value: unknown): value is CorporateCompanyFactsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["legalName","organizationNumber"]) &&
    (typeof value.legalName === "string" && value.legalName.length >= 1 && value.legalName.length <= 255) &&
    (typeof value.organizationNumber === "string" && new RegExp("^\\d{9}$", "u").test(value.organizationNumber))
  );
}

function isCorporateFinancialTotalsWire(value: unknown): value is CorporateFinancialTotalsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["availableDistributionOre","cashOre","equityOre","resultAfterTaxOre"]) &&
    typeof value.availableDistributionOre === "number" && Number.isInteger(value.availableDistributionOre) &&
    typeof value.cashOre === "number" && Number.isInteger(value.cashOre) &&
    typeof value.equityOre === "number" && Number.isInteger(value.equityOre) &&
    typeof value.resultAfterTaxOre === "number" && Number.isInteger(value.resultAfterTaxOre)
  );
}

function isCorporateGeneralMeetingWire(value: unknown): value is CorporateGeneralMeetingWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["chairName","coSignerName","meetingDate","meetingForm","meetingTime","place"]) &&
    (typeof value.chairName === "string" && value.chairName.length >= 1 && value.chairName.length <= 255) &&
    (typeof value.coSignerName === "string" && value.coSignerName.length >= 1 && value.coSignerName.length <= 255) &&
    typeof value.meetingDate === "string" &&
    isMeetingForm(value.meetingForm) &&
    typeof value.meetingTime === "string" &&
    (typeof value.place === "string" && value.place.length >= 1 && value.place.length <= 255)
  );
}

function isCorporateOwnerDividendConfirmationsWire(value: unknown): value is CorporateOwnerDividendConfirmationsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["fullBoardParticipation","fullShareRepresentation","latestApprovedAnnualAccounts","proportionalAllocation","prudentEquityAndLiquidity","supportedDividendBasis","unanimousBoard","unanimousShareholders"]) &&
    typeof value.fullBoardParticipation === "boolean" &&
    typeof value.fullShareRepresentation === "boolean" &&
    typeof value.latestApprovedAnnualAccounts === "boolean" &&
    typeof value.proportionalAllocation === "boolean" &&
    typeof value.prudentEquityAndLiquidity === "boolean" &&
    typeof value.supportedDividendBasis === "boolean" &&
    typeof value.unanimousBoard === "boolean" &&
    typeof value.unanimousShareholders === "boolean"
  );
}

function isCorporateOwnerDividendFactsWire(value: unknown): value is CorporateOwnerDividendFactsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["allocations","amountOre","liquidityAfterPaymentOre","paymentDate"]) &&
    Array.isArray(value.allocations) && value.allocations.every((item) => isOwnerDividendAllocationWire(item)) &&
    typeof value.amountOre === "number" && Number.isInteger(value.amountOre) &&
    typeof value.liquidityAfterPaymentOre === "number" && Number.isInteger(value.liquidityAfterPaymentOre) &&
    typeof value.paymentDate === "string"
  );
}

function isCorporateLifecycleSnapshotWire(value: unknown): value is CorporateLifecycleSnapshotWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["artifacts","decisions","documentSets","events","finalizations"]) &&
    Array.isArray(value.artifacts) && value.artifacts.every((item) => isCorporateArtifactRecordWire(item)) &&
    Array.isArray(value.decisions) && value.decisions.every((item) => isCorporateDecisionRecordWire(item)) &&
    Array.isArray(value.documentSets) && value.documentSets.every((item) => isCorporateDocumentSetRecordWire(item)) &&
    Array.isArray(value.events) && value.events.every((item) => isCorporateEventRecordWire(item)) &&
    Array.isArray(value.finalizations) && value.finalizations.every((item) => isCorporateFinalizationRecordWire(item))
  );
}

function isCorporateReviewedFactsWire(value: unknown): value is CorporateReviewedFactsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["annualDataSha256","availableDistributionOre","governanceBasisSha256","legalName","organizationNumber","shareholders","totalCompanyShares"]) &&
    (typeof value.annualDataSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.annualDataSha256)) &&
    (typeof value.availableDistributionOre === "number" && Number.isInteger(value.availableDistributionOre) && value.availableDistributionOre >= 0 && value.availableDistributionOre <= 9007199254740991) &&
    (typeof value.governanceBasisSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.governanceBasisSha256)) &&
    (typeof value.legalName === "string" && value.legalName.length >= 1 && value.legalName.length <= 255) &&
    (typeof value.organizationNumber === "string" && new RegExp("^\\d{9}$", "u").test(value.organizationNumber)) &&
    Array.isArray(value.shareholders) && value.shareholders.every((item) => isCorporateReviewedShareholderWire(item)) && value.shareholders.length >= 1 && value.shareholders.length <= 10000 &&
    (typeof value.totalCompanyShares === "number" && Number.isInteger(value.totalCompanyShares) && value.totalCompanyShares <= 9007199254740991 && value.totalCompanyShares > 0)
  );
}

function isCorporateReviewedShareholderWire(value: unknown): value is CorporateReviewedShareholderWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["name","shareCount","shareholderId"]) &&
    (typeof value.name === "string" && value.name.length >= 1 && value.name.length <= 255) &&
    (typeof value.shareCount === "number" && Number.isInteger(value.shareCount) && value.shareCount <= 9007199254740991 && value.shareCount > 0) &&
    (typeof value.shareholderId === "string" && value.shareholderId.length >= 1 && value.shareholderId.length <= 255)
  );
}

function isCorporateShareholderBallotWire(value: unknown): value is CorporateShareholderBallotWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["representedShareCount","shareholderId","vote"]) &&
    (typeof value.representedShareCount === "number" && Number.isInteger(value.representedShareCount) && value.representedShareCount <= 9007199254740991 && value.representedShareCount > 0) &&
    (typeof value.shareholderId === "string" && value.shareholderId.length >= 1 && value.shareholderId.length <= 255) &&
    isShareholderVote(value.vote)
  );
}

function isCorporateShareholderWire(value: unknown): value is CorporateShareholderWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["name","order","shareCount","shareholderId"]) &&
    (typeof value.name === "string" && value.name.length >= 1 && value.name.length <= 255) &&
    (typeof value.order === "number" && Number.isInteger(value.order) && value.order >= 0 && value.order <= 10000) &&
    (typeof value.shareCount === "number" && Number.isInteger(value.shareCount) && value.shareCount <= 9007199254740991 && value.shareCount > 0) &&
    (typeof value.shareholderId === "string" && value.shareholderId.length >= 1 && value.shareholderId.length <= 255)
  );
}

function isGroupContributionEventFactsWire(value: unknown): value is GroupContributionEventFactsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["afterTaxAccountingAmount","bothNorwegian","consolidationNotRequired","corporateApprovalEvidenced","counterpartyName","counterpartyOrganizationNumber","distributionCapacityConfirmed","factType","grossTaxAmount","impairmentCleared","noEquityMethod","noNonCashOrCircularRoute","ownershipBasisPoints","perspective","postAcquisitionIncomeProved","prudentEquityAndLiquidityConfirmed","relatedTax","relationship","votingBasisPoints","yearEndGroupEligibilityProved"]) &&
    isLedgerMoneyWire(value.afterTaxAccountingAmount) &&
    typeof value.bothNorwegian === "boolean" &&
    typeof value.consolidationNotRequired === "boolean" &&
    typeof value.corporateApprovalEvidenced === "boolean" &&
    (typeof value.counterpartyName === "string" && value.counterpartyName.length >= 1 && value.counterpartyName.length <= 255) &&
    (typeof value.counterpartyOrganizationNumber === "string" && new RegExp("^\\d{9}$", "u").test(value.counterpartyOrganizationNumber)) &&
    typeof value.distributionCapacityConfirmed === "boolean" &&
    value.factType === "group_contribution" &&
    isLedgerMoneyWire(value.grossTaxAmount) &&
    typeof value.impairmentCleared === "boolean" &&
    typeof value.noEquityMethod === "boolean" &&
    typeof value.noNonCashOrCircularRoute === "boolean" &&
    (typeof value.ownershipBasisPoints === "number" && Number.isInteger(value.ownershipBasisPoints) && value.ownershipBasisPoints >= 0 && value.ownershipBasisPoints <= 10000) &&
    isSupportedCorporatePerspective(value.perspective) &&
    typeof value.postAcquisitionIncomeProved === "boolean" &&
    typeof value.prudentEquityAndLiquidityConfirmed === "boolean" &&
    isLedgerMoneyWire(value.relatedTax) &&
    isSupportedCorporateRelationship(value.relationship) &&
    (typeof value.votingBasisPoints === "number" && Number.isInteger(value.votingBasisPoints) && value.votingBasisPoints >= 0 && value.votingBasisPoints <= 10000) &&
    typeof value.yearEndGroupEligibilityProved === "boolean"
  );
}

function isIntercompanyLoanEventFactsWire(value: unknown): value is IntercompanyLoanEventFactsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["approvalOrExemptionEvidenced","armLengthConfirmed","counterpartyName","counterpartyOrganizationNumber","factType","interestLimitationCleared","noComplexTerms","norwegianCounterparty","ordinaryTerms","perspective","principal","relationship","signedAgreement"]) &&
    typeof value.approvalOrExemptionEvidenced === "boolean" &&
    typeof value.armLengthConfirmed === "boolean" &&
    (typeof value.counterpartyName === "string" && value.counterpartyName.length >= 1 && value.counterpartyName.length <= 255) &&
    (typeof value.counterpartyOrganizationNumber === "string" && new RegExp("^\\d{9}$", "u").test(value.counterpartyOrganizationNumber)) &&
    value.factType === "intercompany_loan" &&
    typeof value.interestLimitationCleared === "boolean" &&
    typeof value.noComplexTerms === "boolean" &&
    typeof value.norwegianCounterparty === "boolean" &&
    typeof value.ordinaryTerms === "boolean" &&
    isSupportedCorporatePerspective(value.perspective) &&
    isLedgerMoneyWire(value.principal) &&
    isSupportedCorporateRelationship(value.relationship) &&
    typeof value.signedAgreement === "boolean"
  );
}

function isLossCoverageCapitalReductionEventFactsWire(value: unknown): value is LossCoverageCapitalReductionEventFactsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["factType","lossEvidenced","lossOnly","newShareCapital","noCreditorNotice","noSimultaneousCapitalChange","noValueTransfer","nominalReduction","oldShareCapital","otherEquityExhausted","registerReconciled","singleOrdinaryClass","unchangedOwnersAndShareCount"]) &&
    value.factType === "loss_coverage_capital_reduction" &&
    typeof value.lossEvidenced === "boolean" &&
    typeof value.lossOnly === "boolean" &&
    isLedgerMoneyWire(value.newShareCapital) &&
    typeof value.noCreditorNotice === "boolean" &&
    typeof value.noSimultaneousCapitalChange === "boolean" &&
    typeof value.noValueTransfer === "boolean" &&
    isLedgerMoneyWire(value.nominalReduction) &&
    isLedgerMoneyWire(value.oldShareCapital) &&
    typeof value.otherEquityExhausted === "boolean" &&
    typeof value.registerReconciled === "boolean" &&
    typeof value.singleOrdinaryClass === "boolean" &&
    typeof value.unchangedOwnersAndShareCount === "boolean"
  );
}

function isMeetingForm(value: unknown): value is MeetingForm {
  return value === "physical" || value === "video";
}

function isOwnerDividendAllocationWire(value: unknown): value is OwnerDividendAllocationWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amountOre","shareholderId"]) &&
    typeof value.amountOre === "number" && Number.isInteger(value.amountOre) &&
    typeof value.shareholderId === "string"
  );
}

function isOwnerDividendApprovalWire(value: unknown): value is OwnerDividendApprovalWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["approvalEventId","companyId","decisionHash","documentSetId"]) &&
    isUuid(value.approvalEventId) &&
    isUuid(value.companyId) &&
    (typeof value.decisionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.decisionHash)) &&
    isUuid(value.documentSetId)
  );
}

function isOwnerDividendArtifactWire(value: unknown): value is OwnerDividendArtifactWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["artifactId","artifactKind","byteLength","contentSha256","documentId"]) &&
    isUuid(value.artifactId) &&
    isCorporateArtifactKind(value.artifactKind) &&
    (typeof value.byteLength === "number" && Number.isInteger(value.byteLength) && value.byteLength <= 9007199254740991 && value.byteLength > 0) &&
    (typeof value.contentSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.contentSha256)) &&
    isUuid(value.documentId)
  );
}

function isOwnerDividendDocumentsWire(value: unknown): value is OwnerDividendDocumentsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["artifacts","companyId","decisionHash","documentSetId"]) &&
    Array.isArray(value.artifacts) && value.artifacts.every((item) => isOwnerDividendArtifactWire(item)) && value.artifacts.length >= 2 && value.artifacts.length <= 2 &&
    isUuid(value.companyId) &&
    (typeof value.decisionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.decisionHash)) &&
    isUuid(value.documentSetId)
  );
}

function isOwnerDividendEventKind(value: unknown): value is OwnerDividendEventKind {
  return value === "signing_requested" || value === "rejected" || value === "superseded";
}

function isOwnerDividendEventWire(value: unknown): value is OwnerDividendEventWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","decisionHash","documentSetId","eventId","eventKind","metadata"]) &&
    isUuid(value.companyId) &&
    (typeof value.decisionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.decisionHash)) &&
    isUuid(value.documentSetId) &&
    isUuid(value.eventId) &&
    isOwnerDividendEventKind(value.eventKind) &&
    isRecord(value.metadata) && Object.values(value.metadata).every((item) => typeof item === "string")
  );
}

function isOwnerDividendFinalizationWire(value: unknown): value is OwnerDividendFinalizationWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","decisionHash","documentSetId","finalizationId","holdingActionId","incomeYear","ledgerEntryId"]) &&
    isUuid(value.companyId) &&
    (typeof value.decisionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.decisionHash)) &&
    isUuid(value.documentSetId) &&
    isUuid(value.finalizationId) &&
    isUuid(value.holdingActionId) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2200) &&
    isUuid(value.ledgerEntryId)
  );
}

function isOwnerDividendLifecycleWire(value: unknown): value is OwnerDividendLifecycleWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingEntryId","companyId","decisionHash","decisionId","declaredAmountOre","documentSetId","finalizationId","incomeYear","paidAmountOre","remainingAmountOre","replayed","state"]) &&
    (isUuid(value.accountingEntryId) || value.accountingEntryId === null) &&
    isUuid(value.companyId) &&
    typeof value.decisionHash === "string" &&
    isUuid(value.decisionId) &&
    typeof value.declaredAmountOre === "number" && Number.isInteger(value.declaredAmountOre) &&
    isUuid(value.documentSetId) &&
    (isUuid(value.finalizationId) || value.finalizationId === null) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.paidAmountOre === "number" && Number.isInteger(value.paidAmountOre) &&
    typeof value.remainingAmountOre === "number" && Number.isInteger(value.remainingAmountOre) &&
    typeof value.replayed === "boolean" &&
    isOwnerDividendState(value.state)
  );
}

function isOwnerDividendPaymentWire(value: unknown): value is OwnerDividendPaymentWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankTransactionId","companyId","decisionHash","documentSetId","holdingActionId","incomeYear","ledgerEntryId","paymentEventId"]) &&
    isUuid(value.bankTransactionId) &&
    isUuid(value.companyId) &&
    (typeof value.decisionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.decisionHash)) &&
    isUuid(value.documentSetId) &&
    isUuid(value.holdingActionId) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2200) &&
    isUuid(value.ledgerEntryId) &&
    isUuid(value.paymentEventId)
  );
}

function isOwnerDividendProposalWire(value: unknown): value is OwnerDividendProposalWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["annualBasis","boardMeeting","boardParticipants","company","companyId","decisionId","dividendAmountOre","documentSetId","fullBoardParticipationConfirmed","generalMeeting","incomeYear","oneShareClassConfirmed","paymentDate","prudentEquityAndLiquidityConfirmed","reviewedFacts","shareholderBallots","shareholders","supportedDividendBasisConfirmed","unanimousBoardConfirmed"]) &&
    isCorporateAnnualBasisWire(value.annualBasis) &&
    isCorporateBoardMeetingWire(value.boardMeeting) &&
    Array.isArray(value.boardParticipants) && value.boardParticipants.every((item) => isCorporateBoardParticipantWire(item)) && value.boardParticipants.length >= 1 && value.boardParticipants.length <= 100 &&
    isCorporateCompanyFactsWire(value.company) &&
    isUuid(value.companyId) &&
    isUuid(value.decisionId) &&
    (typeof value.dividendAmountOre === "number" && Number.isInteger(value.dividendAmountOre) && value.dividendAmountOre <= 9007199254740991 && value.dividendAmountOre > 0) &&
    isUuid(value.documentSetId) &&
    typeof value.fullBoardParticipationConfirmed === "boolean" &&
    isCorporateGeneralMeetingWire(value.generalMeeting) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2200) &&
    typeof value.oneShareClassConfirmed === "boolean" &&
    typeof value.paymentDate === "string" &&
    typeof value.prudentEquityAndLiquidityConfirmed === "boolean" &&
    isCorporateReviewedFactsWire(value.reviewedFacts) &&
    Array.isArray(value.shareholderBallots) && value.shareholderBallots.every((item) => isCorporateShareholderBallotWire(item)) && value.shareholderBallots.length >= 1 && value.shareholderBallots.length <= 10000 &&
    Array.isArray(value.shareholders) && value.shareholders.every((item) => isCorporateShareholderWire(item)) && value.shareholders.length >= 1 && value.shareholders.length <= 10000 &&
    typeof value.supportedDividendBasisConfirmed === "boolean" &&
    typeof value.unanimousBoardConfirmed === "boolean"
  );
}

function isOwnerDividendSignedArtifactWire(value: unknown): value is OwnerDividendSignedArtifactWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["artifactKind","byteLength","companyId","contentSha256","decisionHash","documentSetId","filename","signedArtifactId","signedDocumentId","unsignedArtifactId"]) &&
    (value.artifactKind === "dividend_board_proposal" || value.artifactKind === "dividend_general_meeting_minutes") &&
    (typeof value.byteLength === "number" && Number.isInteger(value.byteLength) && value.byteLength >= 1 && value.byteLength <= 10485760) &&
    isUuid(value.companyId) &&
    (typeof value.contentSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.contentSha256)) &&
    (typeof value.decisionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.decisionHash)) &&
    isUuid(value.documentSetId) &&
    (typeof value.filename === "string" && value.filename.length >= 1 && value.filename.length <= 255) &&
    isUuid(value.signedArtifactId) &&
    isUuid(value.signedDocumentId) &&
    isUuid(value.unsignedArtifactId)
  );
}

function isOwnerLoanEventFactsWire(value: unknown): value is OwnerLoanEventFactsWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["approvalOrExemptionEvidenced","factType","interestAndTaxTreatmentCleared","noComplexTerms","noSecurityOrConversion","norwegianOwner","ordinaryTerms","ownerIsRecordedShareholder","ownerName","principal","signedAgreement"]) &&
    typeof value.approvalOrExemptionEvidenced === "boolean" &&
    value.factType === "owner_loan" &&
    typeof value.interestAndTaxTreatmentCleared === "boolean" &&
    typeof value.noComplexTerms === "boolean" &&
    typeof value.noSecurityOrConversion === "boolean" &&
    typeof value.norwegianOwner === "boolean" &&
    typeof value.ordinaryTerms === "boolean" &&
    typeof value.ownerIsRecordedShareholder === "boolean" &&
    (typeof value.ownerName === "string" && value.ownerName.length >= 1 && value.ownerName.length <= 255) &&
    isLedgerMoneyWire(value.principal) &&
    typeof value.signedAgreement === "boolean"
  );
}

function isOwnerDividendState(value: unknown): value is OwnerDividendState {
  return value === "proposed" || value === "documents_registered" || value === "facts_approved" || value === "signing_requested" || value === "signed_owner_attested" || value === "finalized" || value === "partially_paid" || value === "paid" || value === "rejected" || value === "superseded";
}

function isProposedOwnerDividendWire(value: unknown): value is ProposedOwnerDividendWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["artifacts","decision","replayed","state"]) &&
    Array.isArray(value.artifacts) && value.artifacts.every((item) => isRenderedCorporateArtifactWire(item)) &&
    isCorporateCanonicalDecisionWire(value.decision) &&
    typeof value.replayed === "boolean" &&
    isOwnerDividendState(value.state)
  );
}

function isProposedAnnualCloseWire(value: unknown): value is ProposedAnnualCloseWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["artifacts","decision","replayed","state"]) &&
    Array.isArray(value.artifacts) && value.artifacts.every((item) => isRenderedCorporateArtifactWire(item)) &&
    isCorporateCanonicalDecisionWire(value.decision) &&
    typeof value.replayed === "boolean" &&
    isOwnerDividendState(value.state)
  );
}

function isRenderedCorporateArtifactWire(value: unknown): value is RenderedCorporateArtifactWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["artifactKind","byteLength","contentBase64","contentSha256","decisionHash","filename"]) &&
    isCorporateArtifactKind(value.artifactKind) &&
    typeof value.byteLength === "number" && Number.isInteger(value.byteLength) &&
    typeof value.contentBase64 === "string" &&
    (typeof value.contentSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.contentSha256)) &&
    (typeof value.decisionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.decisionHash)) &&
    typeof value.filename === "string"
  );
}

function isRecordedShareholderLoanWire(value: unknown): value is RecordedShareholderLoanWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingEntryId","actionId","amountOre","bankTransactionId","companyId","counterpartyName","direction","documentId","documentStatus","incomeYear","interestModelled","loanDate","relatedPartySecurity","replayed"]) &&
    isUuid(value.accountingEntryId) &&
    isUuid(value.actionId) &&
    typeof value.amountOre === "number" && Number.isInteger(value.amountOre) &&
    (isUuid(value.bankTransactionId) || value.bankTransactionId === null) &&
    isUuid(value.companyId) &&
    typeof value.counterpartyName === "string" &&
    isShareholderLoanDirection(value.direction) &&
    (isUuid(value.documentId) || value.documentId === null) &&
    isShareholderLoanDocumentStatus(value.documentStatus) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.interestModelled === "boolean" &&
    typeof value.loanDate === "string" &&
    typeof value.relatedPartySecurity === "boolean" &&
    typeof value.replayed === "boolean"
  );
}

function isRecordedSupportedCorporateEventWire(value: unknown): value is RecordedSupportedCorporateEventWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountingEntryId","bankTransactionId","canonicalFacts","companyId","correctionOfEventId","documentFacts","eventDate","eventId","eventKind","eventReference","factsSha256","finalizationSha256","incomeYear","lifecycleState","phase","policyVersion","recordedAt","replayed","signedArtifactHashes"]) &&
    isUuid(value.accountingEntryId) &&
    (isUuid(value.bankTransactionId) || value.bankTransactionId === null) &&
    isRecord(value.canonicalFacts) &&
    isUuid(value.companyId) &&
    (isUuid(value.correctionOfEventId) || value.correctionOfEventId === null) &&
    Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isSupportedCorporateDocumentFactWire(item)) &&
    typeof value.eventDate === "string" &&
    isUuid(value.eventId) &&
    isSupportedCorporateEventKind(value.eventKind) &&
    isUuid(value.eventReference) &&
    typeof value.factsSha256 === "string" &&
    typeof value.finalizationSha256 === "string" &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    value.lifecycleState === "finalized" &&
    isSupportedCorporateEventPhase(value.phase) &&
    value.policyVersion === "corporate-governance-supported-events-2026.1" &&
    isDateTime(value.recordedAt) &&
    typeof value.replayed === "boolean" &&
    isRecord(value.signedArtifactHashes) && Object.values(value.signedArtifactHashes).every((item) => typeof item === "string")
  );
}

function isReverseSupportedCorporateEventWire(value: unknown): value is ReverseSupportedCorporateEventWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","correctionDocumentFact","incomeYear","reason","reversalDate"]) &&
    isUuid(value.companyId) &&
    isSupportedCorporateDocumentFactWire(value.correctionDocumentFact) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.reason === "string" && value.reason.length >= 1 && value.reason.length <= 500) &&
    typeof value.reversalDate === "string"
  );
}

function isReversedSupportedCorporateEventWire(value: unknown): value is ReversedSupportedCorporateEventWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","incomeYear","originalAccountingEntryId","originalEventId","replayed","reversalAccountingEntryId","reversedAt"]) &&
    isUuid(value.companyId) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    isUuid(value.originalAccountingEntryId) &&
    isUuid(value.originalEventId) &&
    typeof value.replayed === "boolean" &&
    isUuid(value.reversalAccountingEntryId) &&
    isDateTime(value.reversedAt)
  );
}

function isShareholderLoanDirection(value: unknown): value is ShareholderLoanDirection {
  return value === "shareholder_to_company" || value === "company_to_corporate_shareholder" || value === "company_to_personal_shareholder";
}

function isShareholderLoanDocumentStatus(value: unknown): value is ShareholderLoanDocumentStatus {
  return value === "attached" || value === "missing_accepted_warning" || value === "not_required";
}

function isShareholderLoanWire(value: unknown): value is ShareholderLoanWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["actionId","amount","bankTransactionId","companyId","counterpartyName","direction","documentId","documentStatus","incomeYear","interestModelled","ledgerEntryId","loanDate","relatedPartySecurity"]) &&
    isUuid(value.actionId) &&
    isLedgerMoneyWire(value.amount) &&
    (isUuid(value.bankTransactionId) || value.bankTransactionId === null) &&
    isUuid(value.companyId) &&
    (typeof value.counterpartyName === "string" && value.counterpartyName.length >= 1 && value.counterpartyName.length <= 255) &&
    isShareholderLoanDirection(value.direction) &&
    (isUuid(value.documentId) || value.documentId === null) &&
    isShareholderLoanDocumentStatus(value.documentStatus) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2200) &&
    typeof value.interestModelled === "boolean" &&
    isUuid(value.ledgerEntryId) &&
    typeof value.loanDate === "string" &&
    typeof value.relatedPartySecurity === "boolean"
  );
}

function isShareholderVote(value: unknown): value is ShareholderVote {
  return value === "for" || value === "against" || value === "abstain";
}

function isSupportedCorporateBankFactWire(value: unknown): value is SupportedCorporateBankFactWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["signedAmount","sourceSha256","transactionDate","transactionId"]) &&
    isLedgerMoneyWire(value.signedAmount) &&
    (typeof value.sourceSha256 === "string" && new RegExp("^[0-9a-fA-F]{64}$", "u").test(value.sourceSha256)) &&
    typeof value.transactionDate === "string" &&
    isUuid(value.transactionId)
  );
}

function isSupportedCorporateDocumentFactWire(value: unknown): value is SupportedCorporateDocumentFactWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["contentSha256","documentId","evidenceKind","revision"]) &&
    (typeof value.contentSha256 === "string" && new RegExp("^[0-9a-fA-F]{64}$", "u").test(value.contentSha256)) &&
    isUuid(value.documentId) &&
    isSupportedCorporateEvidenceKind(value.evidenceKind) &&
    (typeof value.revision === "number" && Number.isInteger(value.revision) && value.revision >= 1)
  );
}

function isSupportedCorporateEvidenceKind(value: unknown): value is SupportedCorporateEvidenceKind {
  return value === "signed_decision" || value === "signed_agreement" || value === "amended_articles" || value === "contribution_confirmation" || value === "registration_receipt" || value === "shareholder_register" || value === "tax_calculation" || value === "lender_statement" || value === "correction_memo";
}

function isSupportedCorporateEventKind(value: unknown): value is SupportedCorporateEventKind {
  return value === "cash_capital_increase" || value === "loss_coverage_capital_reduction" || value === "intercompany_loan" || value === "owner_loan" || value === "bank_loan" || value === "group_contribution";
}

function isSupportedCorporateEventPhase(value: unknown): value is SupportedCorporateEventPhase {
  return value === "binding_subscription" || value === "restricted_payment" || value === "registered" || value === "decided_not_registered" || value === "first_recognized_after_registration" || value === "funding" || value === "disbursement" || value === "payment" || value === "decision";
}

function isSupportedCorporateEventWire(value: unknown): value is SupportedCorporateEventWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankFact","companyId","documentFacts","eventDate","eventId","eventKind","eventReference","facts","incomeYear","phase","shareholderRegisterFact","taxCalculationFact"]) &&
    (value.bankFact === undefined || (isSupportedCorporateBankFactWire(value.bankFact) || value.bankFact === null)) &&
    isUuid(value.companyId) &&
    Array.isArray(value.documentFacts) && value.documentFacts.every((item) => isSupportedCorporateDocumentFactWire(item)) && value.documentFacts.length >= 1 && value.documentFacts.length <= 12 &&
    typeof value.eventDate === "string" &&
    isUuid(value.eventId) &&
    isSupportedCorporateEventKind(value.eventKind) &&
    isUuid(value.eventReference) &&
    (isCashCapitalIncreaseEventFactsWire(value.facts) || isLossCoverageCapitalReductionEventFactsWire(value.facts) || isIntercompanyLoanEventFactsWire(value.facts) || isOwnerLoanEventFactsWire(value.facts) || isBankLoanEventFactsWire(value.facts) || isGroupContributionEventFactsWire(value.facts)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isSupportedCorporateEventPhase(value.phase) &&
    (value.shareholderRegisterFact === undefined || (isSupportedCorporateSourceFactWire(value.shareholderRegisterFact) || value.shareholderRegisterFact === null)) &&
    (value.taxCalculationFact === undefined || (isSupportedCorporateSourceFactWire(value.taxCalculationFact) || value.taxCalculationFact === null))
  );
}

function isSupportedCorporatePerspective(value: unknown): value is SupportedCorporatePerspective {
  return value === "lender" || value === "borrower" || value === "giver" || value === "recipient";
}

function isSupportedCorporateRelationship(value: unknown): value is SupportedCorporateRelationship {
  return value === "parent_to_subsidiary" || value === "subsidiary_to_parent" || value === "sister_to_sister" || value === "other_same_group";
}

function isSupportedCorporateSourceFactWire(value: unknown): value is SupportedCorporateSourceFactWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["factSha256","recordId","revision"]) &&
    (typeof value.factSha256 === "string" && new RegExp("^[0-9a-fA-F]{64}$", "u").test(value.factSha256)) &&
    isUuid(value.recordId) &&
    (typeof value.revision === "number" && Number.isInteger(value.revision) && value.revision >= 1)
  );
}

function isAcceptBankFileWire(value: unknown): value is AcceptBankFileWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","documentSha256","incomeYear"]) &&
    isUuid(value.companyId) &&
    (typeof value.documentSha256 === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.documentSha256)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100)
  );
}

function isAcceptBankSuggestionWire(value: unknown): value is AcceptBankSuggestionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["acceptanceId","bankTransactionId","companyId","expectedRuleVersion","expectedSuggestion","incomeYear"]) &&
    isUuid(value.acceptanceId) &&
    isUuid(value.bankTransactionId) &&
    isUuid(value.companyId) &&
    (typeof value.expectedRuleVersion === "string" && value.expectedRuleVersion.length >= 1 && value.expectedRuleVersion.length <= 80) &&
    isBankSuggestionKind(value.expectedSuggestion) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100)
  );
}

function isAcceptedBankSuggestionWire(value: unknown): value is AcceptedBankSuggestionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["acceptanceId","acceptedAt","acceptedBy","accountingEntryId","bankTransactionId","replayed","suggestion"]) &&
    isUuid(value.acceptanceId) &&
    isDateTime(value.acceptedAt) &&
    isUuid(value.acceptedBy) &&
    isUuid(value.accountingEntryId) &&
    isUuid(value.bankTransactionId) &&
    typeof value.replayed === "boolean" &&
    isBankSuggestionWire(value.suggestion)
  );
}

function isBankAccountWire(value: unknown): value is BankAccountWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountId","accountKind","connectionId","currency","displayName","earliestCoveredDate","lastSuccessAt","latestCoveredDate","maskedAccount","status"]) &&
    isUuid(value.accountId) &&
    typeof value.accountKind === "string" &&
    isUuid(value.connectionId) &&
    value.currency === "NOK" &&
    typeof value.displayName === "string" &&
    (typeof value.earliestCoveredDate === "string" || value.earliestCoveredDate === null) &&
    (isDateTime(value.lastSuccessAt) || value.lastSuccessAt === null) &&
    (typeof value.latestCoveredDate === "string" || value.latestCoveredDate === null) &&
    typeof value.maskedAccount === "string" &&
    typeof value.status === "string"
  );
}

function isBankConnectionActionWire(value: unknown): value is BankConnectionActionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","connectorId","incomeYear"]) &&
    isUuid(value.companyId) &&
    (typeof value.connectorId === "string" && new RegExp("^[a-z0-9][a-z0-9-]{0,79}$", "u").test(value.connectorId)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100)
  );
}

function isBankConnectionListWire(value: unknown): value is BankConnectionListWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items"]) &&
    Array.isArray(value.items) && value.items.every((item) => isBankConnectionWire(item))
  );
}

function isBankConnectionWire(value: unknown): value is BankConnectionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accounts","companyId","connectionId","connectorId","consentExpiresOn","lastFailureCode","lastSuccessAt","status"]) &&
    Array.isArray(value.accounts) && value.accounts.every((item) => isBankAccountWire(item)) &&
    isUuid(value.companyId) &&
    isUuid(value.connectionId) &&
    typeof value.connectorId === "string" &&
    (typeof value.consentExpiresOn === "string" || value.consentExpiresOn === null) &&
    (typeof value.lastFailureCode === "string" || value.lastFailureCode === null) &&
    (isDateTime(value.lastSuccessAt) || value.lastSuccessAt === null) &&
    typeof value.status === "string"
  );
}

function isBankConsentRedirectWire(value: unknown): value is BankConsentRedirectWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["redirectUrl","state"]) &&
    typeof value.redirectUrl === "string" &&
    typeof value.state === "string"
  );
}

function isBankFileColumnMappingWire(value: unknown): value is BankFileColumnMappingWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","balance","bookingDate","reference","state","text","valueDate"]) &&
    (typeof value.amount === "string" && value.amount.length >= 1 && value.amount.length <= 120) &&
    (value.balance === undefined || ((typeof value.balance === "string" && value.balance.length <= 120) || value.balance === null)) &&
    (typeof value.bookingDate === "string" && value.bookingDate.length >= 1 && value.bookingDate.length <= 120) &&
    (value.reference === undefined || ((typeof value.reference === "string" && value.reference.length <= 120) || value.reference === null)) &&
    (value.state === undefined || ((typeof value.state === "string" && value.state.length <= 120) || value.state === null)) &&
    (typeof value.text === "string" && value.text.length >= 1 && value.text.length <= 120) &&
    (value.valueDate === undefined || ((typeof value.valueDate === "string" && value.valueDate.length <= 120) || value.valueDate === null))
  );
}

function isBankFilePreviewResultWire(value: unknown): value is BankFilePreviewResultWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountMask","closingBalance","correctionCount","currency","documentSha256","duplicateCount","ignoredCount","intervalEnd","intervalStart","openingBalance","replayed","sourceFileId","transactionCount"]) &&
    (typeof value.accountMask === "string" || value.accountMask === null) &&
    (isLedgerMoneyWire(value.closingBalance) || value.closingBalance === null) &&
    (typeof value.correctionCount === "number" && Number.isInteger(value.correctionCount) && value.correctionCount >= 0) &&
    value.currency === "NOK" &&
    (typeof value.documentSha256 === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.documentSha256)) &&
    (typeof value.duplicateCount === "number" && Number.isInteger(value.duplicateCount) && value.duplicateCount >= 0) &&
    (typeof value.ignoredCount === "number" && Number.isInteger(value.ignoredCount) && value.ignoredCount >= 0) &&
    typeof value.intervalEnd === "string" &&
    typeof value.intervalStart === "string" &&
    (isLedgerMoneyWire(value.openingBalance) || value.openingBalance === null) &&
    typeof value.replayed === "boolean" &&
    isUuid(value.sourceFileId) &&
    (typeof value.transactionCount === "number" && Number.isInteger(value.transactionCount) && value.transactionCount >= 1)
  );
}

function isBankFilePreviewWire(value: unknown): value is BankFilePreviewWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accountId","columnMapping","companyId","content","dataFormat","filename","incomeYear","sourceFileId"]) &&
    isUuid(value.accountId) &&
    (value.columnMapping === undefined || (isBankFileColumnMappingWire(value.columnMapping) || value.columnMapping === null)) &&
    isUuid(value.companyId) &&
    (typeof value.content === "string" && value.content.length >= 1 && value.content.length <= 5000000) &&
    isSupportedBankDataFormat(value.dataFormat) &&
    (typeof value.filename === "string" && value.filename.length >= 1 && value.filename.length <= 255) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isUuid(value.sourceFileId)
  );
}

function isBankStatementImportResultWire(value: unknown): value is BankStatementImportResultWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["duplicateCount","importedCount","replayed"]) &&
    (typeof value.duplicateCount === "number" && Number.isInteger(value.duplicateCount) && value.duplicateCount >= 0) &&
    (typeof value.importedCount === "number" && Number.isInteger(value.importedCount) && value.importedCount >= 0) &&
    typeof value.replayed === "boolean"
  );
}

function isBankStatementImportWire(value: unknown): value is BankStatementImportWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","dataFormat","incomeYear","statementText"]) &&
    isUuid(value.companyId) &&
    isSupportedBankDataFormat(value.dataFormat) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.statementText === "string" && value.statementText.length >= 1 && value.statementText.length <= 5000000)
  );
}

function isBankSuggestionAcceptancePageWire(value: unknown): value is BankSuggestionAcceptancePageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items","page"]) &&
    Array.isArray(value.items) && value.items.every((item) => isAcceptedBankSuggestionWire(item)) &&
    isBankingPageWire(value.page)
  );
}

function isBankSuggestionKind(value: unknown): value is BankSuggestionKind {
  return value === "BANK_FEE" || value === "SYSTEM_SUBSCRIPTION" || value === "DEPOSIT_INTEREST";
}

function isBankSuggestionWire(value: unknown): value is BankSuggestionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["kind","reason","ruleVersion"]) &&
    typeof value.kind === "string" &&
    typeof value.reason === "string" &&
    typeof value.ruleVersion === "string"
  );
}

function isBankSyncMode(value: unknown): value is BankSyncMode {
  return value === "INITIAL_BACKFILL" || value === "NIGHTLY" || value === "ON_DEMAND" || value === "ANNUAL_CLOSE" || value === "RECOVERY";
}

function isBankSyncResultWire(value: unknown): value is BankSyncResultWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["attemptId","duplicateCount","importedCount","pageCount","replayed","updatedCount"]) &&
    isUuid(value.attemptId) &&
    (typeof value.duplicateCount === "number" && Number.isInteger(value.duplicateCount) && value.duplicateCount >= 0) &&
    (typeof value.importedCount === "number" && Number.isInteger(value.importedCount) && value.importedCount >= 0) &&
    (typeof value.pageCount === "number" && Number.isInteger(value.pageCount) && value.pageCount >= 0) &&
    typeof value.replayed === "boolean" &&
    (typeof value.updatedCount === "number" && Number.isInteger(value.updatedCount) && value.updatedCount >= 0)
  );
}

function isBankSyncWire(value: unknown): value is BankSyncWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","connectorId","dateFrom","dateTo","incomeYear","mode"]) &&
    isUuid(value.companyId) &&
    (typeof value.connectorId === "string" && new RegExp("^[a-z0-9][a-z0-9-]{0,79}$", "u").test(value.connectorId)) &&
    typeof value.dateFrom === "string" &&
    typeof value.dateTo === "string" &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isBankSyncMode(value.mode)
  );
}

function isBankTransactionPageWire(value: unknown): value is BankTransactionPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["items","page"]) &&
    Array.isArray(value.items) && value.items.every((item) => isBankTransactionWire(item)) &&
    isBankingPageWire(value.page)
  );
}

function isBankTransactionWire(value: unknown): value is BankTransactionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amount","balance","companyId","createdAt","incomeYear","matchedActionReference","matchedEntryId","sourceHash","suggestion","text","transactionDate","transactionId","warningAccepted"]) &&
    isLedgerMoneyWire(value.amount) &&
    (isLedgerMoneyWire(value.balance) || value.balance === null) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.matchedActionReference === "string" || value.matchedActionReference === null) &&
    (isUuid(value.matchedEntryId) || value.matchedEntryId === null) &&
    (typeof value.sourceHash === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.sourceHash)) &&
    (isBankSuggestionWire(value.suggestion) || value.suggestion === null) &&
    typeof value.text === "string" &&
    typeof value.transactionDate === "string" &&
    isUuid(value.transactionId) &&
    typeof value.warningAccepted === "boolean"
  );
}

function isBankingPageWire(value: unknown): value is BankingPageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["hasMore","nextCursor"]) &&
    typeof value.hasMore === "boolean" &&
    (typeof value.nextCursor === "string" || value.nextCursor === null)
  );
}

function isSupportedBankDataFormat(value: unknown): value is SupportedBankDataFormat {
  return value === "CSV" || value === "CAMT053";
}

function isStartBankConnectionWire(value: unknown): value is StartBankConnectionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankKey","companyId","connectionId","connectorId","incomeYear","returnUrl"]) &&
    (typeof value.bankKey === "string" && value.bankKey.length >= 1 && value.bankKey.length <= 120) &&
    isUuid(value.companyId) &&
    isUuid(value.connectionId) &&
    (typeof value.connectorId === "string" && new RegExp("^[a-z0-9][a-z0-9-]{0,79}$", "u").test(value.connectorId)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.returnUrl === "string" && value.returnUrl.length <= 2048 && new RegExp("^https://", "u").test(value.returnUrl))
  );
}

function isAnnualCheckoutCommandWire(value: unknown): value is AnnualCheckoutCommandWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","consentVersion","incomeYear","offerVersion","purchaseAccepted","recurringConsent","termsDigest"]) &&
    isUuid(value.companyId) &&
    (typeof value.consentVersion === "string" && value.consentVersion.length >= 1 && value.consentVersion.length <= 100) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.offerVersion === "string" && value.offerVersion.length >= 1 && value.offerVersion.length <= 100) &&
    typeof value.purchaseAccepted === "boolean" &&
    typeof value.recurringConsent === "boolean" &&
    (typeof value.termsDigest === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.termsDigest))
  );
}

function isAnnualCheckoutObservationCommandWire(value: unknown): value is AnnualCheckoutObservationCommandWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","purchaseId"]) &&
    isUuid(value.companyId) &&
    isUuid(value.purchaseId)
  );
}

function isAnnualCheckoutWire(value: unknown): value is AnnualCheckoutWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["capturedMinor","checkoutUrl","companyId","incomeYear","offer","purchaseId","refundedMinor","status"]) &&
    (typeof value.capturedMinor === "number" && Number.isInteger(value.capturedMinor) && value.capturedMinor >= 0) &&
    (typeof value.checkoutUrl === "string" || value.checkoutUrl === null) &&
    isUuid(value.companyId) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    isAnnualBillingOfferWire(value.offer) &&
    isUuid(value.purchaseId) &&
    (typeof value.refundedMinor === "number" && Number.isInteger(value.refundedMinor) && value.refundedMinor >= 0) &&
    isAnnualPurchaseStatus(value.status)
  );
}

function isAnnualAgreementCleanupCommandWire(value: unknown): value is AnnualAgreementCleanupCommandWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","purchaseId"]) &&
    isUuid(value.companyId) &&
    isUuid(value.purchaseId)
  );
}

function isAnnualAgreementCleanupWire(value: unknown): value is AnnualAgreementCleanupWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","purchaseId","status"]) &&
    isUuid(value.companyId) &&
    isUuid(value.purchaseId) &&
    (value.status === "deferred" || value.status === "pending" || value.status === "unknown" || value.status === "confirmed")
  );
}

function isAnnualBillingOfferWire(value: unknown): value is AnnualBillingOfferWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","currency","exportThrough","grossMinor","incomeYear","netMinor","offerVersion","paidThrough","priceChangeNoticeBy","renewalDate","renewalReminderBy","termsDigest","termsText","vatBasisPoints","vatMinor"]) &&
    isUuid(value.companyId) &&
    value.currency === "NOK" &&
    typeof value.exportThrough === "string" &&
    (typeof value.grossMinor === "number" && Number.isInteger(value.grossMinor) && value.grossMinor > 0) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    (typeof value.netMinor === "number" && Number.isInteger(value.netMinor) && value.netMinor > 0) &&
    typeof value.offerVersion === "string" &&
    typeof value.paidThrough === "string" &&
    typeof value.priceChangeNoticeBy === "string" &&
    typeof value.renewalDate === "string" &&
    typeof value.renewalReminderBy === "string" &&
    typeof value.termsDigest === "string" &&
    typeof value.termsText === "string" &&
    typeof value.vatBasisPoints === "number" && Number.isInteger(value.vatBasisPoints) &&
    (typeof value.vatMinor === "number" && Number.isInteger(value.vatMinor) && value.vatMinor >= 0)
  );
}

function isAnnualPurchaseSummaryWire(value: unknown): value is AnnualPurchaseSummaryWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["acceptedAt","capturedAt","capturedMinor","companyId","currency","exportThrough","grossMinor","incomeYear","netMinor","offerVersion","paidThrough","purchaseId","recurringConsent","refundedMinor","renewalCanceledAt","renewalDate","status","termsDigest","termsText","vatBasisPoints","vatMinor"]) &&
    isDateTime(value.acceptedAt) &&
    (isDateTime(value.capturedAt) || value.capturedAt === null) &&
    (typeof value.capturedMinor === "number" && Number.isInteger(value.capturedMinor) && value.capturedMinor >= 0) &&
    isUuid(value.companyId) &&
    value.currency === "NOK" &&
    typeof value.exportThrough === "string" &&
    (typeof value.grossMinor === "number" && Number.isInteger(value.grossMinor) && value.grossMinor > 0) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    (typeof value.netMinor === "number" && Number.isInteger(value.netMinor) && value.netMinor > 0) &&
    typeof value.offerVersion === "string" &&
    typeof value.paidThrough === "string" &&
    isUuid(value.purchaseId) &&
    typeof value.recurringConsent === "boolean" &&
    (typeof value.refundedMinor === "number" && Number.isInteger(value.refundedMinor) && value.refundedMinor >= 0) &&
    (isDateTime(value.renewalCanceledAt) || value.renewalCanceledAt === null) &&
    typeof value.renewalDate === "string" &&
    isAnnualPurchaseStatus(value.status) &&
    typeof value.termsDigest === "string" &&
    typeof value.termsText === "string" &&
    typeof value.vatBasisPoints === "number" && Number.isInteger(value.vatBasisPoints) &&
    (typeof value.vatMinor === "number" && Number.isInteger(value.vatMinor) && value.vatMinor >= 0)
  );
}

function isAnnualPurchaseStatus(value: unknown): value is AnnualPurchaseStatus {
  return value === "pending" || value === "paid" || value === "failed" || value === "refunded";
}

function isAnnualBillingSnapshotWire(value: unknown): value is AnnualBillingSnapshotWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["nextPurchaseId","offer","purchases"]) &&
    (isUuid(value.nextPurchaseId) || value.nextPurchaseId === null) &&
    isAnnualBillingOfferWire(value.offer) &&
    Array.isArray(value.purchases) && value.purchases.every((item) => isAnnualPurchaseSummaryWire(item))
  );
}

function isAnnualRenewalCancellationCommandWire(value: unknown): value is AnnualRenewalCancellationCommandWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","purchaseId"]) &&
    isUuid(value.companyId) &&
    isUuid(value.purchaseId)
  );
}

function isAnnualRenewalCancellationWire(value: unknown): value is AnnualRenewalCancellationWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["cancellationId","companyId","effectiveAt","exportThrough","incomeYear","paidThrough","purchaseId","requestedAt"]) &&
    isUuid(value.cancellationId) &&
    isUuid(value.companyId) &&
    isDateTime(value.effectiveAt) &&
    typeof value.exportThrough === "string" &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.paidThrough === "string" &&
    isUuid(value.purchaseId) &&
    isDateTime(value.requestedAt)
  );
}

function isBillingAccountWire(value: unknown): value is BillingAccountWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","createdAt","filingPackageNok","filingPackagePaid","filingPackagePaymentReference","founderCohortNumber","monthlyNok","noChargeReason","pricingPlan","providerCustomerReference","refundCompleted","refundEligible","refundProviderReference","subscriptionActive","subscriptionProviderReference","supportedCase","updatedAt","updatedBy"]) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    typeof value.filingPackageNok === "number" && Number.isInteger(value.filingPackageNok) &&
    typeof value.filingPackagePaid === "boolean" &&
    (typeof value.filingPackagePaymentReference === "string" || value.filingPackagePaymentReference === null) &&
    (typeof value.founderCohortNumber === "number" && Number.isInteger(value.founderCohortNumber) || value.founderCohortNumber === null) &&
    typeof value.monthlyNok === "number" && Number.isInteger(value.monthlyNok) &&
    (typeof value.noChargeReason === "string" || value.noChargeReason === null) &&
    isBillingPlan(value.pricingPlan) &&
    (typeof value.providerCustomerReference === "string" || value.providerCustomerReference === null) &&
    typeof value.refundCompleted === "boolean" &&
    typeof value.refundEligible === "boolean" &&
    (typeof value.refundProviderReference === "string" || value.refundProviderReference === null) &&
    typeof value.subscriptionActive === "boolean" &&
    (typeof value.subscriptionProviderReference === "string" || value.subscriptionProviderReference === null) &&
    typeof value.supportedCase === "boolean" &&
    isDateTime(value.updatedAt) &&
    isUuid(value.updatedBy)
  );
}

function isBillingCompanyWire(value: unknown): value is BillingCompanyWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId"]) &&
    isUuid(value.companyId)
  );
}

function isBillingConfigureWire(value: unknown): value is BillingConfigureWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","founderCohortNumber","pricingPlan"]) &&
    isUuid(value.companyId) &&
    (value.founderCohortNumber === undefined || ((typeof value.founderCohortNumber === "number" && Number.isInteger(value.founderCohortNumber) && value.founderCohortNumber >= 1 && value.founderCohortNumber <= 100) || value.founderCohortNumber === null)) &&
    isBillingPlan(value.pricingPlan)
  );
}

function isBillingEntitlementDecisionWire(value: unknown): value is BillingEntitlementDecisionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["allowed","billingExempt","chargeAllowed","companyId","incomeYear","message","obligation","pilotEntitlementId","readinessAllowed","status"]) &&
    typeof value.allowed === "boolean" &&
    typeof value.billingExempt === "boolean" &&
    typeof value.chargeAllowed === "boolean" &&
    isUuid(value.companyId) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    typeof value.message === "string" &&
    isBillingObligation(value.obligation) &&
    (isUuid(value.pilotEntitlementId) || value.pilotEntitlementId === null) &&
    typeof value.readinessAllowed === "boolean" &&
    isBillingStatus(value.status)
  );
}

function isBillingFilingPackageWire(value: unknown): value is BillingFilingPackageWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","incomeYear","obligation"]) &&
    isUuid(value.companyId) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (value.obligation === undefined || isBillingObligation(value.obligation))
  );
}

function isBillingObligation(value: unknown): value is BillingObligation {
  return value === "aksjonaerregisteroppgaven" || value === "skattemelding" || value === "aarsregnskap";
}

function isBillingPaymentKind(value: unknown): value is BillingPaymentKind {
  return value === "subscription" || value === "subscription_cancellation" || value === "filing_package" || value === "refund";
}

function isBillingPaymentEventWire(value: unknown): value is BillingPaymentEventWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["amountNok","companyId","createdAt","createdBy","eventId","idempotencyKey","incomeYear","kind","provider","providerReference","replayed","status"]) &&
    typeof value.amountNok === "number" && Number.isInteger(value.amountNok) &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.createdBy) &&
    isUuid(value.eventId) &&
    typeof value.idempotencyKey === "string" &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) || value.incomeYear === null) &&
    isBillingPaymentKind(value.kind) &&
    typeof value.provider === "string" &&
    typeof value.providerReference === "string" &&
    typeof value.replayed === "boolean" &&
    isBillingPaymentStatus(value.status)
  );
}

function isBillingPaymentStatus(value: unknown): value is BillingPaymentStatus {
  return value === "created" || value === "succeeded" || value === "failed" || value === "refunded" || value === "canceled";
}

function isBillingPilotEntitlementCommandWire(value: unknown): value is BillingPilotEntitlementCommandWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["billingExempt","companyId","entitlementId","evidenceReference","expiresAt","incomeYear","startsAt","status","systemUserRequestId","userId"]) &&
    typeof value.billingExempt === "boolean" &&
    isUuid(value.companyId) &&
    (value.entitlementId === undefined || (isUuid(value.entitlementId) || value.entitlementId === null)) &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 1000) &&
    isDateTime(value.expiresAt) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isDateTime(value.startsAt) &&
    isProductionPilotStatus(value.status) &&
    isUuid(value.systemUserRequestId) &&
    isUuid(value.userId)
  );
}

function isBillingPilotEntitlementWire(value: unknown): value is BillingPilotEntitlementWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["approvedBy","billingExempt","caseProfile","companyId","createdAt","entitlementId","evidenceReference","expiresAt","incomeYear","obligation","startsAt","status","systemUserExternalReference","systemUserRequestId","updatedAt","userId"]) &&
    isUuid(value.approvedBy) &&
    typeof value.billingExempt === "boolean" &&
    typeof value.caseProfile === "string" &&
    isUuid(value.companyId) &&
    isDateTime(value.createdAt) &&
    isUuid(value.entitlementId) &&
    typeof value.evidenceReference === "string" &&
    isDateTime(value.expiresAt) &&
    typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) &&
    isBillingObligation(value.obligation) &&
    isDateTime(value.startsAt) &&
    isProductionPilotStatus(value.status) &&
    typeof value.systemUserExternalReference === "string" &&
    isUuid(value.systemUserRequestId) &&
    isDateTime(value.updatedAt) &&
    isUuid(value.userId)
  );
}

function isBillingPlan(value: unknown): value is BillingPlan {
  return value === "founder" || value === "standard";
}

function isBillingPricingWire(value: unknown): value is BillingPricingWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["filingPackageNok","monthlyNok","plan"]) &&
    typeof value.filingPackageNok === "number" && Number.isInteger(value.filingPackageNok) &&
    typeof value.monthlyNok === "number" && Number.isInteger(value.monthlyNok) &&
    isBillingPlan(value.plan)
  );
}

function isBillingSnapshotWire(value: unknown): value is BillingSnapshotWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accounts","paymentEvents","pilotEntitlements","pricing"]) &&
    Array.isArray(value.accounts) && value.accounts.every((item) => isBillingAccountWire(item)) &&
    Array.isArray(value.paymentEvents) && value.paymentEvents.every((item) => isBillingPaymentEventWire(item)) &&
    Array.isArray(value.pilotEntitlements) && value.pilotEntitlements.every((item) => isBillingPilotEntitlementWire(item)) &&
    Array.isArray(value.pricing) && value.pricing.every((item) => isBillingPricingWire(item))
  );
}

function isBillingStatus(value: unknown): value is BillingStatus {
  return value === "annual_billing_unavailable" || value === "active" || value === "subscription_required" || value === "filing_package_required" || value === "ready_for_production_filing" || value === "unsupported_case" || value === "refund_eligible" || value === "pilot_entitlement_active";
}

function isBillingUnsupportedWire(value: unknown): value is BillingUnsupportedWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","reason"]) &&
    isUuid(value.companyId) &&
    (typeof value.reason === "string" && value.reason.length >= 1 && value.reason.length <= 500)
  );
}

function isProductionPilotStatus(value: unknown): value is ProductionPilotStatus {
  return value === "pending" || value === "active" || value === "suspended" || value === "completed" || value === "revoked";
}

function isMarketingFunnelReportResponse(value: unknown): value is MarketingFunnelReportResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["counts","medianSeconds","rates","repeatedSignals","supportBySurface","windowEnd","windowStart"]) &&
    isRecord(value.counts) && Object.values(value.counts).every((item) => typeof item === "number" && Number.isInteger(item)) &&
    isRecord(value.medianSeconds) && Object.values(value.medianSeconds).every((item) => (typeof item === "number" && Number.isFinite(item) || typeof item === "number" && Number.isInteger(item) || item === null)) &&
    isRecord(value.rates) && Object.values(value.rates).every((item) => (typeof item === "number" && Number.isFinite(item) || typeof item === "number" && Number.isInteger(item) || item === null)) &&
    Array.isArray(value.repeatedSignals) && value.repeatedSignals.every((item) => isMarketingRepeatedSignalWire(item)) &&
    isRecord(value.supportBySurface) && Object.values(value.supportBySurface).every((item) => typeof item === "number" && Number.isInteger(item)) &&
    isDateTime(value.windowEnd) &&
    isDateTime(value.windowStart)
  );
}

function isMarketingMeasurementEventResponse(value: unknown): value is MarketingMeasurementEventResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["accepted","duplicate"]) &&
    value.accepted === true &&
    typeof value.duplicate === "boolean"
  );
}

function isMarketingMeasurementEventWire(value: unknown): value is MarketingMeasurementEventWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["anonymousSessionHash","campaignSource","clientEventId","consentVersion","event","firstLayerNoticeSha256","firstLayerNoticeVersion","privacyNoticeSha256","privacyNoticeVersion","reason","releaseSha256","surface"]) &&
    (typeof value.anonymousSessionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.anonymousSessionHash)) &&
    (value.campaignSource === "direct" || value.campaignSource === "organic" || value.campaignSource === "community" || value.campaignSource === "partner" || value.campaignSource === "approved_campaign" || value.campaignSource === "unknown") &&
    isUuid(value.clientEventId) &&
    value.consentVersion === "marketing-analytics-v1" &&
    (value.event === "home_view" || value.event === "eligibility_start" || value.event === "provisional_supported" || value.event === "provisional_clarify" || value.event === "provisional_blocked" || value.event === "definitive_eligible" || value.event === "definitive_blocked" || value.event === "signup_start" || value.event === "unsupported_exit") &&
    (typeof value.firstLayerNoticeSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.firstLayerNoticeSha256)) &&
    (typeof value.firstLayerNoticeVersion === "string" && new RegExp("^[a-z0-9][a-z0-9._-]{0,63}$", "u").test(value.firstLayerNoticeVersion)) &&
    (typeof value.privacyNoticeSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.privacyNoticeSha256)) &&
    (typeof value.privacyNoticeVersion === "string" && new RegExp("^[a-z0-9][a-z0-9._-]{0,63}$", "u").test(value.privacyNoticeVersion)) &&
    ((value.reason === "unknown_material_facts" || value.reason === "unsupported_company" || value.reason === "unsupported_activity" || value.reason === "missing_required_facts" || value.reason === "new_unsupported_condition") || value.reason === null) &&
    (typeof value.releaseSha256 === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.releaseSha256)) &&
    (value.surface === "homepage" || value.surface === "eligibility" || value.surface === "signup")
  );
}

function isMarketingMeasurementWithdrawalRequest(value: unknown): value is MarketingMeasurementWithdrawalRequest {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["anonymousSessionHash"]) &&
    (typeof value.anonymousSessionHash === "string" && new RegExp("^[0-9a-f]{64}$", "u").test(value.anonymousSessionHash))
  );
}

function isMarketingMeasurementWithdrawalResponse(value: unknown): value is MarketingMeasurementWithdrawalResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["deletedEventCount"]) &&
    (typeof value.deletedEventCount === "number" && Number.isInteger(value.deletedEventCount) && value.deletedEventCount >= 0)
  );
}

function isMarketingRepeatedSignalWire(value: unknown): value is MarketingRepeatedSignalWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["count","event","reason","surface"]) &&
    (typeof value.count === "number" && Number.isInteger(value.count) && value.count >= 5) &&
    (value.event === "home_view" || value.event === "eligibility_start" || value.event === "provisional_supported" || value.event === "provisional_clarify" || value.event === "provisional_blocked" || value.event === "definitive_eligible" || value.event === "definitive_blocked" || value.event === "signup_start" || value.event === "unsupported_exit") &&
    (value.reason === "unknown_material_facts" || value.reason === "unsupported_company" || value.reason === "unsupported_activity" || value.reason === "missing_required_facts" || value.reason === "new_unsupported_condition") &&
    (value.surface === "homepage" || value.surface === "eligibility" || value.surface === "signup")
  );
}

function isProblemDetails(value: unknown): value is ProblemDetails {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["code","detail","instance","requestId","status","title","type"]) &&
    typeof value.code === "string" &&
    typeof value.detail === "string" &&
    typeof value.instance === "string" &&
    typeof value.requestId === "string" &&
    typeof value.status === "number" && Number.isInteger(value.status) &&
    typeof value.title === "string" &&
    typeof value.type === "string"
  );
}

export class TalliApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails | undefined;

  constructor(
    status: number,
    problem: ProblemDetails | undefined,
  ) {
    super(problem?.code ?? `HTTP_${status}`);
    this.name = "TalliApiError";
    this.status = status;
    this.problem = problem;
  }
}

export interface TalliApiClientOptions {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
  headers?: HeadersInit;
}

export interface TalliRequestOptions {
  signal?: AbortSignal;
  headers?: HeadersInit;
  requestId?: string;
}

export interface TalliMutationOptions extends TalliRequestOptions {
  idempotencyKey: string;
}

export interface LedgerListRequest extends TalliRequestOptions {
  companyIds: readonly string[];
  cursor?: string;
  limit?: number;
}

export interface LedgerEntryListRequest extends LedgerListRequest {
  includeSource?: boolean;
}

export interface InvestmentsListRequest extends TalliRequestOptions {
  companyIds: readonly string[];
  cursor?: string;
  limit?: number;
}

export interface DocumentsListRequest extends TalliRequestOptions {
  companyId: string;
}

export interface DocumentsBackupProjectionRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
}

export interface CorporateGovernanceListRequest extends TalliRequestOptions {
  companyIds: readonly string[];
}

export interface CorporateGovernanceDecisionFactsRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
  decisionKind: CorporateDecisionKind;
}

export interface CorporateGovernanceReadinessRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
  decisionKind: CorporateDecisionKind;
}

export interface LedgerOpeningSnapshotListRequest extends TalliRequestOptions {
  companyIds: readonly string[];
  cursor?: string;
  limit?: number;
}

export interface LedgerReconstructionRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
}

export interface BankingListRequest extends TalliRequestOptions {
  companyIds: readonly string[];
  cursor?: string;
  limit?: number;
}

export interface BankingConnectionCallbackRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
  code?: string;
  state?: string;
  resourceId?: string;
  result?: string;
}

export interface BankingConnectionListRequest extends TalliRequestOptions {
  companyId: string;
}

export interface AnnualBillingSnapshotRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
  beforePurchaseId?: string;
}

export interface BillingSnapshotRequest extends TalliRequestOptions {
  companyIds: readonly string[];
}

export interface BillingEntitlementRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
  obligation: BillingObligation;
  caseProfile?: string;
}

export interface CompanyAccessContextRequest extends TalliRequestOptions {
  companyId?: string;
}

export interface MarketingMeasurementReportRequest extends TalliRequestOptions {
  windowDays?: number;
}

export function createTalliApiClient(options: TalliApiClientOptions) {
  const fetchImplementation = options.fetch ?? globalThis.fetch;
  const baseUrl = options.baseUrl.replace(/\/$/, "");

  async function executeJson<T>(
    url: string,
    method: string,
    request: TalliRequestOptions,
    body: unknown,
    guard: (value: unknown) => value is T,
  ): Promise<T> {
    const idempotencyKey = "idempotencyKey" in request
      && typeof request.idempotencyKey === "string"
      ? request.idempotencyKey
      : undefined;
    const response = await fetchImplementation(url, {
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      headers: {
        Accept: "application/json, application/problem+json",
        ...(body === undefined ? {} : { ["Content-Type"]: "application/json" }),
        ...options.headers,
        ...request.headers,
        ...(idempotencyKey === undefined
          ? {}
          : { ["Idempotency-Key"]: idempotencyKey }),
        ...(request.requestId === undefined
          ? {}
          : { ["X-Request-ID"]: request.requestId }),
      },
      method,
      signal: request.signal,
    });
    if (!response.ok) {
      const contentType = response.headers.get("content-type") ?? "";
      const candidate = contentType.includes("application/problem+json")
        ? await response.json().catch(() => undefined)
        : undefined;
      throw new TalliApiError(
        response.status,
        isProblemDetails(candidate) ? candidate : undefined,
      );
    }
    const candidate: unknown = await response.json().catch(() => {
      throw new TalliApiError(502, undefined);
    });
    if (!guard(candidate)) throw new TalliApiError(502, undefined);
    return candidate;
  }

  async function executeEmpty(
    url: string,
    method: string,
    request: TalliMutationOptions,
    body: unknown,
  ): Promise<void> {
    const response = await fetchImplementation(url, {
      body: JSON.stringify(body),
      cache: "no-store",
      headers: {
        Accept: "application/json, application/problem+json",
        ["Content-Type"]: "application/json",
        ...options.headers,
        ...request.headers,
        ["Idempotency-Key"]: request.idempotencyKey,
        ...(request.requestId === undefined
          ? {}
          : { ["X-Request-ID"]: request.requestId }),
      },
      method,
      signal: request.signal,
    });
    if (!response.ok) {
      const contentType = response.headers.get("content-type") ?? "";
      const candidate = contentType.includes("application/problem+json")
        ? await response.json().catch(() => undefined)
        : undefined;
      throw new TalliApiError(
        response.status,
        isProblemDetails(candidate) ? candidate : undefined,
      );
    }
  }

  async function executeLedgerWriter(
    path: string,
    body: { companyId: string; incomeYear: number },
    request: TalliMutationOptions,
    expectedKind: LedgerEntryKind | null,
  ): Promise<LedgerWriterResultWire> {
    const result = await executeJson(
      `${baseUrl}${path}`,
      "POST",
      request,
      body,
      isLedgerWriterResultWire,
    );
    if (expectedKind === null) {
      if (result.postedEntry !== null) throw new TalliApiError(502, undefined);
      return result;
    }
    if (
      result.postedEntry === null
      || result.postedEntry.companyId !== body.companyId
      || result.postedEntry.incomeYear !== body.incomeYear
      || result.postedEntry.entryKind !== expectedKind
      || result.postedEntry.replayed !== result.replayed
    ) {
      throw new TalliApiError(502, undefined);
    }
    return result;
  }

  return {
    async systemBoundaryGetTracerStatus(
      request: TalliRequestOptions = {},
    ): Promise<SystemBoundaryStatus> {
      const response = await fetchImplementation(`${baseUrl}/api/v1/system-boundary/tracer`, {
        cache: "no-store",
        headers: {
          Accept: "application/json, application/problem+json",
          ...options.headers,
          ...request.headers,
          ...(request.requestId === undefined
            ? {}
            : { ["X-Request-ID"]: request.requestId }),
        },
        method: "GET",
        signal: request.signal,
      });

      if (!response.ok) {
        const contentType = response.headers.get("content-type") ?? "";
        const candidate = contentType.includes("application/problem+json")
          ? await response.json().catch(() => undefined)
          : undefined;
        const problem = isProblemDetails(candidate) ? candidate : undefined;
        throw new TalliApiError(response.status, problem);
      }

      const candidate: unknown = await response.json();
      if (!isSystemBoundaryStatus(candidate)) {
        throw new TalliApiError(502, undefined);
      }
      return candidate;
    },

    async companyAccessGetSelectedContext(
      request: CompanyAccessContextRequest = {},
    ): Promise<CompanyContextResponse> {
      const query = new URLSearchParams();
      if (request.companyId !== undefined) query.set("company_id", request.companyId);
      const suffix = query.size ? `?${query}` : "";
      const response = await fetchImplementation(`${baseUrl}/api/v1/company-access/context${suffix}`, {
        cache: "no-store",
        headers: {
          Accept: "application/json, application/problem+json",
          ...options.headers,
          ...request.headers,
          ...(request.requestId === undefined
            ? {}
            : { ["X-Request-ID"]: request.requestId }),
        },
        method: "GET",
        signal: request.signal,
      });

      if (!response.ok) {
        const contentType = response.headers.get("content-type") ?? "";
        const candidate = contentType.includes("application/problem+json")
          ? await response.json().catch(() => undefined)
          : undefined;
        const problem = isProblemDetails(candidate) ? candidate : undefined;
        throw new TalliApiError(response.status, problem);
      }

      const candidate: unknown = await response.json();
      if (!isCompanyContextResponse(candidate)) {
        throw new TalliApiError(502, undefined);
      }
      return candidate;
    },

    async companyAccessOnboardCompany(
      body: CompanyOnboardingRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyOnboardingResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/onboarding`,
        "POST",
        request,
        body,
        isCompanyOnboardingResponse,
      );
    },

    async companyAccessEligibilityPrecheck(
      body: EligibilityPrecheckRequest,
      request: TalliRequestOptions = {},
    ): Promise<EligibilityDecisionResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/eligibility/precheck`,
        "POST",
        request,
        body,
        isEligibilityDecisionResponse,
      );
    },

    async companyAccessEligibilityDefinitive(
      body: EligibilityDefinitiveRequest,
      request: TalliRequestOptions = {},
    ): Promise<EligibilityDecisionResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/eligibility/definitive`,
        "POST",
        request,
        body,
        isEligibilityDecisionResponse,
      );
    },

    async companyAccessAdmitCompanyYear(
      body: CompanyYearAdmissionRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyYearAdmissionResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/company-year-admissions`,
        "POST",
        request,
        body,
        isCompanyYearAdmissionResponse,
      );
    },

    async companyAccessRecheckCompanyYearEligibility(
      companyYearAdmissionId: string,
      body: CompanyYearEligibilityRecheckRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyYearEligibilityStateResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/company-year-admissions/${encodeURIComponent(companyYearAdmissionId)}/eligibility-rechecks`,
        "POST",
        request,
        body,
        isCompanyYearEligibilityStateResponse,
      );
    },

    async companyAccessReacceptAgreement(
      body: CompanyAgreementAcceptanceRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyAgreementAcceptanceResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/agreements/reaccept`,
        "POST",
        request,
        body,
        isCompanyAgreementAcceptanceResponse,
      );
    },

    async companyAccessGetCompanyRecord(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyAccessRecordResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/companies/${encodeURIComponent(companyId)}`,
        "GET",
        request,
        undefined,
        isCompanyAccessRecordResponse,
      );
    },

    async companyAccessGetOperatorContext(
      request: TalliRequestOptions = {},
    ): Promise<OperatorContextResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/operator-context`,
        "GET",
        request,
        undefined,
        isOperatorContextResponse,
      );
    },

    async companyAccessSearchOperatorCompanies(
      query: string,
      request: TalliRequestOptions = {},
    ): Promise<OperatorCompanySearchResponse> {
      const search = new URLSearchParams({ query });
      return executeJson(
        `${baseUrl}/api/v1/company-access/operator-companies?${search}`,
        "GET",
        request,
        undefined,
        isOperatorCompanySearchResponse,
      );
    },

    async companyAccessGrantSupportAccess(
      body: GrantSupportAccessRequest,
      request: TalliRequestOptions = {},
    ): Promise<SupportAccessGrantResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/operator-support-grants`,
        "POST",
        request,
        body,
        isSupportAccessGrantResponse,
      );
    },

    async companyAccessRevokeSupportAccess(
      caseId: string,
      body: RevokeSupportAccessRequest,
      request: TalliRequestOptions = {},
    ): Promise<SupportAccessGrantResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/operator-support-grants/${encodeURIComponent(caseId)}/revocations`,
        "POST",
        request,
        body,
        isSupportAccessGrantResponse,
      );
    },

    async companyAccessOpenSupportCase(
      caseId: string,
      body: OpenSupportCaseRequest,
      request: TalliRequestOptions = {},
    ): Promise<SupportCaseOpeningResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/operator-support-cases/${encodeURIComponent(caseId)}/openings`,
        "POST",
        request,
        body,
        isSupportCaseOpeningResponse,
      );
    },

    async companyAccessReadSupportCase(
      caseId: string,
      request: TalliRequestOptions = {},
    ): Promise<SupportCaseSnapshotResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/operator-support-cases/${encodeURIComponent(caseId)}`,
        "GET",
        request,
        undefined,
        isSupportCaseSnapshotResponse,
      );
    },

    async companyAccessListInvitations(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationListResponse> {
      const query = new URLSearchParams({ company_id: companyId });
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations?${query}`,
        "GET",
        request,
        undefined,
        isCompanyInvitationListResponse,
      );
    },

    async companyAccessCreateInvitation(
      body: CreateCompanyInvitationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations`,
        "POST",
        request,
        body,
        isCompanyInvitationResponse,
      );
    },

    async companyAccessLookupInvitation(
      body: InvitationTokenRequest,
      request: TalliRequestOptions = {},
    ): Promise<InvitationLookup> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations/lookup`,
        "POST",
        request,
        body,
        isInvitationLookup,
      );
    },

    async companyAccessAcceptInvitation(
      body: AcceptCompanyInvitationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyMembershipResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations/accept`,
        "POST",
        request,
        body,
        isCompanyMembershipResponse,
      );
    },

    async companyAccessRevokeInvitation(
      invitationId: string,
      body: CompanyInvitationCommandRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations/${encodeURIComponent(invitationId)}/revoke`,
        "POST",
        request,
        body,
        isCompanyInvitationResponse,
      );
    },

    async companyAccessResendInvitation(
      invitationId: string,
      body: CompanyInvitationCommandRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations/${encodeURIComponent(invitationId)}/resend`,
        "POST",
        request,
        body,
        isCompanyInvitationResponse,
      );
    },

    async companyAccessListPendingInvitationSideEffects(
      request: TalliRequestOptions = {},
    ): Promise<InvitationSideEffectContinuationList> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitation-side-effects/pending`,
        "GET",
        request,
        undefined,
        isInvitationSideEffectContinuationList,
      );
    },

    async companyAccessCompleteInvitationSideEffect(
      operationId: string,
      request: TalliRequestOptions = {},
    ): Promise<InvitationSideEffectCompletion> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitation-side-effects/${encodeURIComponent(operationId)}/complete`,
        "POST",
        request,
        undefined,
        isInvitationSideEffectCompletion,
      );
    },

    async companyAccessListMemberships(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyMembershipListResponse> {
      const query = new URLSearchParams({ company_id: companyId });
      return executeJson(
        `${baseUrl}/api/v1/company-access/memberships?${query}`,
        "GET",
        request,
        undefined,
        isCompanyMembershipListResponse,
      );
    },

    async companyAccessAdministerMembership(
      userId: string,
      body: AdministerCompanyMembershipRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyMembershipResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/memberships/${encodeURIComponent(userId)}`,
        "PATCH",
        request,
        body,
        isCompanyMembershipResponse,
      );
    },

    async companyAccessListCancellations(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationListResponse> {
      const query = new URLSearchParams({ company_id: companyId });
      return executeJson(
        `${baseUrl}/api/v1/company-access/cancellations?${query}`,
        "GET",
        request,
        undefined,
        isCompanyCancellationListResponse,
      );
    },

    async companyAccessRequestCancellation(
      body: RequestCompanyCancellationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/cancellations`,
        "POST",
        request,
        body,
        isCompanyCancellationResponse,
      );
    },

    async companyAccessReviewDeletion(
      cancellationId: string,
      supportCaseId: string,
      body: ReviewCompanyDeletionRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyDeletionReviewResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/cancellations/${encodeURIComponent(cancellationId)}/reviews`,
        "POST",
        {
          ...request,
          headers: { ...request.headers, "X-Support-Case-ID": supportCaseId },
        },
        body,
        isCompanyDeletionReviewResponse,
      );
    },

    async companyAccessResumeCancellation(
      cancellationId: string,
      body: ResumeCompanyCancellationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/cancellations/${encodeURIComponent(cancellationId)}/resume`,
        "POST",
        request,
        body,
        isCompanyCancellationResponse,
      );
    },

    async companyAccessFinalizeDeletion(
      cancellationId: string,
      body: FinalizeCompanyDeletionRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/cancellations/${encodeURIComponent(cancellationId)}/finalize`,
        "POST",
        request,
        body,
        isCompanyCancellationResponse,
      );
    },

    async ledgerListEntries(
      request: LedgerEntryListRequest,
    ): Promise<LedgerEntryPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      if (request.includeSource !== undefined) query.set("includeSource", String(request.includeSource));
      return executeJson(
        `${baseUrl}/api/v1/ledger/entries?${query}`,
        "GET",
        request,
        undefined,
        isLedgerEntryPageWire,
      );
    },

    async documentsList(
      request: DocumentsListRequest,
    ): Promise<DocumentListWire> {
      const query = new URLSearchParams({ companyId: request.companyId });
      return executeJson(
        `${baseUrl}/api/v1/documents?${query}`,
        "GET",
        request,
        undefined,
        isDocumentListWire,
      );
    },

    async documentsBackupProjection(
      request: DocumentsBackupProjectionRequest,
    ): Promise<DocumentBackupProjectionWire> {
      const query = new URLSearchParams({
        company_id: request.companyId,
        income_year: String(request.incomeYear),
      });
      return executeJson(
        `${baseUrl}/api/v1/documents/backup-projection?${query}`,
        "GET",
        request,
        undefined,
        isDocumentBackupProjectionWire,
      );
    },

    async documentsBeginUpload(
      body: DocumentBeginUploadWire,
      request: TalliMutationOptions,
    ): Promise<DocumentUploadTransferWire> {
      return executeJson(
        `${baseUrl}/api/v1/documents/uploads`,
        "POST",
        request,
        body,
        isDocumentUploadTransferWire,
      );
    },

    async documentsFinalizeUpload(
      documentId: string,
      request: TalliMutationOptions,
    ): Promise<DocumentWire> {
      return executeJson(
        `${baseUrl}/api/v1/documents/${encodeURIComponent(documentId)}/finalize`,
        "POST",
        request,
        undefined,
        isDocumentWire,
      );
    },

    async documentsRemove(
      documentId: string,
      body: DocumentRemovalRequestWire,
      request: TalliMutationOptions,
    ): Promise<DocumentWire> {
      return executeJson(
        `${baseUrl}/api/v1/documents/${encodeURIComponent(documentId)}/remove`,
        "POST",
        request,
        body,
        isDocumentWire,
      );
    },

    async documentsCreateTransfer(
      documentId: string,
      body: DocumentTransferRequestWire,
      request: TalliMutationOptions,
    ): Promise<DocumentTransferWire> {
      return executeJson(
        `${baseUrl}/api/v1/documents/${encodeURIComponent(documentId)}/transfers`,
        "POST",
        request,
        body,
        isDocumentTransferWire,
      );
    },

    async corporateGovernanceListDecisionLifecycle(
      request: CorporateGovernanceListRequest,
    ): Promise<CorporateLifecycleSnapshotWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/decisions?${query}`,
        "GET",
        request,
        undefined,
        isCorporateLifecycleSnapshotWire,
      );
    },

    async corporateGovernanceDeriveDecisionFacts(
      request: CorporateGovernanceDecisionFactsRequest,
    ): Promise<CorporateDecisionFactsWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
        decisionKind: request.decisionKind,
      });
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/decision-facts?${query}`,
        "GET",
        request,
        undefined,
        isCorporateDecisionFactsWire,
      );
    },

    async corporateGovernanceReadDecisionReadiness(
      request: CorporateGovernanceReadinessRequest,
    ): Promise<CorporateDocumentReadinessWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
        decisionKind: request.decisionKind,
      });
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/readiness?${query}`,
        "GET",
        request,
        undefined,
        isCorporateDocumentReadinessWire,
      );
    },

    async corporateGovernanceReadDecisionLifecycle(
      decisionId: string,
      request: TalliRequestOptions = {},
    ): Promise<CorporateLifecycleSnapshotWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/decisions/${encodeURIComponent(decisionId)}`,
        "GET",
        request,
        undefined,
        isCorporateLifecycleSnapshotWire,
      );
    },

    async corporateGovernanceProposeOwnerDividend(
      body: OwnerDividendProposalWire,
      request: TalliMutationOptions,
    ): Promise<ProposedOwnerDividendWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/owner-dividends/proposals`,
        "POST",
        request,
        body,
        isProposedOwnerDividendWire,
      );
    },

    async corporateGovernanceProposeAnnualClose(
      body: AnnualCloseProposalWire,
      request: TalliMutationOptions,
    ): Promise<ProposedAnnualCloseWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/annual-closes/proposals`,
        "POST",
        request,
        body,
        isProposedAnnualCloseWire,
      );
    },

    async corporateGovernanceRegisterAnnualCloseDocuments(
      decisionId: string,
      body: OwnerDividendDocumentsWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCloseLifecycleWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/annual-closes/${encodeURIComponent(decisionId)}/documents`,
        "POST",
        request,
        body,
        isAnnualCloseLifecycleWire,
      );
    },

    async corporateGovernanceApproveAnnualClose(
      decisionId: string,
      body: OwnerDividendApprovalWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCloseLifecycleWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/annual-closes/${encodeURIComponent(decisionId)}/approvals`,
        "POST",
        request,
        body,
        isAnnualCloseLifecycleWire,
      );
    },

    async corporateGovernanceRecordAnnualCloseEvent(
      decisionId: string,
      body: AnnualCloseEventWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCloseLifecycleWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/annual-closes/${encodeURIComponent(decisionId)}/events`,
        "POST",
        request,
        body,
        isAnnualCloseLifecycleWire,
      );
    },

    async corporateGovernanceFinalizeAnnualClose(
      decisionId: string,
      body: AnnualCloseFinalizationWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCloseLifecycleWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/annual-closes/${encodeURIComponent(decisionId)}/finalizations`,
        "POST",
        request,
        body,
        isAnnualCloseLifecycleWire,
      );
    },

    async corporateGovernanceAttestAnnualCloseSignedArtifact(
      decisionId: string,
      body: AnnualCloseSignedArtifactWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCloseLifecycleWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/annual-closes/${encodeURIComponent(decisionId)}/signed-artifacts`,
        "POST",
        request,
        body,
        isAnnualCloseLifecycleWire,
      );
    },

    async corporateGovernanceRecordShareholderLoan(
      body: ShareholderLoanWire,
      request: TalliMutationOptions,
    ): Promise<RecordedShareholderLoanWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/shareholder-loans`,
        "POST",
        request,
        body,
        isRecordedShareholderLoanWire,
      );
    },

    async corporateGovernanceListSupportedEvents(
      request: CorporateGovernanceListRequest,
    ): Promise<RecordedSupportedCorporateEventWire[]> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/supported-events?${query}`,
        "GET",
        request,
        undefined,
        (value): value is RecordedSupportedCorporateEventWire[] =>
          Array.isArray(value) && value.every(isRecordedSupportedCorporateEventWire),
      );
    },

    async corporateGovernanceRecordSupportedEvent(
      body: SupportedCorporateEventWire,
      request: TalliMutationOptions,
    ): Promise<RecordedSupportedCorporateEventWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/supported-events`,
        "POST",
        request,
        body,
        isRecordedSupportedCorporateEventWire,
      );
    },

    async corporateGovernanceReverseSupportedEvent(
      eventId: string,
      body: ReverseSupportedCorporateEventWire,
      request: TalliMutationOptions,
    ): Promise<ReversedSupportedCorporateEventWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/supported-events/${encodeURIComponent(eventId)}/reversal`,
        "POST",
        request,
        body,
        isReversedSupportedCorporateEventWire,
      );
    },

    async corporateGovernanceRegisterOwnerDividendDocuments(
      decisionId: string,
      body: OwnerDividendDocumentsWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/owner-dividends/${encodeURIComponent(decisionId)}/documents`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async corporateGovernanceApproveOwnerDividend(
      decisionId: string,
      body: OwnerDividendApprovalWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/owner-dividends/${encodeURIComponent(decisionId)}/approvals`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async corporateGovernanceRecordOwnerDividendEvent(
      decisionId: string,
      body: OwnerDividendEventWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/owner-dividends/${encodeURIComponent(decisionId)}/events`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async corporateGovernanceAttestOwnerDividendSignedArtifact(
      decisionId: string,
      body: OwnerDividendSignedArtifactWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/owner-dividends/${encodeURIComponent(decisionId)}/signed-artifacts`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async corporateGovernanceFinalizeOwnerDividend(
      decisionId: string,
      body: OwnerDividendFinalizationWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/owner-dividends/${encodeURIComponent(decisionId)}/finalizations`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async corporateGovernanceRecordOwnerDividendPayment(
      decisionId: string,
      body: OwnerDividendPaymentWire,
      request: TalliMutationOptions,
    ): Promise<OwnerDividendLifecycleWire> {
      return executeJson(
        `${baseUrl}/api/v1/corporate-governance/owner-dividends/${encodeURIComponent(decisionId)}/payments`,
        "POST",
        request,
        body,
        isOwnerDividendLifecycleWire,
      );
    },

    async investmentsRecognizeSharePurchase(
      body: InvestmentsRecognizeSharePurchaseWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsEconomicEventResultWire> {
      const result = await executeJson(
        `${baseUrl}/api/v1/investments/share-purchase-recognitions`,
        "POST",
        request,
        body,
        isInvestmentsEconomicEventResultWire,
      );
      if (result.eventId !== body.eventId) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsRecognizeShareSale(
      body: InvestmentsRecognizeShareSaleWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsEconomicEventResultWire> {
      const result = await executeJson(
        `${baseUrl}/api/v1/investments/share-sale-recognitions`,
        "POST",
        request,
        body,
        isInvestmentsEconomicEventResultWire,
      );
      if (result.eventId !== body.eventId || result.positionId !== body.positionId) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsRecognizeReceivedDividend(
      body: InvestmentsRecognizeReceivedDividendWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsEconomicEventResultWire> {
      const result = await executeJson(
        `${baseUrl}/api/v1/investments/received-dividend-recognitions`,
        "POST",
        request,
        body,
        isInvestmentsEconomicEventResultWire,
      );
      if (result.eventId !== body.eventId || result.positionId !== body.positionId) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsRecognizeReceivedFundDistribution(
      body: InvestmentsRecognizeReceivedFundDistributionWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsEconomicEventResultWire> {
      const result = await executeJson(
        `${baseUrl}/api/v1/investments/received-fund-distribution-recognitions`,
        "POST",
        request,
        body,
        isInvestmentsEconomicEventResultWire,
      );
      if (result.eventId !== body.eventId || result.positionId !== body.positionId) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsSettleCash(
      body: InvestmentsSettleCashWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsCashSettlementResultWire> {
      const result = await executeJson(
        `${baseUrl}/api/v1/investments/cash-settlements`,
        "POST",
        request,
        body,
        isInvestmentsCashSettlementResultWire,
      );
      if (result.settlementId !== body.settlementId || result.eventId !== body.eventId) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsRecordYearEndMeasurement(
      body: InvestmentsYearEndMeasurementWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsYearEndMeasurementResultWire> {
      const result = await executeJson(
        `${baseUrl}/api/v1/investments/year-end-measurements`,
        "POST",
        request,
        body,
        isInvestmentsYearEndMeasurementResultWire,
      );
      if (
        result.measurementId !== body.measurementId ||
        result.positionId !== body.positionId
      ) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsCorrectInvestment(
      body: InvestmentsCorrectionWire,
      request: TalliMutationOptions,
    ): Promise<InvestmentsCorrectionResultWire> {
      const result = await executeJson(
        `${baseUrl}/api/v1/investments/corrections`,
        "POST",
        request,
        body,
        isInvestmentsCorrectionResultWire,
      );
      const replacementRecordId = body.replacement.replacementKind === "cash_settlement"
        ? body.replacement.settlementId
        : body.replacement.eventId;
      if (
        result.correctionId !== body.correctionId ||
        result.targetKind !== body.targetKind ||
        result.originalRecordId !== body.originalRecordId ||
        result.replacementRecordId !== replacementRecordId
      ) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async investmentsListPositions(
      request: InvestmentsListRequest,
    ): Promise<InvestmentPositionPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        `${baseUrl}/api/v1/investments/positions?${query}`,
        "GET",
        request,
        undefined,
        isInvestmentPositionPageWire,
      );
    },

    async investmentsListCorrections(
      request: InvestmentsListRequest,
    ): Promise<InvestmentCorrectionPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        `${baseUrl}/api/v1/investments/corrections?${query}`,
        "GET",
        request,
        undefined,
        isInvestmentCorrectionPageWire,
      );
    },

    async investmentsListActivity(
      request: InvestmentsListRequest,
    ): Promise<InvestmentActivityPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        `${baseUrl}/api/v1/investments/activity?${query}`,
        "GET",
        request,
        undefined,
        isInvestmentActivityPageWire,
      );
    },

    async investmentsListEconomicEvents(
      request: InvestmentsListRequest,
    ): Promise<InvestmentLifecycleEventPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        `${baseUrl}/api/v1/investments/economic-events?${query}`,
        "GET",
        request,
        undefined,
        isInvestmentLifecycleEventPageWire,
      );
    },

    async investmentsListAcquisitionLots(
      request: InvestmentsListRequest,
    ): Promise<AcquisitionLotPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        `${baseUrl}/api/v1/investments/acquisition-lots?${query}`,
        "GET",
        request,
        undefined,
        isAcquisitionLotPageWire,
      );
    },

    async investmentsListShareSaleAllocations(
      request: InvestmentsListRequest,
    ): Promise<ShareSaleAllocationPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        `${baseUrl}/api/v1/investments/share-sale-allocations?${query}`,
        "GET",
        request,
        undefined,
        isShareSaleAllocationPageWire,
      );
    },

    async investmentsListYearEndMeasurements(
      request: InvestmentsListRequest,
    ): Promise<InvestmentYearEndMeasurementPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        `${baseUrl}/api/v1/investments/year-end-measurements?${query}`,
        "GET",
        request,
        undefined,
        isInvestmentYearEndMeasurementPageWire,
      );
    },

    async ledgerGetReconstructionAssessment(
      request: LedgerReconstructionRequest,
    ): Promise<LedgerReconstructionAssessmentWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
      });
      return executeJson(
        `${baseUrl}/api/v1/ledger/reconstruction-assessment?${query}`,
        "GET",
        request,
        undefined,
        isLedgerReconstructionAssessmentWire,
      );
    },

    async ledgerGetCompanyYearCloseAssessment(
      request: LedgerReconstructionRequest,
    ): Promise<LedgerCompanyYearCloseAssessmentWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
      });
      return executeJson(
        `${baseUrl}/api/v1/ledger/company-year-close-assessment?${query}`,
        "GET",
        request,
        undefined,
        isLedgerCompanyYearCloseAssessmentWire,
      );
    },

    async ledgerListOpeningSnapshots(
      request: LedgerOpeningSnapshotListRequest,
    ): Promise<LedgerOpeningSnapshotPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        `${baseUrl}/api/v1/ledger/opening-snapshots?${query}`,
        "GET",
        request,
        undefined,
        isLedgerOpeningSnapshotPageWire,
      );
    },

    async ledgerListPeriodLocks(
      request: LedgerListRequest,
    ): Promise<LedgerPeriodLockPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        `${baseUrl}/api/v1/ledger/period-locks?${query}`,
        "GET",
        request,
        undefined,
        isLedgerPeriodLockPageWire,
      );
    },

    async ledgerStartNewYear(
      body: NewYearStartWire,
      request: TalliMutationOptions,
    ): Promise<NewYearStartResultWire> {
      return executeJson(
        `${baseUrl}/api/v1/new-year-starts`,
        "POST",
        request,
        body,
        isNewYearStartResultWire,
      );
    },

    async ledgerPostAdministrativeCost(
      body: LedgerAdministrativeCostWire,
      request: TalliMutationOptions,
    ): Promise<AdministrativeCostEntryWire> {
      const result = await executeJson(
        `${baseUrl}/api/v1/ledger/administrative-costs`,
        "POST",
        request,
        body,
        isAdministrativeCostEntryWire,
      );
      if (result.companyId !== body.companyId || result.incomeYear !== body.incomeYear) {
        throw new TalliApiError(502, undefined);
      }
      return result;
    },

    async ledgerPostTaxSettlement(
      body: LedgerTaxSettlementWire,
      request: TalliMutationOptions,
    ): Promise<LedgerWriterResultWire> {
      return executeLedgerWriter(
        "/api/v1/ledger/tax-settlements",
        body,
        request,
        "TAX_SETTLEMENT",
      );
    },

    async ledgerPostManualJournal(
      body: LedgerManualJournalWire,
      request: TalliMutationOptions,
    ): Promise<LedgerPostedEntryWire> {
      return executeJson(
        `${baseUrl}/api/v1/ledger/manual-journals`,
        "POST",
        request,
        body,
        isLedgerPostedEntryWire,
      );
    },

    async ledgerLockPeriod(
      body: LedgerLockPeriodWire,
      request: TalliMutationOptions,
    ): Promise<LedgerPeriodLockWire> {
      return executeJson(
        `${baseUrl}/api/v1/ledger/period-locks`,
        "POST",
        request,
        body,
        isLedgerPeriodLockWire,
      );
    },

    async bankingImportStatement(
      body: BankStatementImportWire,
      request: TalliMutationOptions,
    ): Promise<BankStatementImportResultWire> {
      return executeJson(
        `${baseUrl}/api/v1/banking/statement-imports`,
        "POST",
        request,
        body,
        isBankStatementImportResultWire,
      );
    },

    async bankingStartConnection(
      body: StartBankConnectionWire,
      request: TalliMutationOptions,
    ): Promise<BankConsentRedirectWire> {
      return executeJson(
        baseUrl + "/api/v1/banking/connections",
        "POST",
        request,
        body,
        isBankConsentRedirectWire,
      );
    },

    async bankingListConnections(
      request: BankingConnectionListRequest,
    ): Promise<BankConnectionListWire> {
      const query = new URLSearchParams({ companyId: request.companyId });
      return executeJson(
        baseUrl + "/api/v1/banking/connections?" + query,
        "GET",
        request,
        undefined,
        isBankConnectionListWire,
      );
    },

    async bankingCompleteConnection(
      connectionId: string,
      request: BankingConnectionCallbackRequest,
    ): Promise<BankConnectionWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
      });
      if (request.code !== undefined) query.set("code", request.code);
      if (request.state !== undefined) query.set("state", request.state);
      if (request.resourceId !== undefined) query.set("resource_id", request.resourceId);
      if (request.result !== undefined) query.set("result", request.result);
      return executeJson(
        baseUrl + "/api/v1/banking/connections/" + encodeURIComponent(connectionId) + "/callback?" + query,
        "GET",
        request,
        undefined,
        isBankConnectionWire,
      );
    },

    async bankingRevokeConnection(
      connectionId: string,
      body: BankConnectionActionWire,
      request: TalliMutationOptions,
    ): Promise<void> {
      return executeEmpty(
        baseUrl + "/api/v1/banking/connections/" + encodeURIComponent(connectionId) + "/revoke",
        "POST",
        request,
        body,
      );
    },

    async bankingSyncAccount(
      connectionId: string,
      accountId: string,
      body: BankSyncWire,
      request: TalliMutationOptions,
    ): Promise<BankSyncResultWire> {
      return executeJson(
        baseUrl + "/api/v1/banking/connections/" + encodeURIComponent(connectionId)
          + "/accounts/" + encodeURIComponent(accountId) + "/syncs",
        "POST",
        request,
        body,
        isBankSyncResultWire,
      );
    },

    async bankingPreviewSourceFile(
      body: BankFilePreviewWire,
      request: TalliMutationOptions,
    ): Promise<BankFilePreviewResultWire> {
      return executeJson(
        baseUrl + "/api/v1/banking/source-files/previews",
        "POST",
        request,
        body,
        isBankFilePreviewResultWire,
      );
    },

    async bankingAcceptSourceFile(
      sourceFileId: string,
      body: AcceptBankFileWire,
      request: TalliMutationOptions,
    ): Promise<BankStatementImportResultWire> {
      return executeJson(
        baseUrl + "/api/v1/banking/source-files/" + encodeURIComponent(sourceFileId) + "/acceptance",
        "POST",
        request,
        body,
        isBankStatementImportResultWire,
      );
    },

    async bankingListTransactions(
      request: BankingListRequest,
    ): Promise<BankTransactionPageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        `${baseUrl}/api/v1/banking/transactions?${query}`,
        "GET",
        request,
        undefined,
        isBankTransactionPageWire,
      );
    },

    async bankingAcceptSuggestion(
      body: AcceptBankSuggestionWire,
      request: TalliMutationOptions,
    ): Promise<AcceptedBankSuggestionWire> {
      return executeJson(
        `${baseUrl}/api/v1/banking/suggestion-acceptances`,
        "POST",
        request,
        body,
        isAcceptedBankSuggestionWire,
      );
    },

    async bankingListSuggestionAcceptances(
      request: BankingListRequest,
    ): Promise<BankSuggestionAcceptancePageWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyId", companyId);
      if (request.cursor !== undefined) query.set("cursor", request.cursor);
      if (request.limit !== undefined) query.set("limit", String(request.limit));
      return executeJson(
        `${baseUrl}/api/v1/banking/suggestion-acceptances?${query}`,
        "GET",
        request,
        undefined,
        isBankSuggestionAcceptancePageWire,
      );
    },

    async billingStartAnnualCheckout(
      body: AnnualCheckoutCommandWire,
      request: TalliMutationOptions,
    ): Promise<AnnualCheckoutWire> {
      return executeJson(baseUrl + "/api/v1/billing/annual/checkouts", "POST", request, body, isAnnualCheckoutWire);
    },

    async billingCleanupAnnualAgreement(
      body: AnnualAgreementCleanupCommandWire,
      request: TalliRequestOptions = {},
    ): Promise<AnnualAgreementCleanupWire> {
      return executeJson(baseUrl + "/api/v1/billing/annual/agreement-cleanups", "POST", request, body, isAnnualAgreementCleanupWire);
    },

    async billingObserveAnnualCheckout(
      body: AnnualCheckoutObservationCommandWire,
      request: TalliRequestOptions,
    ): Promise<AnnualCheckoutWire> {
      return executeJson(baseUrl + "/api/v1/billing/annual/checkout-observations", "POST", request, body, isAnnualCheckoutWire);
    },

    async billingReadAnnualSnapshot(
      request: AnnualBillingSnapshotRequest,
    ): Promise<AnnualBillingSnapshotWire> {
      const query = new URLSearchParams({companyId: request.companyId, incomeYear: String(request.incomeYear)});
      if (request.beforePurchaseId !== undefined) query.set("beforePurchaseId", request.beforePurchaseId);
      return executeJson(baseUrl + "/api/v1/billing/annual/snapshot?" + query, "GET", request, undefined, isAnnualBillingSnapshotWire);
    },

    async billingCancelAnnualRenewal(
      body: AnnualRenewalCancellationCommandWire,
      request: TalliMutationOptions,
    ): Promise<AnnualRenewalCancellationWire> {
      return executeJson(baseUrl + "/api/v1/billing/annual/renewal-cancellations", "POST", request, body, isAnnualRenewalCancellationWire);
    },

    async billingReadSnapshot(
      request: BillingSnapshotRequest,
    ): Promise<BillingSnapshotWire> {
      const query = new URLSearchParams();
      for (const companyId of request.companyIds) query.append("companyIds", companyId);
      return executeJson(
        baseUrl + "/api/v1/billing/snapshot?" + query,
        "GET",
        request,
        undefined,
        isBillingSnapshotWire,
      );
    },

    async billingReadEntitlement(
      request: BillingEntitlementRequest,
    ): Promise<BillingEntitlementDecisionWire> {
      const query = new URLSearchParams({
        companyId: request.companyId,
        incomeYear: String(request.incomeYear),
        obligation: request.obligation,
      });
      if (request.caseProfile !== undefined) query.set("caseProfile", request.caseProfile);
      return executeJson(
        baseUrl + "/api/v1/billing/entitlement?" + query,
        "GET",
        request,
        undefined,
        isBillingEntitlementDecisionWire,
      );
    },



    async billingCancelSubscription(
      body: BillingCompanyWire,
      request: TalliMutationOptions,
    ): Promise<BillingPaymentEventWire> {
      return executeJson(baseUrl + "/api/v1/billing/subscriptions/cancellation", "POST", request, body, isBillingPaymentEventWire);
    },


    async billingRefundFilingPackage(
      body: BillingFilingPackageWire,
      request: TalliMutationOptions,
    ): Promise<BillingPaymentEventWire> {
      return executeJson(baseUrl + "/api/v1/billing/filing-package/refund", "POST", request, body, isBillingPaymentEventWire);
    },

    async billingMarkUnsupported(
      body: BillingUnsupportedWire,
      request: TalliMutationOptions,
    ): Promise<BillingAccountWire> {
      return executeJson(baseUrl + "/api/v1/billing/unsupported", "POST", request, body, isBillingAccountWire);
    },

    async billingManagePilotEntitlement(
      body: BillingPilotEntitlementCommandWire,
      request: TalliMutationOptions,
    ): Promise<BillingPilotEntitlementWire> {
      return executeJson(baseUrl + "/api/v1/billing/pilot-entitlements", "POST", request, body, isBillingPilotEntitlementWire);
    },

    async marketingMeasurementRecordEvent(
      body: MarketingMeasurementEventWire,
      request: TalliRequestOptions = {},
    ): Promise<MarketingMeasurementEventResponse> {
      return executeJson(
        `${baseUrl}/api/v1/marketing-measurement/events`,
        "POST",
        request,
        body,
        isMarketingMeasurementEventResponse,
      );
    },

    async marketingMeasurementWithdrawSession(
      body: MarketingMeasurementWithdrawalRequest,
      request: TalliRequestOptions = {},
    ): Promise<MarketingMeasurementWithdrawalResponse> {
      return executeJson(
        `${baseUrl}/api/v1/marketing-measurement/withdrawals`,
        "POST",
        request,
        body,
        isMarketingMeasurementWithdrawalResponse,
      );
    },

    async marketingMeasurementGetReport(
      request: MarketingMeasurementReportRequest = {},
    ): Promise<MarketingFunnelReportResponse> {
      const query = new URLSearchParams();
      if (request.windowDays !== undefined) query.set("window_days", String(request.windowDays));
      const suffix = query.size ? `?${query}` : "";
      return executeJson(
        `${baseUrl}/api/v1/marketing-measurement/report${suffix}`,
        "GET",
        request,
        undefined,
        isMarketingFunnelReportResponse,
      );
    },
  };
}
