"""Complete PDF/XML discovery and persistence through the canonical RF owner."""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from talli_backend.adapters.maskinporten import MaskinportenAccessToken, SYSTEM_USER_DIALOGPORTEN_SCOPE, SYSTEM_USER_TAX_SCOPE
from talli_backend.adapters.rf1086_authority import Rf1086ReadOnlyAuthorityAdapter
from talli_backend.adapters.rf1086_dialogporten import Rf1086DialogportenAdapter
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086FeedbackArtifactPersistenceError, Rf1086ReconciliationInput,
    reconcile_journaled_rf1086_production,
)
from test_rf1086_ar_feedback import receipt
from test_rf1086_dialogporten import ACCEPTANCE, DIALOG, ORG, SUBMISSION, XML, dialog
from test_shareholder_register_filing_production import FeedbackJournal

INPUT = Rf1086ReconciliationInput("local-submission", "local-company", 2025, SUBMISSION,
    "<submitted-main/>", {"shareholder": "<submitted-under/>"}, ORG, DIALOG)


def run(*, data=None, documents=None, journal=None, input=INPUT):
    seen = []
    data = dialog() if data is None else data
    documents = documents if documents is not None else {
        ACCEPTANCE: ("application/pdf", b"%PDF-1.7 synthetic companion"),
        XML: ("application/xml", receipt().encode()),
    }
    def transport(request):
        seen.append((request.method, str(request.url)))
        assert request.method == "GET"
        if request.url.host == "platform.tt02.altinn.no":
            assert request.headers["authorization"] == "Bearer local-dialog-token"
            return httpx.Response(200, json=data)
        assert request.url.host == "api-test.sits.no"
        assert request.headers["authorization"] == "Bearer local-rf-token"
        identifier = request.url.path.rsplit("/", 1)[1]
        assert "/forsendelser/" + ACCEPTANCE + "/dokumenter/" in request.url.path
        value = documents[identifier]
        if isinstance(value, Exception):
            raise value
        kind, raw = value
        return httpx.Response(200, content=raw, headers={"content-type": kind})
    network = httpx.MockTransport(transport)
    discovery = Rf1086DialogportenAdapter(MaskinportenAccessToken("local-dialog-token", "Bearer", 120,
        SYSTEM_USER_DIALOGPORTEN_SCOPE, "test"), environment="test", transport=network)
    authority = Rf1086ReadOnlyAuthorityAdapter(MaskinportenAccessToken("local-rf-token", "Bearer", 120,
        SYSTEM_USER_TAX_SCOPE, "test"), environment="test", transport=network)
    journal = journal if journal is not None else FeedbackJournal("processing")
    result = asyncio.run(reconcile_journaled_rf1086_production(journal, authority, input,
        discovery=discovery, initial_poll=False))
    return result, journal, seen


def test_related_pdf_and_xml_are_both_durable_before_final_acceptance():
    result, journal, seen = run()
    assert result.state == "accepted" and result.artifact_count == 3 and len(seen) == 3
    assert len(journal.events) == 1 and journal.events[0].state == "accepted"
    for artifact in journal.artifacts.values():
        if artifact.authority_reference == "talli:rf1086-feedback-provenance:v1":
            continue
        reference = json.loads(artifact.authority_reference)
        assert reference["dialogId"] == DIALOG and reference["transmissionId"] == ACCEPTANCE
        assert reference["relatedTransmissionId"] == SUBMISSION and reference["organizationNumber"] == ORG
        assert reference["createdAt"] == "2026-09-15T05:09:44.935459+00:00"


def test_rejection_xml_controls_companion_classification():
    data = dialog()
    data["transmissions"][1]["type"] = "Rejection"
    result, journal, _ = run(data=data, documents={ACCEPTANCE: ("application/pdf", b"%PDF-1.7 receipt"),
        XML: ("application/xml", receipt().replace("godkjent", "avvist").encode())})
    assert result.state == "rejected" and {a.classification for a in journal.artifacts.values()} == {"rejected"}


def test_pdf_without_xml_cannot_finalize():
    data = dialog()
    data["transmissions"][1]["attachments"] = [{"id": ACCEPTANCE}]
    result, journal, _ = run(data=data)
    assert result.state == "action_required" and result.artifact_count == 2


@pytest.mark.parametrize("xml", [receipt().replace(ORG, "999999999"),
    receipt().replace("2025", "2024"), receipt().replace("godkjent", "unknown"),
    receipt().replace("</leveranseoppsummering>", "<leveransestatus>avvist</leveransestatus></leveranseoppsummering>")])
