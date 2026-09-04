import {
  type AnnualCloseEventWire,
  type AnnualCloseFinalizationWire,
  type AnnualCloseProposalWire,
  type AnnualCloseSignedArtifactWire,
  type CorporateCanonicalDecisionWire,
  type CorporateGovernanceDecisionFactsRequest,
  type CorporateGovernanceReadinessRequest,
  type CorporateLifecycleSnapshotWire,
  createTalliApiClient,
  type OwnerDividendApprovalWire,
  type OwnerDividendDocumentsWire,
  type OwnerDividendEventWire,
  type OwnerDividendFinalizationWire,
  type OwnerDividendPaymentWire,
  type OwnerDividendProposalWire,
  type OwnerDividendSignedArtifactWire,
  type ReverseSupportedCorporateEventWire,
  type ShareholderLoanWire,
  type SupportedCorporateEventWire,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

function mutation(idempotencyKey: string, requestId?: string) {
  return {
    idempotencyKey,
    requestId,
    signal: AbortSignal.timeout(10_000),
  };
}

function canonicalInputFromWire(
  input: Record<string, unknown>,
): Record<string, unknown> {
  const decision = input as unknown as CorporateCanonicalDecisionWire;
  return {
    request_id: decision.decisionId,
    company_id: decision.companyId,
    organization_number: decision.organizationNumber,
    legal_name: decision.legalName,
    income_year: decision.incomeYear,
    decision_kind: decision.decisionKind,
    annual_close_source_id: decision.annualCloseSourceId,
    source_hash: decision.sourceHash,
    template_family: decision.templateFamily,
    template_version: decision.templateVersion,
    annual_basis_year: decision.annualBasisYear,
    financial_totals: {
      result_after_tax_ore: decision.financialTotals.resultAfterTaxOre,
      equity_ore: decision.financialTotals.equityOre,
      available_distribution_ore: decision.financialTotals.availableDistributionOre,
      cash_ore: decision.financialTotals.cashOre,
    },
    board_meeting: {
      meeting_date: decision.boardMeeting.meetingDate,
      meeting_time: decision.boardMeeting.meetingTime,
      place: decision.boardMeeting.place,
      treatment_method: decision.boardMeeting.treatmentMethod,
    },
    board_participants: decision.boardParticipants.map((participant) => ({
      participant_id: participant.participantId,
      name: participant.name,
      role: participant.role,
    })),
    general_meeting: {
      meeting_date: decision.generalMeeting.meetingDate,
      meeting_time: decision.generalMeeting.meetingTime,
      place: decision.generalMeeting.place,
      meeting_form: decision.generalMeeting.meetingForm,
      chair_name: decision.generalMeeting.chairName,
      co_signer_name: decision.generalMeeting.coSignerName,
    },
    shareholders: decision.shareholders.map((shareholder) => ({
      shareholder_id: shareholder.shareholderId,
      name: shareholder.name,
      share_count: shareholder.shareCount,
      represented_share_count: shareholder.representedShareCount,
      vote: shareholder.vote,
    })),
    total_company_shares: decision.totalCompanyShares,
    one_share_class_confirmed: decision.oneShareClassConfirmed,
    dividend: decision.dividend === null ? null : {
      amount_ore: decision.dividend.amountOre,
      payment_date: decision.dividend.paymentDate,
      liquidity_after_payment_ore: decision.dividend.liquidityAfterPaymentOre,
      allocations: decision.dividend.allocations.map((allocation) => ({
        shareholder_id: allocation.shareholderId,
        amount_ore: allocation.amountOre,
      })),
    },
    annual_result_allocation_ore: decision.annualResultAllocationOre,
    confirmations: {
      latest_approved_annual_accounts: decision.confirmations.latestApprovedAnnualAccounts,
      supported_dividend_basis: decision.confirmations.supportedDividendBasis,
      full_board_participation: decision.confirmations.fullBoardParticipation,
      full_share_representation: decision.confirmations.fullShareRepresentation,
      unanimous_board: decision.confirmations.unanimousBoard,
      unanimous_shareholders: decision.confirmations.unanimousShareholders,
      proportional_allocation: decision.confirmations.proportionalAllocation,
      prudent_equity_and_liquidity: decision.confirmations.prudentEquityAndLiquidity,
    },
  };
}

export function presentCorporateLifecycle(snapshot: CorporateLifecycleSnapshotWire) {
  return {
    corporateDecisions: snapshot.decisions.map((item) => ({
      id: item.decisionId,
      company_id: item.companyId,
      income_year: item.incomeYear,
      decision_kind: item.decisionKind,
      annual_close_source_id: item.annualCloseSourceId,
      source_hash: item.sourceHash,
      canonical_input: canonicalInputFromWire(item.canonicalInput),
      decision_hash: item.decisionHash,
      supersedes_decision_id: item.supersedesDecisionId,
      created_by: item.createdBy,
      created_at: item.createdAt,
    })),
    corporateDocumentSets: snapshot.documentSets.map((item) => ({
      id: item.documentSetId,
      company_id: item.companyId,
      income_year: item.incomeYear,
      decision_id: item.decisionId,
      template_family: item.templateFamily,
      template_version: item.templateVersion,
      decision_hash: item.decisionHash,
      supersedes_set_id: item.supersedesDocumentSetId,
      created_by: item.createdBy,
      created_at: item.createdAt,
    })),
    corporateDocumentArtifacts: snapshot.artifacts.map((item) => ({
      id: item.artifactId,
      company_id: item.companyId,
      income_year: item.incomeYear,
      set_id: item.documentSetId,
      artifact_kind: item.artifactKind,
      variant: item.variant,
      document_id: item.documentId,
      content_sha256: item.contentSha256,
      byte_length: item.byteLength,
      mime_type: "application/pdf" as const,
      supersedes_artifact_id: item.supersedesArtifactId,
      created_by: item.createdBy,
      created_at: item.createdAt,
    })),
    corporateDocumentEvents: snapshot.events.map((item) => ({
      id: item.eventId,
      company_id: item.companyId,
      income_year: item.incomeYear,
      decision_id: item.decisionId,
      set_id: item.documentSetId,
      artifact_id: item.artifactId,
      event_kind: item.eventKind,
      actor_id: item.actorId,
      occurred_at: item.occurredAt,
      decision_hash: item.decisionHash,
      content_sha256: item.contentSha256,
      metadata: item.metadata,
      idempotency_key: item.idempotencyKey,
      created_at: item.createdAt,
    })),
    corporateDecisionFinalizations: snapshot.finalizations.map((item) => ({
      id: item.finalizationId,
      company_id: item.companyId,
      income_year: item.incomeYear,
      decision_id: item.decisionId,
      finalization_kind: item.finalizationKind as "owner_dividend_declared" | "annual_close_adopted",
      holding_action_id: item.holdingActionId,
      ledger_entry_id: item.accountingEntryId,
      annual_close_source_id: item.annualCloseSourceId,
      decision_hash: item.decisionHash,
      signed_artifact_hashes: item.signedArtifactHashes,
      accounting_policy_version: item.accountingPolicyVersion,
      created_by: item.createdBy,
      created_at: item.createdAt,
    })),
  };
}

export async function listCorporateDecisionLifecycle(
  accessToken: string,
  companyIds: readonly string[],
) {
  const snapshot = await client(accessToken).corporateGovernanceListDecisionLifecycle({
    companyIds,
    signal: AbortSignal.timeout(10_000),
  });
  return presentCorporateLifecycle(snapshot);
}

export async function readCorporateDecisionReadiness(
  accessToken: string,
  request: Omit<CorporateGovernanceReadinessRequest, "signal">,
) {
  return client(accessToken).corporateGovernanceReadDecisionReadiness({
    ...request,
    signal: AbortSignal.timeout(10_000),
  });
}

export async function deriveCorporateDecisionFacts(
  accessToken: string,
  request: Omit<CorporateGovernanceDecisionFactsRequest, "signal">,
) {
  return client(accessToken).corporateGovernanceDeriveDecisionFacts({
    ...request,
    signal: AbortSignal.timeout(10_000),
  });
}

export async function readCorporateDecisionLifecycle(
  accessToken: string,
  decisionId: string,
) {
  const snapshot = await client(accessToken).corporateGovernanceReadDecisionLifecycle(
    decisionId,
    { signal: AbortSignal.timeout(10_000) },
  );
  return presentCorporateLifecycle(snapshot);
}

export function proposeOwnerDividend(
  accessToken: string,
  body: OwnerDividendProposalWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceProposeOwnerDividend(
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function proposeAnnualClose(
  accessToken: string,
  body: AnnualCloseProposalWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceProposeAnnualClose(
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function listSupportedCorporateEvents(
  accessToken: string,
  companyIds: readonly string[],
) {
  return client(accessToken).corporateGovernanceListSupportedEvents({
    companyIds,
    signal: AbortSignal.timeout(10_000),
  });
}

export function recordSupportedCorporateEvent(
  accessToken: string,
  body: SupportedCorporateEventWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceRecordSupportedEvent(
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function reverseSupportedCorporateEvent(
  accessToken: string,
  eventId: string,
  body: ReverseSupportedCorporateEventWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceReverseSupportedEvent(
    eventId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function registerAnnualCloseDocuments(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendDocumentsWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceRegisterAnnualCloseDocuments(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function approveAnnualClose(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendApprovalWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceApproveAnnualClose(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function recordAnnualCloseEvent(
  accessToken: string,
  decisionId: string,
  body: AnnualCloseEventWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceRecordAnnualCloseEvent(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function finalizeAnnualClose(
  accessToken: string,
  decisionId: string,
  body: AnnualCloseFinalizationWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceFinalizeAnnualClose(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function attestAnnualCloseSignedArtifact(
  accessToken: string,
  decisionId: string,
  body: AnnualCloseSignedArtifactWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceAttestAnnualCloseSignedArtifact(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function recordShareholderLoan(
  accessToken: string,
  body: ShareholderLoanWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceRecordShareholderLoan(
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function registerOwnerDividendDocuments(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendDocumentsWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceRegisterOwnerDividendDocuments(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function approveOwnerDividend(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendApprovalWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceApproveOwnerDividend(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function recordOwnerDividendEvent(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendEventWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceRecordOwnerDividendEvent(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function attestOwnerDividendSignedArtifact(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendSignedArtifactWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceAttestOwnerDividendSignedArtifact(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function finalizeOwnerDividend(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendFinalizationWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceFinalizeOwnerDividend(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}

export function recordOwnerDividendPayment(
  accessToken: string,
  decisionId: string,
  body: OwnerDividendPaymentWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).corporateGovernanceRecordOwnerDividendPayment(
    decisionId,
    body,
    mutation(idempotencyKey, requestId),
  );
}
