from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SubmissionStatus(StrEnum):
    READY = "ready"
    AUTHORITY_CONFIRMED = "authority_confirmed"
    PREVIEW_CONFIRMED = "preview_confirmed"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    FEEDBACK_READY = "feedback_ready"
    RECEIPT_STORED = "receipt_stored"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_BLOCKED = "failed_blocked"


class SubmissionCallStatus(StrEnum):
    PREPARED = "prepared"
    SENT = "sent"
    ACCEPTED = "accepted"
    FAILED = "failed"


class SubmissionCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str
    body_hash: str
    idempotency_key: str
    status: SubmissionCallStatus = SubmissionCallStatus.PREPARED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FilingSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filing: str
    company_id: str
    income_year: int
    status: SubmissionStatus
    authority_confirmed_by: str | None = None
    authority_confirmed_at: datetime | None = None
    preview_confirmed_by: str | None = None
    preview_confirmed_at: datetime | None = None
    calls: tuple[SubmissionCall, ...] = ()
    receipt_id: str | None = None
    feedback_document_ids: tuple[str, ...] = ()
    failure_code: str | None = None
    failure_message: str | None = None

    @property
    def user_confirmed(self) -> bool:
        return self.authority_confirmed_at is not None and self.preview_confirmed_at is not None


def prepare_submission(*, filing: str, company_id: str, income_year: int) -> FilingSubmission:
    return FilingSubmission(
        filing=filing,
        company_id=company_id,
        income_year=income_year,
        status=SubmissionStatus.READY,
    )


def confirm_authority(submission: FilingSubmission, *, user_id: str) -> FilingSubmission:
    return submission.model_copy(
        update={
            "status": SubmissionStatus.AUTHORITY_CONFIRMED,
            "authority_confirmed_by": user_id,
            "authority_confirmed_at": datetime.now(UTC),
        }
    )


def confirm_preview(submission: FilingSubmission, *, user_id: str) -> FilingSubmission:
    if submission.authority_confirmed_at is None:
        raise ValueError("authority must be confirmed before final preview")
    return submission.model_copy(
        update={
            "status": SubmissionStatus.PREVIEW_CONFIRMED,
            "preview_confirmed_by": user_id,
            "preview_confirmed_at": datetime.now(UTC),
        }
    )


def register_api_call(submission: FilingSubmission, *, endpoint: str, body: object) -> FilingSubmission:
    if not submission.user_confirmed:
        raise ValueError("authority and final preview confirmation are required before API calls")
    body_hash = _body_hash(body)
    for call in submission.calls:
        if call.endpoint == endpoint and call.body_hash == body_hash:
            return submission
    call = SubmissionCall(
        endpoint=endpoint,
        body_hash=body_hash,
        idempotency_key=_idempotency_key(submission, endpoint, body_hash),
    )
    return submission.model_copy(
        update={
            "status": SubmissionStatus.SUBMITTING,
            "calls": submission.calls + (call,),
        }
    )


def mark_submitted(submission: FilingSubmission, *, feedback_document_ids: tuple[str, ...] = ()) -> FilingSubmission:
    return submission.model_copy(
        update={
            "status": SubmissionStatus.SUBMITTED,
            "feedback_document_ids": feedback_document_ids,
            "failure_code": None,
            "failure_message": None,
        }
    )


def store_receipt(submission: FilingSubmission, *, receipt_id: str) -> FilingSubmission:
    return submission.model_copy(update={"status": SubmissionStatus.RECEIPT_STORED, "receipt_id": receipt_id})


def mark_retryable_failure(submission: FilingSubmission, *, code: str, message: str) -> FilingSubmission:
    return submission.model_copy(
        update={
            "status": SubmissionStatus.FAILED_RETRYABLE,
            "failure_code": code,
            "failure_message": message,
        }
    )


def mark_blocked_failure(submission: FilingSubmission, *, code: str, message: str) -> FilingSubmission:
    return submission.model_copy(
        update={
            "status": SubmissionStatus.FAILED_BLOCKED,
            "failure_code": code,
            "failure_message": message,
        }
    )


def _body_hash(body: object) -> str:
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _idempotency_key(submission: FilingSubmission, endpoint: str, body_hash: str) -> str:
    raw = f"{submission.company_id}:{submission.income_year}:{submission.filing}:{endpoint}:{body_hash}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))
