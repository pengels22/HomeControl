#!/usr/bin/env python3
"""Run the production-shaped driver suite without touching LAB1 hardware."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module


drivers = import_module("physical_drivers")


def main() -> None:
    bundle = drivers.build_lab1_mock_drivers()
    transport = bundle["i2c_transport"]
    rcm = bundle["rcm_relays"]
    lcm = bundle["lcm_relays"]
    pwm = bundle["lcm_pwm"]
    rcm.initialize()
    lcm.initialize()
    pwm.initialize()

    for index in range(32):
        result = rcm.set_channel(index, index % 2 == 0)
        assert result["readback"] is (index % 2 == 0)
    for index in range(8):
        result = lcm.set_channel(index, index % 2 == 1)
        assert result["readback"] is (index % 2 == 1)
    for index in range(10):
        pwm.set_percent(index, index * 10)
    for component in ("light:0", "light:1"):
        bundle["shelly_1"].set_brightness(component, 65)
        bundle["shelly_2"].set_brightness(component, 35)

    # Concurrent writes share the same transport lock and preserve all channels.
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: rcm.set_channel(index, True), range(32)))
    assert all(rcm.read_channel(index) for index in range(32))

    before = rcm.shadow[0x20]
    rcm.set_channel(0, False)
    after = rcm.shadow[0x20]
    assert after == (before | 0x01)

    transport.fail_writes = True
    try:
        try:
            rcm.set_channel(1, True)
        except drivers.HardwareTransportError:
            pass
        else:
            raise AssertionError("write failure was not propagated")
    finally:
        transport.fail_writes = False
    assert rcm.set_channel(1, True)["readback"] is True

    transport.fail_reads = True
    try:
        try:
            rcm.read_channel(0)
        except drivers.HardwareTransportError:
            pass
        else:
            raise AssertionError("read failure was not propagated")
    finally:
        transport.fail_reads = False

    print(json.dumps({
        "ok": True,
        "simulation": True,
        "physical_outputs_enabled": False,
        "commissioning_status": "SIMULATED",
        "rcm_channels_tested": 32,
        "lcm_relay_channels_tested": 8,
        "pca9685_channels_tested": 10,
        "shelly_channels_tested": 4,
        "i2c_operations": len(transport.operations),
        "shelly_calls": len(bundle["shelly_1"].calls) + len(bundle["shelly_2"].calls),
        "physical_transports_opened": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