def test_invalid_companion_never_gives_pdf_acceptance(xml):
    result, journal, _ = run(documents={ACCEPTANCE: ("application/pdf", b"%PDF-1.7 receipt"),
        XML: ("application/xml", xml.encode())})
    assert result.state == "action_required" and all(a.classification == "action_required" for a in journal.artifacts.values())


def test_late_document_failure_prevents_all_artifact_writes():
    result, journal, _ = run(documents={ACCEPTANCE: ("application/pdf", b"%PDF-1.7 receipt"),
        XML: httpx.ReadError("private network error")})
    assert result.state == "unknown" and not journal.artifacts


def test_second_xml_conflict_prevents_final_acceptance():
    data = dialog()
    data["transmissions"][1]["attachments"].append({"id": DIALOG})
    documents = {ACCEPTANCE: ("application/pdf", b"%PDF-1.7 receipt"),
        XML: ("application/xml", receipt().encode()),
        DIALOG: ("application/xml", receipt().replace("godkjent", "avvist").encode())}
    result, journal, _ = run(data=data, documents=documents)
    assert result.state == "action_required" and len(journal.artifacts) == 4


def test_persistence_failure_cannot_record_final_decision():
    result, journal, _ = run(journal=FeedbackJournal(failure=Rf1086FeedbackArtifactPersistenceError(retryable=True)))
    assert result.state == "unknown" and not journal.artifacts


def test_context_required_before_provider_request():
    result, journal, seen = run(input=replace(INPUT, organization_number=None))
    assert result.state == "action_required" and not seen and not journal.artifacts


def test_no_feedback_yet_remains_processing():
    data = dialog()
    data["transmissions"].pop()
    result, journal, seen = run(data=data)
    assert result.state == "processing" and len(seen) == 1 and not journal.artifacts


def test_replay_keeps_original_document_hashes_and_event_identity():
    first, journal, _ = run()
    second, journal, _ = run(journal=journal)
    assert first.artifact_hashes == second.artifact_hashes and not second.changed
    assert len(journal.artifacts) == 3 and len(journal.events) == 1


def test_identical_bytes_keep_all_attachment_attribution_in_durable_manifest():
    from xml.etree import ElementTree
    data = dialog()
    data["transmissions"][1]["attachments"].append({"id": DIALOG})
    raw = receipt().encode()
    result, journal, _ = run(data=data, documents={ACCEPTANCE: ("application/pdf", b"%PDF-1.7 receipt"),
        XML: ("application/xml", raw), DIALOG: ("application/xml", raw)})
    assert result.state == "accepted" and len(journal.artifacts) == 3
    manifests = [a for a in journal.artifacts.values() if a.authority_reference == "talli:rf1086-feedback-provenance:v1"]
    manifest, = manifests
    entries = ElementTree.fromstring(manifest.bytes).findall("transmission/attachment")
    assert {a.attrib["id"] for a in entries} == {ACCEPTANCE, XML, DIALOG}
    hashes = {a.attrib["id"]: a.attrib["sha256"] for a in entries}
    assert hashes[XML] == hashes[DIALOG]


def test_manifest_is_order_independent_and_failure_to_store_it_blocks_final_decision():
    data = dialog()
    data["transmissions"][1]["attachments"].reverse()
    first, journal, _ = run()
    second, _, _ = run(data=data, journal=journal)
    assert first.artifact_hashes == second.artifact_hashes and not second.changed
    class ManifestFailure(FeedbackJournal):
        async def record_artifact(self, artifact):
            if artifact.authority_reference == "talli:rf1086-feedback-provenance:v1":
                raise Rf1086FeedbackArtifactPersistenceError(retryable=True)
            return await super().record_artifact(artifact)
    result, journal, _ = run(journal=ManifestFailure())
    assert result.state == "unknown" and len(journal.artifacts) == 2
    assert all(event.state != "accepted" for event in journal.events)


@pytest.mark.parametrize("kind,status", [("Rejection", "godkjent"), ("Acceptance", "avvist"),
    ("Information", "godkjent"), ("Alert", "godkjent"), ("Request", "godkjent"),
    ("Correction", "godkjent"), ("Submission", "godkjent")])
def test_category_conflicts_or_non_decision_categories_do_not_finalize(kind, status):
    data = dialog()
    data["transmissions"][1]["type"] = kind
    result, journal, _ = run(data=data, documents={ACCEPTANCE: ("application/pdf", b"%PDF-1.7 receipt"),
        XML: ("application/xml", receipt().replace("godkjent", status).encode())})
    assert result.state == "action_required" and len(journal.artifacts) == 3
