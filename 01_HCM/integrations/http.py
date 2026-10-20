"""Small async JSON client with bounded responses and sanitized failures."""
import httpx
from dataclasses import dataclass

@dataclass
class ProviderHTTPError(RuntimeError):
    category: str
    status_code: int|None=None
    def __str__(self): return self.category

class ProviderHTTP:
    def __init__(self,*,timeout=10,max_bytes=2_000_000,transport=None):
        self.client=httpx.AsyncClient(timeout=timeout,transport=transport,follow_redirects=False)
        self.max_bytes=max_bytes
    async def json(self,method,url,*,headers=None,params=None,json_body=None,form_body=None):
        try:
            response=await self.client.request(method,url,headers=headers,params=params,json=json_body,data=form_body)
            if len(response.content)>self.max_bytes: raise RuntimeError('Provider response too large')
            if response.status_code==401: raise ProviderHTTPError('authentication',401)
            if response.status_code==403: raise ProviderHTTPError('authorization',403)
            if response.status_code==429: raise ProviderHTTPError('rate_limited',429)
            if response.status_code>=500: raise ProviderHTTPError('provider_error',response.status_code)
            if response.status_code>=400:
                try:
                    detail=response.json()
                    if isinstance(detail,dict) and detail.get('error') in {'invalid_grant','invalid_client'}:
                        raise ProviderHTTPError('authentication',response.status_code)
                except ValueError: pass
                raise ProviderHTTPError('provider_error',response.status_code)
            return response.json(),response.status_code
        except httpx.TimeoutException: raise ProviderHTTPError('timeout') from None
        except httpx.HTTPError: raise ProviderHTTPError('network') from None
    async def close(self): await self.client.aclose()
