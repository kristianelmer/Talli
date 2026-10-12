"""Acquire the complete related receipt set before any durable artifact write."""
from __future__ import annotations

import json
import re
from xml.etree import ElementTree as ET

from .feedback import RF1086_MAX_ARCHIVE_SCAN_BYTES, classify_rf1086_feedback
from .production import _sha256
from .public import (
    Rf1086AuthorityError, Rf1086FeedbackDiscovery, Rf1086FeedbackTransmission,
    Rf1086ReadOnlyAuthority, Rf1086ReconciliationArtifact, Rf1086ReconciliationInput,
)


async def acquire_dialog_feedback(authority: Rf1086ReadOnlyAuthority, discovery: Rf1086FeedbackDiscovery,
        input: Rf1086ReconciliationInput) -> list[Rf1086ReconciliationArtifact]:
    if (not isinstance(input.organization_number, str) or not re.fullmatch(r"[0-9]{9}", input.organization_number)
            or not isinstance(input.dialog_id, str) or not input.dialog_id):
        raise Rf1086AuthorityError("RF1086_FEEDBACK_CONTEXT_REQUIRED", status=200)
    transmissions = await discovery.read_feedback_transmissions(organization_number=input.organization_number,
        dialog_id=input.dialog_id, forsendelse_id=input.forsendelse_id)
    if not isinstance(transmissions, tuple) or len(transmissions) > 1000:
        raise Rf1086AuthorityError("RF1086_FEEDBACK_EXTENT_INVALID", status=200)
    result = []
    provenance = ET.Element("rf1086FeedbackProvenance", {"version": "1",
        "organizationNumber": input.organization_number, "incomeYear": str(input.income_year),
        "dialogId": input.dialog_id, "submissionTransmissionId": input.forsendelse_id})
    processed_bytes = 0
    seen = set()
    for transmission in transmissions:
        if (not isinstance(transmission, Rf1086FeedbackTransmission)
                or transmission.dialog_id != input.dialog_id
                or transmission.related_forsendelse_id != input.forsendelse_id
                or transmission.transmission_id in seen or not transmission.document_ids
                or len(set(transmission.document_ids)) != len(transmission.document_ids)):
            raise Rf1086AuthorityError("RF1086_FEEDBACK_RELATIONSHIP_INVALID", status=200)
        seen.add(transmission.transmission_id)
        documents = []
        decisions = []
        for identifier in transmission.document_ids:
            document = await authority.get_document(income_year=input.income_year,
                forsendelse_id=transmission.transmission_id, document_id=identifier)
            if document.reference != identifier:
                raise Rf1086AuthorityError("RF1086_FEEDBACK_RELATIONSHIP_INVALID", status=200)
            processed_bytes += len(document.bytes)
            if processed_bytes > RF1086_MAX_ARCHIVE_SCAN_BYTES:
                raise Rf1086AuthorityError("RF1086_ARCHIVE_SCAN_LIMIT", status=200)
            documents.append(document)
            if document.content_type in {"application/xml", "text/xml"}:
                decisions.append(classify_rf1086_feedback(document.bytes,
                    forsendelse_id=input.forsendelse_id, income_year=input.income_year,
                    organization_number=input.organization_number,
                    related_forsendelse_id=transmission.related_forsendelse_id).classification)
            elif document.content_type != "application/pdf" or not document.bytes.startswith(b"%PDF-"):
                decisions.append("action_required")
        decision = decisions[0] if decisions and len(set(decisions)) == 1 else "action_required"
        if (transmission.transmission_type not in {"Acceptance", "Rejection", "Decision"}
                or (transmission.transmission_type == "Acceptance" and decision == "rejected")
                or (transmission.transmission_type == "Rejection" and decision == "accepted")):
            decision = "action_required"
        transmission_manifest = ET.SubElement(provenance, "transmission", {
            "id": transmission.transmission_id, "relatedTransmissionId": transmission.related_forsendelse_id,
            "createdAt": transmission.created_at, "type": transmission.transmission_type})
        for document in documents:
            ET.SubElement(transmission_manifest, "attachment", {"id": document.reference,
                "sha256": _sha256(document.bytes), "contentType": document.content_type})
            # Retain exact discovery attribution in the existing metadata field.
            # Original provider bytes remain byte-for-byte unchanged.
            reference = json.dumps({"dialogId": transmission.dialog_id,
                "transmissionId": transmission.transmission_id,
                "relatedTransmissionId": transmission.related_forsendelse_id,
                "attachmentId": document.reference, "createdAt": transmission.created_at,
                "transmissionType": transmission.transmission_type,
                "organizationNumber": input.organization_number, "incomeYear": input.income_year},
                separators=(",", ":"))
            if len(reference) > 500:
                raise Rf1086AuthorityError("RF1086_FEEDBACK_RELATIONSHIP_INVALID", status=200)
            result.append(Rf1086ReconciliationArtifact(input.submission_id, input.company_id,
                reference, document.content_type, document.bytes, len(document.bytes),
                _sha256(document.bytes), decision))
    if result:
        # The existing store deduplicates bytes by SHA, so each relationship must
        # also survive independently of whichever attachment first stored them.
        provenance[:] = sorted(provenance, key=lambda item: item.attrib["id"])
        for item in provenance:
            item[:] = sorted(item, key=lambda attachment: attachment.attrib["id"])
        manifest = ET.tostring(provenance, encoding="utf-8", xml_declaration=True)
        if processed_bytes + len(manifest) > RF1086_MAX_ARCHIVE_SCAN_BYTES:
            raise Rf1086AuthorityError("RF1086_ARCHIVE_SCAN_LIMIT", status=200)
        decisions = {artifact.classification for artifact in result}
        classification = next(iter(decisions)) if len(decisions) == 1 else "action_required"
        result.append(Rf1086ReconciliationArtifact(input.submission_id, input.company_id,
            "talli:rf1086-feedback-provenance:v1", "application/xml", manifest, len(manifest),
            _sha256(manifest), classification))
    return result
