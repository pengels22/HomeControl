from pathlib import Path
from importlib import import_module
from pydantic_settings import BaseSettings, SettingsConfigDict

global_config = import_module('07_servises.common.global_config')
hcm_globals = global_config.load_global_config('HCM')

def ms_to_s(value: int) -> int:
    return max(1, int(value) // 1000)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='HCM_', env_file='.env', extra='ignore')
    integration_mock_enabled: bool = False
    api_host: str = '0.0.0.0'
    api_port: int = hcm_globals.API_HCM_Port
    module_host: str = '0.0.0.0'
    module_port: int = hcm_globals.API_Module_Port
    update_port: int = hcm_globals.API_Update_Port
    update_request_secret_file: Path | None = Path('/etc/homecontrol/update-request.secret')
    database_url: str | None = None
    config_root: Path = Path('06_config')
    dev_mode: bool = hcm_globals.HCM_Dev_Mode
    tls_enabled: bool = hcm_globals.HCM_TLS_Enabled
    tls_cert: str | None = None
    tls_key: str | None = None
    tls_ca: str | None = None
    tls_require_client_cert: bool = hcm_globals.HCM_TLS_Require_Client_Cert
    module_cert_identity_required: bool = True
    allow_insecure_module_listener: bool = False
    commissioning_enabled: bool = hcm_globals.Commissioning_Enabled
    conflict_heartbeat_enabled: bool = True
    conflict_heartbeat_device_id: str = '3c53bbf7adb2'
    hcm_heartbeat_device_id: str = '48b02d87db16'
    conflict_heartbeat_host: str = '192.168.20.26'
    conflict_heartbeat_port: int = 6004
    conflict_heartbeat_interval_s: int = 5
    conflict_heartbeat_timeout_s: int = 15
    conflict_heartbeat_protocol: str = 'hcm-heartbeat-v3'
    conflict_heartbeat_auth_mode: str = 'hmac-sha256'
    conflict_heartbeat_auth_secret_file: Path | None = Path('/etc/hcm-heartbeat/heartbeat-auth.secret')
    lab1_device_id: str = '2ccf675d3414'
    lab1_hostname: str = 'lab1'
    lab1_ip_address: str = '192.168.20.36'
    auth_rp_id: str = 'homecontrol.local'
    auth_challenge_ttl_s: int = ms_to_s(hcm_globals.Auth_Challenge_TTL)
    auth_session_ttl_s: int = ms_to_s(hcm_globals.Auth_Session_TTL)
    host_network_status_file: Path | None = Path('/var/lib/homecontrol/.state/host-network-status.json')
    storage_root: Path = Path('/var/lib/homecontrol')
    safety_input_backend: str = 'linux'
    safety_input_wiring_file: Path = Path('/etc/hcm/safety-inputs.json')
    touchscreen_pin_lookup_secret_file: Path | None = Path('/etc/homecontrol/touchscreen-pin-lookup.secret')
    touchscreen_idle_timeout_s: int = 300
    touchscreen_absolute_timeout_s: int = 12 * 60 * 60
    touchscreen_rate_limit_base_s: int = 2
    touchscreen_rate_limit_max_s: int = 300

settings = Settings()
