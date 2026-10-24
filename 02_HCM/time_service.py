"""Canonical application time access for HCM.

The operating system owns clock synchronization.  This service only provides
timezone-aware views of that clock and cached, best-effort synchronization
health; it never maintains or advances a software clock.
"""
from __future__ import annotations

import subprocess
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, timezone, tzinfo
from typing import Callable
from zoneinfo import ZoneInfo


Clock = Callable[[], datetime]


@dataclass(frozen=True)
class SyncHealth:
    status: str
    checked_at: datetime
    source: str | None = None
    detail: str | None = None


class TimeService:
    def __init__(self, timezone_name: str = 'America/Detroit', *, clock: Clock | None = None,
                 monotonic: Callable[[], float] | None = None,
                 sync_probe: Callable[[], SyncHealth | str] | None = None,
                 sync_cache_seconds: float = 30.0):
        self._zone = ZoneInfo(timezone_name)
        self._timezone_name = timezone_name
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or _time.monotonic
        self._sync_probe = sync_probe or self._probe_sync
        self._sync_cache_seconds = max(0.0, sync_cache_seconds)
        self._sync_cached: SyncHealth | None = None
        self._sync_checked_mono: float | None = None

    def now_utc(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def now_local(self) -> datetime:
        return self.now_utc().astimezone(self._zone)

    def local_date(self) -> date:
        return self.now_local().date()

    def timezone(self) -> str:
        return self._timezone_name

    def utc_offset_seconds(self) -> int:
        return int((self.now_local().utcoffset() or timezone.utc.utcoffset(None)).total_seconds())

    def dst(self) -> bool:
        return bool(self.now_local().dst())

    def monotonic(self) -> float:
        return self._monotonic()

    def sync_health(self, *, force: bool = False) -> SyncHealth:
        now_mono = self._monotonic()
        if not force and self._sync_cached and self._sync_checked_mono is not None \
                and now_mono - self._sync_checked_mono < self._sync_cache_seconds:
            return self._sync_cached
        try:
            value = self._sync_probe()
            if isinstance(value, SyncHealth):
                health = value
            else:
                health = SyncHealth(str(value), self.now_utc())
        except Exception as exc:  # telemetry must never make time unavailable
            health = SyncHealth('unknown', self.now_utc(), detail=str(exc)[:160])
        self._sync_cached = health
        self._sync_checked_mono = now_mono
        return health

    def as_payload(self, *, force_sync: bool = False) -> dict:
        utc_now = self.now_utc()
        local_now = utc_now.astimezone(self._zone)
        health = self.sync_health(force=force_sync)
        return {
            'utc': utc_now.isoformat().replace('+00:00', 'Z'),
            'local': local_now.isoformat(),
            'timezone': self._timezone_name,
            'utc_offset_seconds': int((local_now.utcoffset() or timezone.utc.utcoffset(None)).total_seconds()),
            'dst': bool(local_now.dst()),
            'sync_status': health.status,
            'sync_source': health.source,
            'sync_detail': health.detail,
            'checked_at': health.checked_at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
        }

    def _probe_sync(self) -> SyncHealth:
        checked = self.now_utc()
        try:
            result = subprocess.run(
                ['timedatectl', 'show', '-p', 'NTPSynchronized', '-p', 'NTP', '--value'],
                check=False, capture_output=True, text=True, timeout=1.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return SyncHealth('unknown', checked, detail=str(exc)[:160])
        values = [line.strip().lower() for line in result.stdout.splitlines() if line.strip()]
        if result.returncode != 0 or not values:
            return SyncHealth('unknown', checked, detail='system synchronization status unavailable')
        if values[0] == 'yes':
            return SyncHealth('synchronized', checked, source=values[1] if len(values) > 1 else None)
        if values[0] == 'no':
            return SyncHealth('unsynchronized', checked, source=values[1] if len(values) > 1 else None)
        return SyncHealth('unknown', checked, source=values[1] if len(values) > 1 else None)


def build_time_service(timezone_name: str) -> TimeService:
    return TimeService(timezone_name)
