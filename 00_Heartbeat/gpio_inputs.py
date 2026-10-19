"""Optional read-only GPIO inputs for the independent Conflict supervisor."""
import json
import time


class GPIOInputError(RuntimeError):
    pass


class DebouncedLevel:
    def __init__(self, debounce_ms=250):
        self.debounce_seconds = float(debounce_ms) / 1000.0
        self.candidate = None
        self.candidate_since = None
        self.stable = None

    def update(self, value, now=None):
        now = time.monotonic() if now is None else now
        if value is None:
            self.candidate = None
            self.candidate_since = None
            self.stable = None
            return None
        value = bool(value)
        if self.stable is None:
            if value != self.candidate:
                self.candidate = value
                self.candidate_since = now
                return None
            if self.candidate_since is not None and now - self.candidate_since >= self.debounce_seconds:
                self.stable = value
            return self.stable
        if value != self.candidate:
            self.candidate = value
            self.candidate_since = now
            return self.stable
        if value != self.stable and now - self.candidate_since >= self.debounce_seconds:
            self.stable = value
        return self.stable


def _load_manifest_signals(path):
    """Load the JSON-compatible YAML hardware manifest without PyYAML."""
    with open(path, encoding='utf-8') as stream:
        data = json.load(stream)
    signals = data.get('signals')
    if not isinstance(signals, dict):
        raise GPIOInputError('hardware profile has no signals mapping')
    for name in ('fire_alarm_s', 'fire_alarm_P'):
        entry = signals.get(name)
        if not isinstance(entry, dict) or int(entry.get('debounce_ms', 0)) != 250:
            raise GPIOInputError('invalid fire input manifest for {}'.format(name))
        if str(entry.get('normal_level')).lower() != 'low' or str(entry.get('alarm_level')).lower() != 'high':
            raise GPIOInputError('invalid polarity for {}'.format(name))
        if entry.get('wiring') != {'no': '3.3V', 'nc': 'GND', 'com': 'GPIO'}:
            raise GPIOInputError('invalid SPDT wiring for {}'.format(name))
    return signals


class GPIOInputMonitor:
    def __init__(self, config):
        self.config = config or {}
        profile = self.config.get('hardware_profile')
        if profile:
            self.config = dict(self.config)
            self.config.update(_load_manifest_signals(profile))
        self.enabled = bool(self.config.get('enabled', False))
        self.readers = {}
        debounce_ms = int(self.config.get('debounce_ms', 250))
        self.debouncers = {name: DebouncedLevel(debounce_ms) for name in ('fire_alarm_s', 'fire_alarm_P')}
        connected = self.config.get('connected_inputs', [])
        if not isinstance(connected, list) or not set(connected) <= set(self.debouncers):
            raise GPIOInputError('invalid connected_inputs')
        self.connected_inputs = connected
        if self.enabled:
            self._open()

    def _open(self):
        if not self.connected_inputs:
            return
        try:
            import gpiod
            from gpiod.line import Direction
            for name in self.connected_inputs:
                entry = self.config[name]
                line = int(entry['line'])
                self.readers[name] = (gpiod.request_lines(
                    entry['gpiochip'], consumer='homecontrol-fire-input',
                    config={line: gpiod.LineSettings(direction=Direction.INPUT)},
                ), line, int(entry.get('active_level', 1)))
        except Exception as exc:
            self.close()
            raise GPIOInputError('could not open configured GPIO inputs: {}'.format(exc))

    def read(self, now=None):
        if not self.enabled:
            return {name: {'state': 'unknown', 'health': 'disabled', 'fault': True} for name in ('fire_alarm_s', 'fire_alarm_P')}
        result = {name: {'state': 'unknown', 'health': 'unconfirmed_wiring', 'fault': True}
                  for name in self.debouncers if name not in self.readers}
        sampled_at = time.time()
        for name, (request, line, active_level) in self.readers.items():
            try:
                raw = request.get_value(line)
                raw_level = bool(getattr(raw, 'value', raw))
                stable = self.debouncers[name].update(raw_level, now)
                if stable is None:
                    result[name] = {'state': 'unknown', 'health': 'debouncing', 'raw': raw_level, 'sampled_at': sampled_at}
                elif name == 'fire_alarm_s':
                    result[name] = {'state': 'active' if stable == bool(active_level) else 'normal', 'health': 'ok', 'raw': raw_level, 'sampled_at': sampled_at}
                else:
                    result[name] = {'state': 'present' if stable == bool(active_level) else 'absent', 'health': 'ok', 'raw': raw_level, 'sampled_at': sampled_at}
            except Exception as exc:
                result[name] = {'state': 'unknown', 'health': 'fault', 'error': str(exc), 'sampled_at': sampled_at}
        return result

    def close(self):
        for request, _line, _active_level in self.readers.values():
            try:
                request.release()
            except Exception:
                pass
        self.readers = {}
