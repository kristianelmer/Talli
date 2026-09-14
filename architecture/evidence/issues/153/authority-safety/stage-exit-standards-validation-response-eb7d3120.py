"""Exact fixed HTTP adapter and public prepare contract, local MockTransport only."""
import asyncio,json,httpx
from test_authority_filing_transports import queue,annual_instance,ORG,XML,ALTINN_TOKEN
from talli_backend.adapters.annual_accounts_authority import AnnualAccountsTransport
from talli_backend.modules.annual_accounts_filing.public import prepare_annual_accounts_for_signing
async def main():
 results=[]
 for body in ('<html>upstream service failure</html>','{"validationIssues":"not-an-array"}','[]'):
  transport,requests,pending=queue(annual_instance(),httpx.Response(201),httpx.Response(201),httpx.Response(200,text=body),{'currentTask':{'altinnTaskType':'signing'}},annual_instance('signing'))
  result=await prepare_annual_accounts_for_signing(AnnualAccountsTransport(ALTINN_TOKEN,transport=transport),company_org_number=ORG,main_form_xml=XML,company_accounts_xml=XML)
  results.append({'validationBody':body,'hasErrors':result['validation']['hasErrors'],'lockPutCount':sum(r.method=='PUT' and r.url.path.endswith('/process/next') for r in requests),'receivedHandoff':bool(result['signingUrl']),'mode':'LOCAL_HTTPX_MOCK_TRANSPORT_NO_PROVIDER'})
 print(json.dumps(results,indent=2))
asyncio.run(main())
