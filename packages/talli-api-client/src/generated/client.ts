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
  businessTermsSha256: "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543";
  businessTermsVersion: "2026-07-17";
  dpaSha256: "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c";
  dpaVersion: "2026-07-17";
  orgNumber: string;
}

export interface CompanyOnboardingResponse {
  companyId: string;
  currentAgreementAccepted: true;
  replayed: boolean;
}

export interface CompanyAgreementAcceptanceRequest {
  agreementAccepted: true;
  businessTermsSha256: "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543";
  businessTermsVersion: "2026-07-17";
  companyId: string;
  dpaSha256: "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c";
  dpaVersion: "2026-07-17";
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
  answerOptions?: "yes" | "no" | "unknown"[];
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
  businessTermsSha256: "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543";
  businessTermsVersion: "2026-07-17";
  capabilityManifestSha256: string;
  capabilityManifestVersion: string;
  companyYearPromiseAccepted: true;
  dpaSha256: "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c";
  dpaVersion: "2026-07-17";
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

export interface LedgerBankSuggestionWire {
  acceptanceId: string;
  bankTransactionId: string;
  companyId: string;
  incomeYear: number;
  rule: "bank_fee" | "system_subscription" | "deposit_interest";
  ruleVersion: string;
}

export interface LedgerCorporateDecisionFinalizationWire {
  companyId: string;
  decisionHash: string;
  decisionId: string;
  finalizationId: string;
  holdingActionId?: string | null;
  incomeYear: number;
  ledgerEntryId?: string | null;
  setId: string;
}

export type LedgerEntryKind = "OPENING_BALANCE" | "ADMINISTRATIVE_COST" | "MANUAL_JOURNAL" | "BANK_RULE_SUGGESTION" | "DIVIDEND_RECEIVED" | "OWNER_DIVIDEND_DECLARED" | "OWNER_DIVIDEND_PAYMENT" | "SHARE_PURCHASE" | "SHARE_SALE" | "SHAREHOLDER_LOAN" | "TAX_SETTLEMENT";

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

export interface LedgerInvestmentDividendWire {
  actionId: string;
  bankTransactionId?: string | null;
  companyId: string;
  declaredDate: string;
  documentId?: string | null;
  documentStatus: "attached" | "missing_accepted_warning" | "not_required";
  grossAmount: LedgerMoneyWire;
  incomeYear: number;
  linkedInvestmentId?: string | null;
  paidDate: string;
  payingCompanyName: string;
  taxTreatment: "fritaksmetoden" | "outside_fritaksmetoden" | "needs_accountant";
}

export interface LedgerInvestmentPurchaseWire {
  acquisitionDate: string;
  actionId: string;
  bankTransactionId?: string | null;
  companyId: string;
  documentId?: string | null;
  documentStatus: "attached" | "missing_accepted_warning" | "not_required";
  incomeYear: number;
  investmentKey: string;
  investmentKind: "norwegian_private_company";
  investmentName: string;
  orgNumber?: string | null;
  purchaseAmount: LedgerMoneyWire;
  shareCount: number;
  taxTreatment: "fritaksmetoden";
}

export interface LedgerInvestmentSaleWire {
  actionId: string;
  bankTransactionId?: string | null;
  companyId: string;
  documentId?: string | null;
  documentStatus: "attached" | "missing_accepted_warning" | "not_required";
  incomeYear: number;
  positionId: string;
  proceeds: LedgerMoneyWire;
  saleDate: string;
  soldShareCount: number;
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
  evidenceDigest: string;
  gapCodes: ReconstructionGapCode[];
  incomeYear: number;
  recordedAt: string;
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

export interface LedgerShareholderLoanWire {
  actionId: string;
  amount: LedgerMoneyWire;
  bankTransactionId?: string | null;
  companyId: string;
  counterpartyName: string;
  direction: "shareholder_to_company" | "company_to_corporate_shareholder";
  documentId?: string | null;
  documentStatus: "attached" | "missing_accepted_warning" | "not_required";
  incomeYear: number;
  interestModelled: boolean;
  loanDate: string;
  relatedPartySecurity: false;
}

export type LedgerSourceCapability = "LEDGER" | "BANKING" | "INVESTMENTS" | "CORPORATE_GOVERNANCE" | "SHAREHOLDER_REGISTER_FILING" | "COMPANY_TAX_FILING";

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

export interface LedgerOwnerDividendPaymentWire {
  bankTransactionId: string;
  companyId: string;
  decisionHash: string;
  decisionId: string;
  holdingActionId: string;
  incomeYear: number;
  ledgerEntryId: string;
  setId: string;
}

export interface LedgerWriterResultWire {
  postedEntry: LedgerPostedEntryWire | null;
  replayed: boolean;
}

export type ReconstructionState = "BLOCKED" | "READY";

export type TaxSettlementKind = "payable" | "payment" | "refund";

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

function isLedgerBankSuggestionWire(value: unknown): value is LedgerBankSuggestionWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["acceptanceId","bankTransactionId","companyId","incomeYear","rule","ruleVersion"]) &&
    isUuid(value.acceptanceId) &&
    isUuid(value.bankTransactionId) &&
    isUuid(value.companyId) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (value.rule === "bank_fee" || value.rule === "system_subscription" || value.rule === "deposit_interest") &&
    (typeof value.ruleVersion === "string" && value.ruleVersion.length >= 1 && value.ruleVersion.length <= 64)
  );
}

