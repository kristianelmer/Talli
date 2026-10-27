"""Fixed Accounts paths and distinct finite system/person/read transports."""
import asyncio
import base64

import httpx

from talli_backend.application.annual_accounts_delivery_rehearsal import AccountsRehearsalRuntime
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsAuthorityPort as Port,AnnualAccountsDeliveryStage as Stage,AnnualAccountsDeliveryAction as Action,
    AnnualAccountsReadPurpose as Purpose,AnnualAccountsError,AnnualAccountsDeliveryOriginal as Original,
    AnnualAccountsDeliveryCompletion as Completion,AnnualAccountsDeliveryTransport,annual_accounts_authority_adapter,
)

_PATH='/brg/aarsregnskap-vanlig-202406/instances/'


class _LoopbackAccounts:
    role=None
    stage=None

    def __init__(self,runtime,*,transport=None):
        if (type(runtime) is not AccountsRehearsalRuntime or runtime.admission.port is not self.role
                or runtime.admission.stage is not self.stage):raise ValueError('Accounts finite port differs from its role.')
        self.runtime=runtime;self._transport=transport

    async def _request(self,method,path,*,body=None,media=None):
        headers=self.runtime.request_headers()
        headers['Accept-Encoding']='identity'
        if media is not None:headers['Content-Type']=media
        try:
            async with asyncio.timeout(5):
                async with httpx.AsyncClient(base_url=self.runtime.admission.origin,timeout=5,follow_redirects=False,
                        trust_env=False,transport=self._transport) as client:
                    async with client.stream(method,path,content=body,headers=headers) as response:
                        chunks=[];size=0
                        async for chunk in response.aiter_raw(chunk_size=65536):
                            size+=len(chunk)
                            if size>16*1024*1024:return None,None,None,'response_too_large'
                            chunks.append(chunk)
                        content_type=response.headers.get('content-type')
                        if content_type is not None and len(content_type)>8192:return None,None,None,'response_invalid'
                        return response.status_code,content_type,base64.b64encode(b''.join(chunks)).decode(),None
        except (TimeoutError,httpx.TimeoutException):return None,None,None,'timeout'
        except httpx.HTTPError:return None,None,None,'connection_lost'

    async def execute(self,request,review,draft):
        grant=self.runtime.admission;request.assert_draft(draft,review,grant)
        permitted=({Action.CREATE_INSTANCE,Action.UPLOAD_MAIN_FORM,Action.UPLOAD_COMPANY_ACCOUNTS} if self.stage is Stage.PREPARE
            else {Action.CONFIRM} if self.stage is Stage.CONFIRM else {Action.SIGN} if self.stage is Stage.SIGN else set())
        if request.action not in permitted:raise AnnualAccountsError.forbidden()
        result=await self._request(request.request_method,request.request_path,
            body=base64.b64decode(request.request_body_base64,validate=True),media=request.request_content_type)
        return Completion(request.binding,request.action,request.sha256,*result)

    async def read(self,*,purpose,instance_id,data_id=None):
        # The workflow supplies only the positively learned retained instance
        # and file IDs. Original's constructor also validates path identities.
        now=self.runtime.now()
        Original(purpose,instance_id,data_id,None,None,now,None,'response_invalid',now)
        grant=self.runtime.admission
        if grant.known_instance is not None and instance_id!=grant.known_instance:raise AnnualAccountsError.forbidden()
        path=_PATH+instance_id+('/validate' if purpose is Purpose.VALIDATION else '/data/'+data_id if data_id else '')
        status,media,body,failure=await self._request('GET',path)
        return Original(purpose,instance_id,data_id,media,body,self.runtime.now(),status,failure,now)


@annual_accounts_authority_adapter(AnnualAccountsDeliveryTransport)
class LoopbackAccountsSystemPreparation(_LoopbackAccounts):
    role=Port.SYSTEM_USER
    stage=Stage.PREPARE


@annual_accounts_authority_adapter(AnnualAccountsDeliveryTransport)
class LoopbackAccountsSystemConfirmation(_LoopbackAccounts):
    role=Port.SYSTEM_USER
    stage=Stage.CONFIRM


@annual_accounts_authority_adapter(AnnualAccountsDeliveryTransport)
class LoopbackAccountsPersonSigning(_LoopbackAccounts):
    role=Port.PERSON
    stage=Stage.SIGN


@annual_accounts_authority_adapter(AnnualAccountsDeliveryTransport)
class LoopbackAccountsKnownRead(_LoopbackAccounts):
    role=Port.KNOWN_READ
    stage=None
