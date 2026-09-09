"""Generated boundary runs the frozen coordinator against local provider ports."""

from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from talli_backend.main import create_app
from talli_backend.compatibility.rf1086_authority_workflow import LegacyRf1086AuthenticationError
from talli_backend.modules.billing.public import ProductionPilotStatus
from test_rf1086_compatibility import CoordinatorSession, APPROVAL, SUBMISSION, OWNER

SEND = "/api/v1/legacy-rf1086/production-filings"
RECOVER = "/api/v1/legacy-rf1086/feedback-reconciliations"
HEADERS = {"Authorization": "Bearer local-owner", "X-Request-ID": "rf-boundary-test"}


class Sessions:
    def __init__(self):
        self.value = CoordinatorSession()
        self.tokens = []

    async def session(self, token):
        self.tokens.append(token)
        if token != "local-owner":
            raise LegacyRf1086AuthenticationError()
        return self.value


def setup():
    sessions = Sessions()
    return TestClient(create_app(legacy_rf1086_session_factory=sessions)), sessions


def test_send_authenticates_and_runs_token_before_durable_begin_and_provider_mutation():
    api, sessions = setup()
    response = api.post(SEND, headers=HEADERS, json={"approvalId": APPROVAL})
    assert response.status_code == 200, response.text
    assert response.json() == {"submissionId": SUBMISSION}
    assert sessions.tokens == ["local-owner"]
    events = sessions.value.events
    assert events.index("fresh_mfa") < events.index("mutation_token") < events.index("begin") < events.index("operation_journal")
    assert [name for name, _ in sessions.value.mutation_authority.calls] == ["main", "sub", "sub", "confirm", "list"]
    assert "discard" in events
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "rf-boundary-test"


@pytest.mark.parametrize("path,body", [(SEND, {"approvalId": APPROVAL}), (RECOVER, {"submissionId": SUBMISSION})])
@pytest.mark.parametrize("forged", [{"actorId": OWNER}, {"companyId": OWNER}, {"xml": "<form/>"},
    {"scope": "arbitrary"}, {"forsendelseId": OWNER}, {"environment": "test"}, {"status": "accepted"}])
def test_caller_cannot_supply_trusted_filing_or_provider_facts(path, body, forged):
    api, sessions = setup()
    assert api.post(path, headers=HEADERS, json=body | forged).status_code == 422
    assert not sessions.tokens and not sessions.value.events


@pytest.mark.parametrize("path,body", [(SEND, {"approvalId": APPROVAL}), (RECOVER, {"submissionId": SUBMISSION})])
def test_authentication_failure_has_no_filing_effect(path, body):
    api, sessions = setup()
    assert api.post(path, json=body).status_code == 401
    response = api.post(path, headers={"Authorization": "Bearer forged"}, json=body)
    assert response.status_code == 401
    assert "forged" not in response.text
    assert not sessions.value.events and not sessions.value.mutation_authority.calls


def test_failed_token_never_begins_a_submission_and_response_contains_no_provider_detail():
    api, sessions = setup()
    sessions.value.failure = "mutation_token"
    response = api.post(SEND, headers=HEADERS, json={"approvalId": APPROVAL})
    assert response.status_code == 503
    assert "begin" not in sessions.value.events
    assert not sessions.value.mutation_authority.calls
    assert response.json()["code"] in {"status_unavailable", "send_unavailable"}


def test_feedback_recovery_uses_original_relation_after_entitlement_and_approval_expire():
    api, sessions = setup()
    value = sessions.value
    value.billing.pilot = replace(value.billing.pilot, status=ProductionPilotStatus.SUSPENDED)
    value.billing.decision = replace(value.billing.decision, allowed=False)
    value.approval = replace(value.approval, invalidated=True)
    response = api.post(RECOVER, headers=HEADERS, json={"submissionId": SUBMISSION})
    assert response.status_code == 200, response.text
    assert response.json() == {"state": "accepted", "errorCode": None, "requiresManualRetry": False}
    assert "billing_entitlement" not in value.events and "fresh_mfa" not in value.events
    assert not value.mutation_authority.calls
    assert value.events.index("claim") < value.events.index("reference") < value.events.index("recovery_token")
    assert value.events[-2:] == ["discard", "release"]


def test_terminal_recovery_returns_stored_state_without_provider_or_new_release_gate():
    api, sessions = setup()
    sessions.value.submission = replace(sessions.value.submission, feedback_state="accepted")
    response = api.post(RECOVER, headers=HEADERS, json={"submissionId": SUBMISSION})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "accepted"
    assert "recovery_token" not in sessions.value.events and "fresh_mfa" not in sessions.value.events
    assert not sessions.value.mutation_authority.calls and not sessions.value.read_only_authority.calls
