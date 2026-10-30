"""Bounded loopback GET transport shared by the two read-only adapters."""
import asyncio
import httpx

from talli_backend.modules.company_tax_filing.public import CompanyTaxReturnAuthorityError


async def read_tax_loopback_original(origin,path,headers,response_types,*,transport=None):
    try:
        async with asyncio.timeout(5):
            async with httpx.AsyncClient(base_url=origin,timeout=5,follow_redirects=False,
                    trust_env=False,transport=transport) as client:
                async with client.stream('GET',path,headers=headers) as response:
                    media=response.headers.get('content-type','').split(';',1)[0].strip().lower()
                    if response.status_code!=200 or media not in response_types:raise ValueError()
                    chunks=[];size=0
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        size+=len(chunk)
                        if size>8*1024*1024:raise ValueError()
                        chunks.append(chunk)
                    raw=b''.join(chunks)
                    if not raw:raise ValueError()
        return raw,media
    except (httpx.HTTPError,TimeoutError,ValueError,TypeError,UnicodeError):
        raise CompanyTaxReturnAuthorityError('Finite Tax read response unavailable.',
            code='COMPANY_TAX_REHEARSAL_AUTHORITY_UNAVAILABLE') from None
