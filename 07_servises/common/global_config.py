import importlib.util
from pathlib import Path
from types import SimpleNamespace


class GlobalConfigError(ValueError):
    pass


COMPONENT_FILES = {
    'HCM': Path('06_config/01_HCM/global_var.py'),
    'SIM': Path('06_config/02_SIM/global_config_SIM.py'),
    'LCM': Path('06_config/03_LCM/global_config_LCM.py'),
    'RCM': Path('06_config/04_RCM/global_config_RCM.py'),
    'PNL': Path('06_config/05_PNL/global_config_PNL.py'),
    'RMC': Path('06_config/06_RMC/global_config_RMC.py'),
}


REQUIRED = {
    'HCM': {
        'Alarm_Contact_Debounce': (int, 0, 60000),
        'API_HCM_Port': (int, 1, 65535),
        'API_Module_Port': (int, 1, 65535),
        'API_Update_Port': (int, 1, 65535),
        'Auth_Challenge_TTL': (int, 1000, 3600000),
        'Auth_Password_PBKDF2_Iterations': (int, 100000, 1000000),
        'Auth_Session_TTL': (int, 1000, 86400000),
        'Commissioning_Enabled': (bool, None, None),
        'Fire_Contact_Debounce': (int, 0, 60000),
        'Fire_Input_Alarm_High': (bool, None, None),
        'Door_Open_Pulse': (int, 250, 10000),
        'Door_Open_Pulse_Min': (int, 0, 10000),
        'Door_Open_Pulse_Max': (int, 250, 60000),
        'HCM_Dev_Mode': (bool, None, None),
        'HCM_TLS_Enabled': (bool, None, None),
        'HCM_TLS_Require_Client_Cert': (bool, None, None),
        'Heartbeat_TCP_Port': (int, 1, 65535),
        'HVAC_Cool_Min_Run': (int, 0, 3600000),
        'HVAC_Cool_Restart_Lockout': (int, 0, 3600000),
        'HVAC_Damper_Lead': (int, 0, 60000),
        'HVAC_Deadband_F': ((int, float), 0, 20),
        'HVAC_Default_Setpoint_F': ((int, float), 45, 90),
        'HVAC_Fan_Lead': (int, 0, 60000),
        'HVAC_Fan_Postrun': (int, 0, 3600000),
        'HVAC_Heat_Min_Run': (int, 0, 3600000),
        'HVAC_Heat_Restart_Lockout': (int, 0, 3600000),
        'Safety_Aux_Relay_Pulse': (int, 0, 60000),
        'Updater_Module_Poll_Interval': (int, 1, 60000),
        'Updater_Module_Return_Timeout': (int, 1, 3600000),
    },
    'SIM': {
        'CAN_Bitrate': (int, 1, 1000000),
        'Hexa_12V_Restart_Off_Time': (int, 0, 60000),
        'Module_Connect_Backoff_Initial': (int, 0, 60000),
        'Module_Connect_Backoff_Max': (int, 1, 300000),
        'Safety_Fail_Safe_On_Unknown': (bool, None, None),
    },
    'LCM': {
        'Lighting_Default_Fade_Steps': (int, 1, 1000),
        'Lighting_Default_Fade_Time': (int, 0, 60000),
        'Lighting_Dimmer_Max_Percent': (int, 0, 100),
        'Lighting_Dimmer_Min_Percent': (int, 0, 100),
        'Safety_Fail_Safe_On_Unknown': (bool, None, None),
    },
        'RCM': {
        'Module_Connect_Backoff_Initial': (int, 0, 60000),
        'Module_Connect_Backoff_Max': (int, 1, 300000),
        'Safety_Fail_Safe_On_Unknown': (bool, None, None),
        'RCM_Default_Relay_On': (bool, None, None),
        'RCM_Relay_Count': (int, 1, 32),
    },
    'PNL': {
        'Module_Connect_Backoff_Initial': (int, 0, 60000),
        'Module_Connect_Backoff_Max': (int, 1, 300000),
        'Panel_Auto_Refresh_Interval': (int, 1, 300000),
        'Panel_Default_Brightness': (int, 0, 100),
        'Panel_Require_Authentication': (bool, None, None),
        'Web_Enabled': (bool, None, None),
    },
    'RMC': {
        'CAN_Bitrate': (int, 1, 1000000),
        'Heartbeat_Interval': (int, 1, 300000),
        'RMC_Firmware_Block_Size': (int, 1, 4),
        'Sensor_Retry_Interval': (int, 1, 300000),
        'Serial_Baud': (int, 1, 1000000),
        'Telemetry_Interval': (int, 1, 300000),
    },
}


class LoadedGlobalConfig(SimpleNamespace):
    def as_dict(self):
        return {
            key: value
            for key, value in self.__dict__.items()
            if not key.startswith('_') and key not in ('component', 'path')
        }


def find_repo_root(start=None):
    current = Path(start or __file__).resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current] + list(current.parents):
        if (candidate / '06_config').is_dir():
            return candidate
    raise GlobalConfigError('could not locate repository root containing 06_config')


def _load_python_file(path):
    spec = importlib.util.spec_from_file_location('homecontrol_global_config_' + path.stem, str(path))
    if spec is None or spec.loader is None:
        raise GlobalConfigError('could not load global config spec for %s' % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        key: value
        for key, value in vars(module).items()
        if key and key[0].isupper() and not key.startswith('_')
    }


def _validate(component, values):
    required = REQUIRED.get(component, {})
    missing = [name for name in required if name not in values]
    if missing:
        raise GlobalConfigError('%s global config missing required values: %s' % (component, ', '.join(sorted(missing))))
    for name, (expected_type, minimum, maximum) in required.items():
        value = values[name]
        if not isinstance(value, expected_type):
            if isinstance(expected_type, tuple):
                type_name = ' or '.join(t.__name__ for t in expected_type)
            else:
                type_name = expected_type.__name__
            raise GlobalConfigError('%s.%s must be %s' % (component, name, type_name))
        if minimum is not None and value < minimum:
            raise GlobalConfigError('%s.%s must be >= %s' % (component, name, minimum))
        if maximum is not None and value > maximum:
            raise GlobalConfigError('%s.%s must be <= %s' % (component, name, maximum))
    if component == 'HCM' and values['Door_Open_Pulse_Min'] > values['Door_Open_Pulse_Max']:
        raise GlobalConfigError('HCM door pulse min cannot exceed max')
    if component == 'HCM' and values['Heartbeat_TCP_Port'] != 6004:
        raise GlobalConfigError('HCM heartbeat TCP port must remain 6004')
    if component == 'LCM' and values['Lighting_Dimmer_Min_Percent'] > values['Lighting_Dimmer_Max_Percent']:
        raise GlobalConfigError('LCM dimmer min cannot exceed max')


def load_global_config(component, root=None):
    name = str(component).upper()
    if name not in COMPONENT_FILES:
        raise GlobalConfigError('unknown component %s' % component)
    repo_root = find_repo_root(root)
    path = repo_root / COMPONENT_FILES[name]
    if not path.exists():
        raise GlobalConfigError('missing global config file %s' % path)
    values = _load_python_file(path)
    _validate(name, values)
    cfg = LoadedGlobalConfig(**values)
    cfg.component = name
    cfg.path = str(path)
    return cfg
