"""Finite, fixture-bound simulation for Accounts draft preparation only."""
from dataclasses import dataclass
from datetime import UTC, datetime
from talli_backend.modules.annual_accounts_filing.delivery import (
    SYNTHETIC_BOARD as BOARD, SYNTHETIC_MEETING as MEETING, SYNTHETIC_SIGNOFF_KIND as KIND,
)


@dataclass(frozen=True, slots=True)
class PrivatePreviewAccountsSignoff:
    company_id: str
    decision_id: str
    decision_sha256: str
    source_sha256: str
    unsigned_document_sha256: dict[str, str]
    expires_at: datetime
    now: object

    def evidence(self, readiness, lifecycle, *, company_id, income_year):
        if (self.now() >= self.expires_at or str(company_id) != self.company_id or int(income_year) != 2025
                or str(readiness.decision_id) != self.decision_id
                or readiness.decision_hash != self.decision_sha256
                or readiness.source_hash != self.source_sha256
                or readiness.current_source_matches is not True
                or readiness.state is None or readiness.state.value != 'facts_approved'
                or readiness.finalized or readiness.annual_submission_ready or readiness.finalization_id is not None
                or dict(readiness.signed_artifact_hashes) or dict(readiness.generated_artifact_hashes) != self.unsigned_document_sha256
                or {item.code for item in readiness.blockers} != {
                    'corporate_documents_missing_signed_artifacts', 'corporate_documents_finalization_required'}
                or any(str(item.decision_id) == self.decision_id for item in lifecycle.finalizations)):
            return None
        return {'kind': KIND, 'companyId': self.company_id, 'incomeYear': 2025,
            'decisionId': self.decision_id, 'decisionSha256': self.decision_sha256,
            'sourceSha256': self.source_sha256, 'unsignedDocumentSha256': self.unsigned_document_sha256,
            'expiresAt': self.expires_at.astimezone(UTC).isoformat(),
            'statement': 'Synthetic test sign-off only; originals are unsigned; no owner signed-copy attestation or finalization.'}
