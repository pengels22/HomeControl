"""Provider type registry; constructors are registered by provider packages."""
from dataclasses import dataclass

@dataclass
class ProviderType:
    info: object
    factory: object

class ProviderFactory:
    def __init__(self): self.types={}
    def register_type(self,provider_id,metadata,factory):
        if provider_id in self.types: raise ValueError('Provider type already registered')
        self.types[provider_id]=ProviderType(metadata,factory)
    def create(self,provider_id,context):
        try: return self.types[provider_id].factory(context)
        except KeyError: raise LookupError('Provider type unavailable') from None

provider_factory=ProviderFactory()
