"""The private simulation prepares exact drafts but cannot become Corporate authority."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import hashlib
import json

import pytest

from talli_backend.application.annual_accounts_delivery_source import read_annual_accounts_delivery_source
from talli_backend.application.annual_accounts_delivery_workflow import AnnualAccountsDeliveryWorkflow, AccountsDeliveryState
from talli_backend.application.annual_accounts_delivery_workspace import AnnualAccountsDeliveryWorkspace
from talli_backend.application.private_preview_accounts_signoff import PrivatePreviewAccountsSignoff
from talli_backend.adapters.annual_accounts_schemas import PinnedAnnualAccountsSchemas
from talli_backend.adapters.preview_synthetic_accounts_signoff import (
    compose_preview_accounts_signoff, FLAG, PROJECT, COMPANY, DECISION, DECISION_SHA256, SOURCE_SHA256,
    UNSIGNED, CLOSED,
)
from talli_backend.modules.annual_accounts_filing.delivery import annual_accounts_source_is_synthetic
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError, AnnualAccountsDeliveryStage, AnnualAccountsDeliveryAction,
    decode_annual_accounts_delivery_draft,
    prepare_annual_accounts_delivery,
)
from talli_backend.shared.kernel import CorrelationId
from test_annual_accounts_delivery_source import QUERY, NOW, prepare, read, source_inputs
from test_annual_accounts_delivery_workflow import Harness
from test_annual_accounts_delivery_draft import delivery_snapshot
from test_annual_accounts_delivery_records import binding


def preview_environment():
    return dict(CLOSED) | {'VERCEL': '1', 'VERCEL_ENV': 'preview', 'VERCEL_TARGET_ENV': 'preview',
        'VERCEL_PROJECT_ID': 'prj_u28yRnkslspXi3LSEDQHvTz8EWCD',
        'SUPABASE_URL': 'https://' + PROJECT + '.supabase.co',
        'TALLI_LEDGER_DATABASE_URL': 'host=db.' + PROJECT + '.supabase.co user=postgres',
        'TALLI_PREVIEW_SYNTHETIC_REGISTRY_IDENTITY': json.dumps({'source': 'browser_test', 'org_number': '992803750'}),
        FLAG: json.dumps({'purpose': 'synthetic_accounts_draft_only_v1', 'companyId': COMPANY,
            'incomeYear': 2025, 'decisionId': DECISION, 'decisionSha256': DECISION_SHA256,
            'sourceSha256': SOURCE_SHA256, 'unsignedDocumentSha256': UNSIGNED,
            'expiresAt': (NOW + timedelta(hours=1)).isoformat()})}


@pytest.mark.parametrize('defect', ['production','wrong-project','wrong-db','provider-open','wrong-decision','long-window','expired'])
def test_composition_requires_exact_finite_designated_preview(defect):
    env = preview_environment()
    assert compose_preview_accounts_signoff(environment=env, now=lambda: NOW) is not None
    if defect == 'production':env['VERCEL_ENV'] = 'production'
    elif defect == 'wrong-project':env['SUPABASE_URL'] = 'https://other.supabase.co'
    elif defect == 'wrong-db':env['TALLI_LEDGER_DATABASE_URL'] = 'host=db.other.supabase.co user=postgres'
    elif defect == 'provider-open':env['TALLI_AUTHORITY_OPS_ENABLED'] = 'true'
    else:
        value = json.loads(env[FLAG])
        if defect == 'wrong-decision':value['decisionSha256'] = '0' * 64
        elif defect == 'long-window':value['expiresAt'] = (NOW + timedelta(days=2)).isoformat()
        else:value['expiresAt'] = (NOW - timedelta(seconds=1)).isoformat()
        env[FLAG] = json.dumps(value)
    with pytest.raises(ValueError, match='finite synthetic Preview scope'):
        compose_preview_accounts_signoff(environment=env, now=lambda: NOW)


def simulation_world():
    inputs, app, transaction = source_inputs()
    original = read(inputs, app).owning_snapshots['corporate']['readiness']
    transaction.list_snapshot = replace(transaction.list_snapshot,
        artifacts=transaction.list_snapshot.artifacts[:2], finalizations=())
    simulation = PrivatePreviewAccountsSignoff(str(QUERY.company_id), original['decision_id']['value'],
        original['decision_hash'], original['source_hash'], dict(original['generated_artifact_hashes']),
        NOW + timedelta(hours=1), lambda: NOW)
    return inputs, app, transaction, simulation


def source(inputs, app, simulation):
    return asyncio.run(read_annual_accounts_delivery_source(inputs, QUERY, corporate=app,
        correlation_id=CorrelationId('synthetic-accounts-source-test'), synthetic_signoff=simulation))


def test_simulated_signoff_retains_unsigned_provenance_and_prepares_only():
    inputs, app, _, simulation = simulation_world()
    current = source(inputs, app, simulation)
    assert annual_accounts_source_is_synthetic(current)
    corporate = current.owning_snapshots['corporate']
    assert corporate['readiness']['state'] == 'facts_approved'
    assert corporate['readiness']['finalized'] is False
    assert corporate['readiness']['annual_submission_ready'] is False
    assert corporate['readiness']['signed_artifact_hashes'] == {}
    assert corporate['snapshot']['finalizations'] == ()
    assert corporate['synthetic_signoff']['unsignedDocumentSha256'] == corporate['readiness']['generated_artifact_hashes']
    draft = prepare(current)
    assert decode_annual_accounts_delivery_draft(draft.canonical_json, draft.sha256) == draft
    workflow = AnnualAccountsDeliveryWorkflow(corporate=app, schemas=PinnedAnnualAccountsSchemas(), ports=object())
    state = AccountsDeliveryState(type('Stored', (), {'draft': draft})(), (), type('Inspection', (), {})())
    assert workflow.mutation_available(None, state, AnnualAccountsDeliveryStage.PREPARE) is False
    assert workflow.reconciliation_available(None, state) is False
    assert workflow.correction_refresh_available(None, state) is False


def test_workspace_exposes_one_synthetic_draft_and_provider_calls_stay_closed():
    inputs, app, _, simulation = simulation_world()
    harness = Harness()
    harness.inputs, harness.corporate = inputs, app
    harness.workflow = AnnualAccountsDeliveryWorkflow(corporate=app, schemas=harness.schemas,
        ports=harness.ports, synthetic_signoff=simulation)
    draft = prepare(source(inputs, app, simulation))
    _, harness.snapshot = delivery_snapshot(draft)
    workspace = AnnualAccountsDeliveryWorkspace(harness.workflow)
    first = replace(harness.snapshot, delivery_drafts=(), coverage=dict(harness.snapshot.coverage)
        | {'deliveryDraftCount': 0, 'deliveryDraftDigests': {}})
    harness.snapshot = first
    before = asyncio.run(workspace.read(harness, QUERY, correlation_id=CorrelationId('synthetic-workspace')))
    assert before['synthetic_signoff'] is True and before['preparation_available'] is True and before['rows'] == []
    _, harness.snapshot = delivery_snapshot(draft)
    after = asyncio.run(workspace.read(harness, QUERY, correlation_id=CorrelationId('synthetic-workspace')))
    assert after['synthetic_signoff'] is True and after['preparation_available'] is False
    assert len(after['rows']) == 1 and after['rows'][0]['synthetic_signoff'] is True
    assert after['rows'][0]['actions'] == []
    with pytest.raises(AnnualAccountsError):
        asyncio.run(harness.workflow.advance(harness, binding(draft), action=AnnualAccountsDeliveryAction.CREATE_INSTANCE,
            correlation_id=CorrelationId('synthetic-no-provider')))
    assert harness.requests == []


@pytest.mark.parametrize('defect', ['expired','stale','no-facts-approval','signed-artifact','altered-proof'])
def test_simulation_fails_closed_when_source_or_provenance_changes(defect):
    inputs, app, transaction, simulation = simulation_world()
    if defect == 'expired':
        simulation = replace(simulation, now=lambda: NOW + timedelta(hours=2))
    elif defect == 'stale':
        transaction.source_facts_changed = True
    elif defect == 'no-facts-approval':
        transaction.list_snapshot = replace(transaction.list_snapshot, events=())
    elif defect == 'signed-artifact':
        from talli_backend.modules.corporate_governance.public import CorporateArtifactVariant
        artifacts = transaction.list_snapshot.artifacts
        transaction.list_snapshot = replace(transaction.list_snapshot,
            artifacts=(*artifacts, replace(artifacts[0], variant=CorporateArtifactVariant.SIGNED_OWNER_ATTESTED)))
    if defect == 'altered-proof':
        draft = prepare(source(inputs, app, simulation))
        value = json.loads(draft.canonical_json)
        value['draft']['source']['owning_snapshots']['corporate']['synthetic_signoff']['statement'] = 'Signed by owner'
        from talli_backend.modules.annual_accounts_filing.delivery import annual_accounts_delivery_digest
        snapshots = value['draft']['source']['owning_snapshots']
        value['draft']['source']['upstream_sha256']['corporate'] = annual_accounts_delivery_digest(snapshots['corporate'])
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        with pytest.raises(ValueError):
            decode_annual_accounts_delivery_draft(raw, hashlib.sha256(raw.encode()).hexdigest())
    else:
        current = source(inputs, app, simulation)
        assert not annual_accounts_source_is_synthetic(current)
        with pytest.raises(AnnualAccountsError):
            prepare(current)
