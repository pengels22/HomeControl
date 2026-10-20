"""Small async JSON client with bounded responses and sanitized failures."""
import httpx

class ProviderHTTP:
    def __init__(self,*,timeout=10,max_bytes=2_000_000,transport=None):
        self.client=httpx.AsyncClient(timeout=timeout,transport=transport,follow_redirects=False)
        self.max_bytes=max_bytes
    async def json(self,method,url,*,headers=None,params=None,json_body=None):
        try:
            response=await self.client.request(method,url,headers=headers,params=params,json=json_body)
            if len(response.content)>self.max_bytes: raise RuntimeError('Provider response too large')
            if response.status_code>=400: raise RuntimeError(f'Provider HTTP {response.status_code}')
            return response.json(),response.status_code
        except httpx.TimeoutException: raise RuntimeError('Provider request timed out') from None
        except httpx.HTTPError: raise RuntimeError('Provider request failed') from None
    async def close(self): await self.client.aclose()
