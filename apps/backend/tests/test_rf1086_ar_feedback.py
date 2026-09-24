"""Observed RF receipt shape with hostile identity and XML variations."""
import pytest

from talli_backend.modules.shareholder_register_filing.feedback import classify_rf1086_feedback

SUBMISSION = "01a0a376-44d7-7535-845a-322691b770c2"
ORGANIZATION = "310279617"
NAMESPACE = "urn:ske:fastsetting:innsamling:aksjonaeroppgave:ar_til_mag:v0_1"


def receipt():
    # Structural synthetic fixture derived from the 2026-09-15 provider receipt.
    # No contact or address fields are needed to exercise decision identity.
    return f'''<tilbakemelding xmlns="{NAMESPACE}">
      <magnetArInfo><innsendingsId>01a0a377-088d-767f-a638-83d7132fb20b</innsendingsId></magnetArInfo>
      <leveranse><oppgavegiver><organisasjonsnummer>{ORGANIZATION}</organisasjonsnummer></oppgavegiver>
      <inntektsaar>2025</inntektsaar><leveranseoppsummering>
      <leveransestatus>godkjent</leveransestatus><vaarLeveransereferanse>AKRE22100</vaarLeveransereferanse>
      </leveranseoppsummering></leveranse></tilbakemelding>'''


def classify(xml=None, **overrides):
    context = dict(forsendelse_id=SUBMISSION, income_year=2025,
        organization_number=ORGANIZATION, related_forsendelse_id=SUBMISSION)
    context.update(overrides)
    return classify_rf1086_feedback((xml if xml is not None else receipt()).encode(), **context)


def test_verified_relation_and_exact_company_year_accept_observed_receipt_shape():
    result = classify()
    assert (result.classification, result.schema, result.transmission_id) == (
        "accepted", "aksjonaeroppgave-ar-til-mag-v0_1", None)


def test_negative_decision_and_unknown_status():
    assert classify(receipt().replace("godkjent", "avvist")).classification == "rejected"
    assert classify(receipt().replace("godkjent", "mottatt")).classification == "action_required"


@pytest.mark.parametrize("context", [
    {"forsendelse_id": True, "related_forsendelse_id": 1},
    {"forsendelse_id": ["id"], "related_forsendelse_id": ["id"]},
    {"forsendelse_id": "id", "related_forsendelse_id": "id"},
    {"forsendelse_id": 1, "related_forsendelse_id": 1},
    {"organization_number": None}, {"organization_number": "999999999"},
    {"organization_number": 310279617}, {"income_year": 2024},
    {"related_forsendelse_id": None}, {"related_forsendelse_id": "another-submission"},
    {"related_forsendelse_id": "01a0a377-088d-767f-a638-83d7132fb20b"},
])
def test_missing_or_mismatched_identity_fails_closed(context):
    assert classify(**context).classification == "action_required"


@pytest.mark.parametrize("xml", [
    receipt().replace("<inntektsaar>2025</inntektsaar>", ""),
    receipt().replace(f"<organisasjonsnummer>{ORGANIZATION}</organisasjonsnummer>", ""),
    receipt().replace("</oppgavegiver>", f"<organisasjonsnummer>{ORGANIZATION}</organisasjonsnummer></oppgavegiver>"),
    receipt().replace("</leveranseoppsummering>", "<leveransestatus>godkjent</leveransestatus></leveranseoppsummering>"),
    receipt().replace("</tilbakemelding>", "<leveranse/></tilbakemelding>"),
    receipt().replace("</leveranse>", "<oppgavegiver/></leveranse>"),
    receipt().replace("</leveranse>", "<leveranseoppsummering/></leveranse>"),
    receipt().replace("<leveranse>", "<wrapper><leveranse>").replace("</leveranse>", "</leveranse></wrapper>"),
    receipt().replace("<organisasjonsnummer>", '<organisasjonsnummer xmlns="urn:foreign">'),
    receipt().replace(ORGANIZATION, "<![CDATA[310279617]]>"),
    receipt().replace("godkjent", "<nested>godkjent</nested>"),
    receipt().replace("godkjent", "<![CDATA[godkjent]]>"),
    receipt().replace("</tilbakemelding>", f"<innsending><forsendelseid>{SUBMISSION}</forsendelseid></innsending></tilbakemelding>"),
    '<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///does-not-exist">]>' + receipt(),
    receipt().replace("</tilbakemelding>", "<x>" * 65 + "</x>" * 65 + "</tilbakemelding>"),
    receipt().replace("</tilbakemelding>", ""),
])
def test_ambiguous_or_hostile_xml_never_accepts(xml):
    assert classify(xml).classification == "action_required"


def test_namespace_prefix_and_numeric_entity_are_semantically_equivalent():
    import re
    xml = re.sub(r"<(\/?)(\w+)", r"<\1rf:\2", receipt()).replace('xmlns="', 'xmlns:rf="')
    assert classify(xml.replace("godkjent", "godkj&#101;nt")).classification == "accepted"


def test_unbound_current_archive_call_does_not_gain_acceptance():
    result = classify_rf1086_feedback(receipt().encode(), forsendelse_id=SUBMISSION, income_year=2025)
    assert result.classification == "action_required"
