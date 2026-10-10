from pathlib import Path
from importlib import import_module
from pydantic_settings import BaseSettings, SettingsConfigDict

global_config = import_module('07_servises.common.global_config')
hcm_globals = global_config.load_global_config('HCM')

def ms_to_s(value: int) -> int:
    return max(1, int(value) // 1000)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='HCM_', env_file='.env', extra='ignore')
    api_host: str = '0.0.0.0'
    api_port: int = hcm_globals.API_HCM_Port
    module_host: str = '0.0.0.0'
    module_port: int = hcm_globals.API_Module_Port
    update_port: int = hcm_globals.API_Update_Port
    database_url: str = 'postgresql://homecontrol:homecontrol-dev@127.0.0.1:5432/homecontrol'
    config_root: Path = Path('06_config')
    dev_mode: bool = hcm_globals.HCM_Dev_Mode
    tls_enabled: bool = hcm_globals.HCM_TLS_Enabled
    tls_cert: str | None = None
    tls_key: str | None = None
    tls_ca: str | None = None
    tls_require_client_cert: bool = hcm_globals.HCM_TLS_Require_Client_Cert
    commissioning_enabled: bool = hcm_globals.Commissioning_Enabled
    auth_rp_id: str = 'homecontrol.local'
    auth_challenge_ttl_s: int = ms_to_s(hcm_globals.Auth_Challenge_TTL)
    auth_session_ttl_s: int = ms_to_s(hcm_globals.Auth_Session_TTL)

settings = Settings()
