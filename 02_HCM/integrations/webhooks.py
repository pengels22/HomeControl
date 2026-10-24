"""Provider-neutral webhook admission hooks; no provider behavior is embedded."""
import hashlib, hmac, time
from collections import deque

class WebhookGuard:
    def __init__(self,provider_id,*,max_bytes=1024*1024,rate=60,window=60):
        self.provider_id=provider_id; self.max_bytes=max_bytes; self.rate=rate; self.window=window; self._seen={}; self._calls=deque()
    def verify(self,payload,signature,secret,nonce):
        if len(payload)>self.max_bytes: raise ValueError('Webhook payload too large')
        now=time.monotonic(); self._calls=deque(t for t in self._calls if now-t<self.window)
        if len(self._calls)>=self.rate: raise ValueError('Webhook rate limit exceeded')
        if nonce in self._seen and now-self._seen[nonce]<self.window: raise ValueError('Webhook replay rejected')
        expected=hmac.new(secret.encode(),payload,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,str(signature)): raise ValueError('Webhook authentication failed')
        self._seen[nonce]=now; self._calls.append(now)
        return {'provider_id':self.provider_id,'payload':payload}
