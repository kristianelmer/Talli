"""Dialog discovery uses exact identities and only the fixed service endpoint."""
import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from talli_backend.adapters.maskinporten import MaskinportenAccessToken, SYSTEM_USER_DIALOGPORTEN_SCOPE
from talli_backend.adapters.rf1086_dialogporten import Rf1086DialogportenAdapter
from talli_backend.modules.shareholder_register_filing.public import Rf1086AuthorityError

DIALOG = "019f5fce-2119-7570-a78b-db0a9b0a5c1f"
SUBMISSION = "01a0a376-44d7-7535-845a-322691b770c2"
ACCEPTANCE = "01a0a378-9500-73e4-acaa-5c06d5eb3293"
XML = "01a0a378-95af-711f-a4d4-ec368b0a1992"
ORG = "310279617"


def dialog():
    return {"id": DIALOG, "party": "urn:altinn:organization:identifier-no:" + ORG,
        "serviceResource": "urn:altinn:resource:ske-innrapportering-aksjonaerregisteroppgave",
        "transmissions": [
            {"id": SUBMISSION, "type": "Submission", "isAuthorized": True},
            {"id": ACCEPTANCE, "relatedTransmissionId": SUBMISSION, "type": "Acceptance",
             "isAuthorized": True, "createdAt": "2026-09-15T05:09:44.935459+00:00",
             "attachments": [{"id": ACCEPTANCE}, {"id": XML}]}]}


def run(data=None, *, response=None, **context):
    seen = []
    def transport(request):
        seen.append(request)
        assert request.method == "GET"
        assert str(request.url) == "https://platform.tt02.altinn.no/dialogporten/api/v1/enduser/dialogs/" + DIALOG
        assert request.headers["authorization"] == "Bearer local-dialog-token"
        return response if response is not None else httpx.Response(200, json=data if data is not None else dialog())
    token = MaskinportenAccessToken("local-dialog-token", "Bearer", 120, SYSTEM_USER_DIALOGPORTEN_SCOPE, "test")
    adapter = Rf1086DialogportenAdapter(token, environment="test", transport=httpx.MockTransport(transport))
    values = dict(organization_number=ORG, dialog_id=DIALOG, forsendelse_id=SUBMISSION)
    values.update(context)
    result = asyncio.run(adapter.read_feedback_transmissions(**values))
    assert len(seen) == 1
    return result


def test_observed_dialog_relationship_and_exact_attachment_ids():
    result, = run()
    assert (result.dialog_id, result.transmission_id, result.related_forsendelse_id,
        result.document_ids) == (DIALOG, ACCEPTANCE, SUBMISSION, (ACCEPTANCE, XML))


def test_untrusted_presentation_urls_and_actor_text_never_escape_or_get_followed():
    data = dialog()
    data.update(dialogToken="sensitive", content={"title": "private narrative"})
    data["transmissions"][1]["attachments"][1]["urls"] = [{"url": "https://attacker.invalid/secret"}]
    result = run(data)
    assert "sensitive" not in repr(result) and "attacker" not in repr(result) and "narrative" not in repr(result)


def test_no_related_feedback_is_pending_extent():
    data = dialog()
    data["transmissions"].pop()
    assert run(data) == ()


@pytest.mark.parametrize("field,value", [
    ("id", XML), ("party", "urn:altinn:organization:identifier-no:999999999"),
    ("serviceResource", "urn:altinn:resource:other"), ("deletedAt", "2026-09-15T00:00:00Z"),
    ("excludedTransmissions", [{}]), ("excludedTransmissions", False),
    ("transmissions", None), ("transmissions", []),
])
def test_dialog_identity_and_extent_fail_closed(field, value):
    data = dialog()
    data[field] = value
    with pytest.raises(Rf1086AuthorityError):
        run(data)


@pytest.mark.parametrize("field,value", [
    ("type", "unknown"), ("type", {}), ("type", None),
    ("relatedTransmissionId", False), ("relatedTransmissionId", "not-uuid"),
    ("id", "../../secret"), ("id", SUBMISSION), ("isAuthorized", False),
    ("isAuthorized", 1), ("deletedAt", "2026-09-15T00:00:00Z"),
    ("excludedAttachments", [{}]), ("excludedAttachments", False),
    ("attachments", None), ("attachments", [{"id": XML}, {"id": XML}]),
    ("attachments", [{"id": XML, "isAuthorized": 1}]),
    ("attachments", [{"id": XML, "isAuthorized": False}]),
    ("attachments", [{"id": "https://attacker.invalid"}]),
    ("createdAt", "2026-09-15T05:09:44"), ("createdAt", None),
])
def test_related_transmission_and_attachment_checks(field, value):
    data = dialog()
    data["transmissions"][1][field] = value
    with pytest.raises(Rf1086AuthorityError):
        run(data)


@pytest.mark.parametrize("status", [302, 400, 401, 403, 404, 429, 500])
def test_http_failure_has_closed_diagnostics_and_no_redirect(status):
    with pytest.raises(Rf1086AuthorityError) as error:
        run(response=httpx.Response(status, text="local-dialog-token private body",
            headers={"location": "https://attacker.invalid"}))
    assert "private" not in str(error.value) and "local-dialog-token" not in str(error.value)


@pytest.mark.parametrize("content", [b"{", b"[]", b'{"id":"a","id":"b"}',
    b'{"value":NaN}', b"x" * (2 * 1024 * 1024 + 1)])
def test_json_structure_duplicates_and_byte_bound(content):
    with pytest.raises(Rf1086AuthorityError):
        run(response=httpx.Response(200, content=content, headers={"content-type": "application/json"}))


def test_wrong_content_type_fails_closed():
    with pytest.raises(Rf1086AuthorityError):
        run(response=httpx.Response(200, text=json.dumps(dialog()), headers={"content-type": "text/html"}))


def test_every_related_transmission_is_returned_for_later_conflict_checks():
    data = dialog()
    rejection = deepcopy(data["transmissions"][1])
    rejection.update(id=XML, type="Rejection")
    data["transmissions"].append(rejection)
    assert len(run(data)) == 2


def test_unrelated_transmission_is_not_mistaken_for_current_feedback():
    data = dialog()
    data["transmissions"][1]["relatedTransmissionId"] = XML
    assert run(data) == ()


def test_deleted_original_submission_cannot_bind_feedback():
    data = dialog()
    data["transmissions"][0]["deletedAt"] = "2026-09-15T00:00:00Z"
    with pytest.raises(Rf1086AuthorityError):
        run(data)
