# Pass 9 PNL hardware bring-up

The ESP-IDF project now has independent LVGL, HCM client, sensor, telemetry,
and Heartbeat task boundaries in `05_PNL/firmware/main/pnl_main.c`. The code is
still a no-GPIO scaffold because the Waveshare ESP32-P4-WIFI6-Touch-LCD-7B
schematic, component versions, and board are not available in this session.

## Reproducible build

With an approved ESP-IDF installation:

```sh
cd 05_PNL/firmware
idf.py set-target esp32p4
idf.py build
```

The build has not been run here because `idf.py`/the ESP-IDF environment is not
installed. A successful compile would not establish LCD, touch, W5500, BH1750,
AHT20, C4002, codec, speaker, PoE, or thermal readiness.

## Required bench gates

Verify the official pin map and rails before adding drivers, then test LCD/LVGL,
touch, Ethernet, each sensor, audio capture/playback, power behavior, watchdog,
and disconnected-HCM fail-muted behavior. Never infer pin mappings from this
scaffold or enable physical outputs from software tests.
