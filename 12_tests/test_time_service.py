from datetime import datetime, timezone
from importlib import import_module

import pytest


time_service = import_module('02_HCM.time_service')


def fixed(value):
    return lambda: value


def test_est_winter_conversion_and_injected_clock():
    service = time_service.TimeService(
        'America/Detroit',
        clock=fixed(datetime(2026, 1, 15, 17, 30, tzinfo=timezone.utc)),
        sync_probe=lambda: 'synchronized',
    )
    assert service.now_utc().isoformat() == '2026-01-15T17:30:00+00:00'
    assert service.now_local().isoformat() == '2026-01-15T12:30:00-05:00'
    assert service.utc_offset_seconds() == -18000
    assert service.dst() is False
    assert service.local_date().isoformat() == '2026-01-15'


def test_edt_summer_and_date_boundary():
    service = time_service.TimeService(
        'America/Detroit',
        clock=fixed(datetime(2026, 7, 1, 3, 30, tzinfo=timezone.utc)),
        sync_probe=lambda: 'unsynchronized',
    )
    assert service.now_local().isoformat() == '2026-06-30T23:30:00-04:00'
    assert service.local_date().isoformat() == '2026-06-30'
    assert service.utc_offset_seconds() == -14400
    assert service.dst() is True
    assert service.sync_health().status == 'unsynchronized'


def test_sync_unknown_is_cached_and_payload_is_aware():
    calls = []
    service = time_service.TimeService(
        'America/Detroit',
        clock=fixed(datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)),
        sync_probe=lambda: calls.append(1) or 'unknown',
        monotonic=lambda: 10.0,
    )
    first = service.as_payload()
    second = service.as_payload()
    assert first['sync_status'] == second['sync_status'] == 'unknown'
    assert len(calls) == 1
    assert first['utc'].endswith('Z') and first['local'].endswith('-05:00')
    assert first['checked_at'].endswith('Z')


def test_naive_injected_clock_is_treated_as_utc():
    service = time_service.TimeService('America/Detroit', clock=fixed(datetime(2026, 1, 1, 0, 0)))
    assert service.now_utc().tzinfo is timezone.utc


def test_invalid_timezone_rejected():
    with pytest.raises(Exception):
        time_service.TimeService('Not/AZone')
