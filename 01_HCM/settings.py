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
    tls_enabled: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None
    commissioning_enabled: bool = True

settings = Settings()
