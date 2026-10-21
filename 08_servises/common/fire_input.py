from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FireInputSample:
    fire_active: bool
    fault: bool
    changed: bool


class DebouncedFireInput:
    """Simulated dry-contact fire input debounce helper.

    The current documented relay arrangement is NO -> 3.3 V, Common -> GPIO,
    NC -> Ground. For a normally de-energized relay this means LOW = normal and
    HIGH = fire alarm. This class does not access GPIO; tests and simulators
    feed boolean samples into it.
    """

    def __init__(self, alarm_level: bool = True, debounce_seconds: float = 0.25):
        self.alarm_level = bool(alarm_level)
        self.debounce_seconds = float(debounce_seconds)
        self._candidate = None
        self._candidate_since = None
        self._stable = None
        self._fault = True

    def sample(self, level: bool | None, now: float) -> FireInputSample:
        if level is None:
            self._fault = True
            return FireInputSample(fire_active=False, fault=True, changed=False)
        value = bool(level)
        if self._stable is None:
            self._stable = value
            self._candidate = value
            self._candidate_since = now
            self._fault = False
            return FireInputSample(fire_active=value == self.alarm_level, fault=False, changed=True)
        if value != self._candidate:
            self._candidate = value
            self._candidate_since = now
            return FireInputSample(fire_active=self._stable == self.alarm_level, fault=self._fault, changed=False)
        if value != self._stable and self._candidate_since is not None and now - self._candidate_since >= self.debounce_seconds:
            self._stable = value
            self._fault = False
            return FireInputSample(fire_active=value == self.alarm_level, fault=False, changed=True)
        self._fault = False
        return FireInputSample(fire_active=self._stable == self.alarm_level, fault=False, changed=False)
