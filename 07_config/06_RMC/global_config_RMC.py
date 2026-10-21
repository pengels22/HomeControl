"""HomeControl RMC user-adjustable operational defaults.

REPO: existing repository value; PROPOSED: candidate awaiting approval.
Durations are milliseconds unless the name states otherwise.
This is a template; the module runtime does not automatically read this file.
Keep device identity, IPs, passwords, pin maps and wiring in their owners.
"""

# REPO | Shared RMC/SIM classical CAN bitrate.
CAN_Bitrate = 125000

# REPO | RMC CAN heartbeat frame interval, ms; separate from Unified V3.
Heartbeat_Interval = 10000

# REPO | HCM-to-SIM-to-RMC classical CAN update transport, bytes.
RMC_Firmware_Block_Size = 4

# REPO | Arduino sensor retry interval, ms.
Sensor_Retry_Interval = 5000

# REPO | Arduino serial diagnostics baud.
Serial_Baud = 115200

# REPO | Arduino sensor telemetry frame interval, ms.
Telemetry_Interval = 5000
