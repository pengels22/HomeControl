"""Internal test provider. No network, credentials, timers or output bindings."""
from pydantic import BaseModel, ConfigDict
from .provider import Provider, ProviderInfo, Diagnostics
from .factory import provider_factory


class PingArguments(BaseModel):
    model_config=ConfigDict(extra='forbid')


class MockProvider(Provider):
    info=ProviderInfo('internal_mock','Internal Test Provider',capabilities={
        'devices':True,'entities':True,'states':True,'events':True,'services':True,
        'reload':True,'physical_control':False,
    }, config_schema={'type':'object','properties':{'host':{'type':'string'},'port':{'type':'integer','minimum':1}},'additionalProperties':False},
    config_flow={'type':'api_key','fields':[{'name':'host','type':'text','required':True},{'name':'port','type':'number'}], 'credential_kinds':['api_key']},
    description='Internal provider for configuration tests',setup_type='api_key',supports_multiple=True,internal=True)

    def __init__(self):
        self.context=None
        self.running=False
        self.fail_health=False
        self.updates=0

    def config_schema(self):
        return {'type':'object','properties':{'host':{'type':'string'},'port':{'type':'integer','minimum':1}},'additionalProperties':False}

    def config_flow(self):
        return {'type':'api_key','fields':[{'name':'host','type':'text','required':True},{'name':'port','type':'number'}], 'credential_kinds':['api_key']}

    async def validate_config(self, config):
        if not config.get('host'): raise ValueError('Host is required')
        if 'port' in config and (not isinstance(config['port'],int) or config['port']<1): raise ValueError('Port is invalid')
        return True

    async def validate_credentials(self, credentials):
        if not isinstance(credentials,str) or len(credentials)<4: raise ValueError('API key is invalid')
        return True

    async def oauth_exchange(self, code):
        if code != 'mock-code': raise ValueError('OAuth authorization failed')
        return {'access_token':'mock-access-token','refresh_token':'mock-refresh-token','expires_in':3600}

    async def setup(self,context):
        self.context=context
        self.device_id=await context.device('test_device','Internal Test Device',available=False)
        self.entity_id=await context.entity('temperature','sensor.internal_mock_temperature',self.device_id,
                                            'Internal Test Temperature',unit='°F',device_class='temperature')
        await context.service('internal_mock','ping',PingArguments,self.ping)

    async def start(self):
        self.running=True
        await self.context.device('test_device','Internal Test Device',available=True)
        await self.update(70.0)
        await self.context.emit('internal_mock.started',{'mock':True},entity_id=self.entity_id)

    async def update(self,value):
        await self.context.state(self.entity_id,value,attributes={'mock':True})
        self.updates+=1

    async def ping(self,arguments,target):
        return {'ok':True,'mock':True}

    async def stop(self):
        self.running=False

    async def health_check(self):
        if self.fail_health:
            raise RuntimeError('deliberate mock health failure')
        return self.running

    async def diagnostics(self):
        return Diagnostics(counters={'state_updates':self.updates},checks={'running':self.running})

if 'internal_mock' not in provider_factory.types:
    provider_factory.register_type('internal_mock',MockProvider.info,lambda context: MockProvider())