function isLedgerCorporateDecisionFinalizationWire(value: unknown): value is LedgerCorporateDecisionFinalizationWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","decisionHash","decisionId","finalizationId","holdingActionId","incomeYear","ledgerEntryId","setId"]) &&
    isUuid(value.companyId) &&
    (typeof value.decisionHash === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.decisionHash)) &&
    isUuid(value.decisionId) &&
    isUuid(value.finalizationId) &&
    (value.holdingActionId === undefined || (isUuid(value.holdingActionId) || value.holdingActionId === null)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (value.ledgerEntryId === undefined || (isUuid(value.ledgerEntryId) || value.ledgerEntryId === null)) &&
    isUuid(value.setId)
  );
}

function isLedgerEntryKind(value: unknown): value is LedgerEntryKind {
  return value === "OPENING_BALANCE" || value === "ADMINISTRATIVE_COST" || value === "MANUAL_JOURNAL" || value === "BANK_RULE_SUGGESTION" || value === "DIVIDEND_RECEIVED" || value === "OWNER_DIVIDEND_DECLARED" || value === "OWNER_DIVIDEND_PAYMENT" || value === "SHARE_PURCHASE" || value === "SHARE_SALE" || value === "SHAREHOLDER_LOAN" || value === "TAX_SETTLEMENT";
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

function isLedgerInvestmentDividendWire(value: unknown): value is LedgerInvestmentDividendWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["actionId","bankTransactionId","companyId","declaredDate","documentId","documentStatus","grossAmount","incomeYear","linkedInvestmentId","paidDate","payingCompanyName","taxTreatment"]) &&
    isUuid(value.actionId) &&
    (value.bankTransactionId === undefined || (isUuid(value.bankTransactionId) || value.bankTransactionId === null)) &&
    isUuid(value.companyId) &&
    typeof value.declaredDate === "string" &&
    (value.documentId === undefined || (isUuid(value.documentId) || value.documentId === null)) &&
    (value.documentStatus === "attached" || value.documentStatus === "missing_accepted_warning" || value.documentStatus === "not_required") &&
    isLedgerMoneyWire(value.grossAmount) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (value.linkedInvestmentId === undefined || (isUuid(value.linkedInvestmentId) || value.linkedInvestmentId === null)) &&
    typeof value.paidDate === "string" &&
    (typeof value.payingCompanyName === "string" && value.payingCompanyName.length >= 1 && value.payingCompanyName.length <= 255) &&
    (value.taxTreatment === "fritaksmetoden" || value.taxTreatment === "outside_fritaksmetoden" || value.taxTreatment === "needs_accountant")
  );
}

