"""Provider contract: implementations receive an ownership-scoped HCM context."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class ProviderInfo:
    provider_id: str
    display_name: str
    version: str = '1'
    capabilities: dict[str, bool] = field(default_factory=dict)
    config_schema: dict = field(default_factory=dict)
    config_flow: dict = field(default_factory=dict)


class Diagnostics(BaseModel):
    """Public diagnostics intentionally exclude arbitrary provider payloads/secrets."""
    model_config = ConfigDict(extra='forbid', strict=True)
    counters: dict[str, int] = {}
    checks: dict[str, bool] = {}


class Provider(ABC):
    info: ProviderInfo

    @abstractmethod
    async def setup(self, context):
        """Register owned resources without starting background work."""

    @abstractmethod
    async def start(self):
        """Begin delivering state/events."""

    @abstractmethod
    async def stop(self):
        """Release provider resources; safe after partially completed setup."""

    async def reload(self):
        await self.stop()
        await self.start()

    def config_schema(self):
        return {}

    def config_flow(self):
        return {'type': 'simple', 'fields': []}

    async def validate_config(self, config):
        return True

    async def validate_credentials(self, credentials):
        return True

    async def test_connection(self):
        return await self.health_check()

    @abstractmethod
    async def health_check(self) -> bool:
        """Return health; exceptions/timeouts are isolated by HCM."""

    @abstractmethod
    async def diagnostics(self) -> Diagnostics:
        """Return only public counters and boolean checks."""
