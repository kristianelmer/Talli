"""Actual RF workspace HTTP projection over synthetic retained feedback rows."""
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/backend/src"), str(ROOT / "apps/backend/tests")]
from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
from talli_backend.modules.shareholder_register_filing.public import Rf1086FeedbackArtifactRecord, Rf1086WorkspaceSnapshot
from talli_backend.shared.kernel import CompanyId, IncomeYear
from test_shareholder_register_filing_api import setup, BASE, HEADERS, COMPANY, SUBMISSION

rows = [
    {"id": str(uuid4()), "company_id": COMPANY, "submission_id": SUBMISSION,
     "document_id": str(uuid4()), "content_type": "application/xml", "byte_length": 17,
     "sha256": digest * 64, "retrieved_at": "2026-09-24T08:00:00Z", "classification": "accepted",
     "authority_reference": reference}
    for digest, reference in (("a", "talli:rf1086-feedback-provenance:v1"), ("b", str(uuid4())))
]
api, sessions = setup()
sessions.value.workspace_result = Rf1086WorkspaceSnapshot(
    CompanyId(COMPANY), IncomeYear(2025), feedback_artifacts=tuple(
        PostgresShareholderRegisterFilingSession._wire_record(Rf1086FeedbackArtifactRecord, row) for row in rows
    ),
)
response = api.get(BASE + f"/workspace?companyId={COMPANY}&incomeYear=2025", headers=HEADERS)
assert response.status_code == 200, response.text
print(json.dumps({"accepted": response.json(), "retained": rows}))