function isLedgerInvestmentPurchaseWire(value: unknown): value is LedgerInvestmentPurchaseWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["acquisitionDate","actionId","bankTransactionId","companyId","documentId","documentStatus","incomeYear","investmentKey","investmentKind","investmentName","orgNumber","purchaseAmount","shareCount","taxTreatment"]) &&
    typeof value.acquisitionDate === "string" &&
    isUuid(value.actionId) &&
    (value.bankTransactionId === undefined || (isUuid(value.bankTransactionId) || value.bankTransactionId === null)) &&
    isUuid(value.companyId) &&
    (value.documentId === undefined || (isUuid(value.documentId) || value.documentId === null)) &&
    (value.documentStatus === "attached" || value.documentStatus === "missing_accepted_warning" || value.documentStatus === "not_required") &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    (typeof value.investmentKey === "string" && value.investmentKey.length >= 1 && value.investmentKey.length <= 255) &&
    value.investmentKind === "norwegian_private_company" &&
    (typeof value.investmentName === "string" && value.investmentName.length >= 1 && value.investmentName.length <= 255) &&
    (value.orgNumber === undefined || ((typeof value.orgNumber === "string" && new RegExp("^\\d{9}$", "u").test(value.orgNumber)) || value.orgNumber === null)) &&
    isLedgerMoneyWire(value.purchaseAmount) &&
    (typeof value.shareCount === "number" && Number.isInteger(value.shareCount) && value.shareCount <= 9007199254740991 && value.shareCount > 0) &&
    value.taxTreatment === "fritaksmetoden"
  );
}

function isLedgerInvestmentSaleWire(value: unknown): value is LedgerInvestmentSaleWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["actionId","bankTransactionId","companyId","documentId","documentStatus","incomeYear","positionId","proceeds","saleDate","soldShareCount"]) &&
    isUuid(value.actionId) &&
    (value.bankTransactionId === undefined || (isUuid(value.bankTransactionId) || value.bankTransactionId === null)) &&
    isUuid(value.companyId) &&
    (value.documentId === undefined || (isUuid(value.documentId) || value.documentId === null)) &&
    (value.documentStatus === "attached" || value.documentStatus === "missing_accepted_warning" || value.documentStatus === "not_required") &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isUuid(value.positionId) &&
    isLedgerMoneyWire(value.proceeds) &&
    typeof value.saleDate === "string" &&
    (typeof value.soldShareCount === "number" && Number.isInteger(value.soldShareCount) && value.soldShareCount <= 9007199254740991 && value.soldShareCount > 0)
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
    hasOnlyProperties(value, ["bankBalance","companyId","incomeYear","nominalValue","shareCapital","shareCount","shareholders"]) &&
    isLedgerMoneyWire(value.bankBalance) &&
    isUuid(value.companyId) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isLedgerMoneyWire(value.nominalValue) &&
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
    hasOnlyProperties(value, ["asOf","assessmentId","companyId","evidenceDigest","gapCodes","incomeYear","recordedAt","state"]) &&
    typeof value.asOf === "string" &&
    isUuid(value.assessmentId) &&
    isUuid(value.companyId) &&
    (typeof value.evidenceDigest === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.evidenceDigest)) &&
    Array.isArray(value.gapCodes) && value.gapCodes.every((item) => isReconstructionGapCode(item)) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isDateTime(value.recordedAt) &&
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

function isLedgerShareholderLoanWire(value: unknown): value is LedgerShareholderLoanWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["actionId","amount","bankTransactionId","companyId","counterpartyName","direction","documentId","documentStatus","incomeYear","interestModelled","loanDate","relatedPartySecurity"]) &&
    isUuid(value.actionId) &&
    isLedgerMoneyWire(value.amount) &&
    (value.bankTransactionId === undefined || (isUuid(value.bankTransactionId) || value.bankTransactionId === null)) &&
    isUuid(value.companyId) &&
    (typeof value.counterpartyName === "string" && value.counterpartyName.length >= 1 && value.counterpartyName.length <= 255) &&
    (value.direction === "shareholder_to_company" || value.direction === "company_to_corporate_shareholder") &&
    (value.documentId === undefined || (isUuid(value.documentId) || value.documentId === null)) &&
    (value.documentStatus === "attached" || value.documentStatus === "missing_accepted_warning" || value.documentStatus === "not_required") &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    typeof value.interestModelled === "boolean" &&
    typeof value.loanDate === "string" &&
    value.relatedPartySecurity === false
  );
}

