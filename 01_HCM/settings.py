from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='HCM_', env_file='.env', extra='ignore')
    api_host: str = '0.0.0.0'
    api_port: int = 8080
    module_host: str = '0.0.0.0'
    module_port: int = 6501
    update_port: int = 6503
    database_url: str = 'postgresql://homecontrol:homecontrol-dev@127.0.0.1:5432/homecontrol'
    config_root: Path = Path('06_config')
    dev_mode: bool = False
    tls_enabled: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None
    tls_ca: str | None = None
    tls_require_client_cert: bool = True
    commissioning_enabled: bool = True
    auth_rp_id: str = 'homecontrol.local'
    auth_challenge_ttl_s: int = 300
    auth_session_ttl_s: int = 3600

settings = Settings()
