"""Optional read-only GPIO inputs for the independent Conflict supervisor."""
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


class GPIOInputMonitor:
    def __init__(self, config):
        self.config = config or {}
        self.enabled = bool(self.config.get('enabled', False))
        self.readers = {}
        debounce_ms = int(self.config.get('debounce_ms', 250))
        self.debouncers = {name: DebouncedLevel(debounce_ms) for name in ('fire_alarm_s', 'fire_alarm_P')}
        if self.enabled:
            self._open()

    def _open(self):
        try:
            import gpiod
            from gpiod.line import Direction
            for name in ('fire_alarm_s', 'fire_alarm_P'):
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
            return {name: {'state': 'unknown', 'health': 'disabled'} for name in ('fire_alarm_s', 'fire_alarm_P')}
        result = {}
        for name, (request, line, active_level) in self.readers.items():
            try:
                raw = request.get_value(line)
                raw_level = bool(getattr(raw, 'value', raw))
                stable = self.debouncers[name].update(raw_level, now)
                if stable is None:
                    result[name] = {'state': 'unknown', 'health': 'debouncing', 'raw': raw_level}
                elif name == 'fire_alarm_s':
                    result[name] = {'state': 'active' if stable == bool(active_level) else 'normal', 'health': 'ok', 'raw': raw_level}
                else:
                    result[name] = {'state': 'present' if stable == bool(active_level) else 'absent', 'health': 'ok', 'raw': raw_level}
            except Exception as exc:
                result[name] = {'state': 'unknown', 'health': 'fault', 'error': str(exc)}
        return result

    def close(self):
        for request, _line, _active_level in self.readers.values():
            try:
                request.release()
            except Exception:
                pass
        self.readers = {}
