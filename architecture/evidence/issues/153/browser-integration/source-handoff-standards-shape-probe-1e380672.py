import json
from contextlib import asynccontextmanager
from dataclasses import replace
from fastapi.testclient import TestClient
from test_annual_accounts_source_facts import source,parse
from talli_backend.modules.annual_accounts_filing.public import project_annual_accounts_source
from talli_backend.main import create_app
results=[]
for value in [None,[],["document-reference"],"document-reference",{"document-reference":"unexpected"},0]:
    raw=source();raw["workspace"]["submissions"][0]["feedback_document_ids"]=value
    query,snapshot=parse(raw);facts=project_annual_accounts_source(query,snapshot)
    class Sessions:
        actor_id=query.actor_id
        async def session(self,token):return self
        @asynccontextmanager
        async def transaction(self,*,snapshot=False):yield self
        async def filing_source_snapshot(self,selected):return globals()["snapshot"]
    client=TestClient(create_app(annual_accounts_session_factory=Sessions()))
    response=client.get(f"/api/v1/annual-accounts/source-facts?companyId={query.company_id}&incomeYear={int(query.income_year)}",headers={"Authorization":"Bearer synthetic"})
    results.append({"input":value,"historyCoverage":facts.history_coverage.status,"projected":facts.recorded_submissions[0].feedback_document_ids,"httpStatus":response.status_code,"wire":response.json()["recordedSubmissions"][0]["feedbackDocumentIds"] if response.status_code==200 else response.text})
print(json.dumps(results,indent=2))