function isLedgerSourceCapability(value: unknown): value is LedgerSourceCapability {
  return value === "LEDGER" || value === "BANKING" || value === "INVESTMENTS" || value === "CORPORATE_GOVERNANCE" || value === "SHAREHOLDER_REGISTER_FILING" || value === "COMPANY_TAX_FILING";
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

function isLedgerOwnerDividendPaymentWire(value: unknown): value is LedgerOwnerDividendPaymentWire {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["bankTransactionId","companyId","decisionHash","decisionId","holdingActionId","incomeYear","ledgerEntryId","setId"]) &&
    isUuid(value.bankTransactionId) &&
    isUuid(value.companyId) &&
    (typeof value.decisionHash === "string" && new RegExp("^[a-f0-9]{64}$", "u").test(value.decisionHash)) &&
    isUuid(value.decisionId) &&
    isUuid(value.holdingActionId) &&
    (typeof value.incomeYear === "number" && Number.isInteger(value.incomeYear) && value.incomeYear >= 2000 && value.incomeYear <= 2100) &&
    isUuid(value.ledgerEntryId) &&
    isUuid(value.setId)
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

export interface LedgerOpeningSnapshotListRequest extends TalliRequestOptions {
  companyIds: readonly string[];
  cursor?: string;
  limit?: number;
}

export interface LedgerReconstructionRequest extends TalliRequestOptions {
  companyId: string;
  incomeYear: number;
}

export interface CompanyAccessContextRequest extends TalliRequestOptions {
  companyId?: string;
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
      body: ReviewCompanyDeletionRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyDeletionReviewResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/cancellations/${encodeURIComponent(cancellationId)}/reviews`,
        "POST",
        request,
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

    async ledgerPostInvestmentDividend(
      body: LedgerInvestmentDividendWire,
      request: TalliMutationOptions,
    ): Promise<LedgerWriterResultWire> {
      return executeLedgerWriter(
        "/api/v1/ledger/investment-dividends",
        body,
        request,
        "DIVIDEND_RECEIVED",
      );
    },

    async ledgerPostShareholderLoan(
      body: LedgerShareholderLoanWire,
      request: TalliMutationOptions,
    ): Promise<LedgerWriterResultWire> {
      return executeLedgerWriter(
        "/api/v1/ledger/shareholder-loans",
        body,
        request,
        "SHAREHOLDER_LOAN",
      );
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

    async ledgerPostBankSuggestionOutcome(
      body: LedgerBankSuggestionWire,
      request: TalliMutationOptions,
    ): Promise<LedgerWriterResultWire> {
      return executeLedgerWriter(
        "/api/v1/ledger/bank-suggestion-outcomes",
        body,
        request,
        "BANK_RULE_SUGGESTION",
      );
    },

    async ledgerPostInvestmentPurchase(
      body: LedgerInvestmentPurchaseWire,
      request: TalliMutationOptions,
    ): Promise<LedgerWriterResultWire> {
      return executeLedgerWriter(
        "/api/v1/ledger/investment-purchases",
        body,
        request,
        "SHARE_PURCHASE",
      );
    },

    async ledgerPostInvestmentSale(
      body: LedgerInvestmentSaleWire,
      request: TalliMutationOptions,
    ): Promise<LedgerWriterResultWire> {
      return executeLedgerWriter(
        "/api/v1/ledger/investment-sales",
        body,
        request,
        "SHARE_SALE",
      );
    },

    async ledgerFinalizeCorporateDecision(
      body: LedgerCorporateDecisionFinalizationWire,
      request: TalliMutationOptions,
    ): Promise<LedgerWriterResultWire> {
      return executeLedgerWriter(
        "/api/v1/ledger/corporate-decisions/finalizations",
        body,
        request,
        body.ledgerEntryId === undefined || body.ledgerEntryId === null
          ? null
          : "OWNER_DIVIDEND_DECLARED",
      );
    },

    async ledgerPostOwnerDividendPayment(
      body: LedgerOwnerDividendPaymentWire,
      request: TalliMutationOptions,
    ): Promise<LedgerWriterResultWire> {
      return executeLedgerWriter(
        "/api/v1/ledger/owner-dividends/payments",
        body,
        request,
        "OWNER_DIVIDEND_PAYMENT",
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
  };
}
