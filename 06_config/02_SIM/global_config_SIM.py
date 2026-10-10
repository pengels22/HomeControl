"""HomeControl SIM user-adjustable operational defaults.

REPO: existing repository value; PROPOSED: candidate awaiting approval.
Durations are milliseconds unless the name states otherwise.
This is a template; the module runtime does not automatically read this file.
Keep device identity, IPs, passwords, pin maps and wiring in their owners.
"""

# REPO | Default simulated analog-input voltage.
Analog_Input_Simulated_Default_V = 0.0

# REPO | SIM CAN config; mismatch with RMC firmware 250000 must be resolved before deployment.
CAN_Bitrate = 125000

# REPO | CAN support enabled.
CAN_Enabled = True

# REPO | SIM channel labels are truncated at 80 characters.
Device_Name_Max_Length = 80

# REPO | Module application heartbeat, ms; distinct from V3 supervisory heartbeat.
Heartbeat_Interval = 5000

# REPO | Upper 12 V loop warning threshold.
Hexa_12V_Loop_High_Warning_V = 13.2

# REPO | Lower 12 V loop warning threshold.
Hexa_12V_Loop_Low_Warning_V = 11.0

# REPO | 12 V loop considered off below this voltage.
Hexa_12V_Loop_Off_Below_V = 3.0

# REPO | Default off interval used by restart_hexa_12v, ms; requires safety recheck.
Hexa_12V_Restart_Off_Time = 5000

# REPO | Upper 3.3 V bus warning threshold.
Hexa_3V3_Bus_High_Warning_V = 3.5

# REPO | Lower 3.3 V bus warning threshold.
Hexa_3V3_Bus_Low_Warning_V = 3.1

# REPO | 3.3 V bus considered off below this voltage.
Hexa_3V3_Bus_Off_Below_V = 1.0

# REPO | Upper 5 V bus warning threshold.
Hexa_5V_Bus_High_Warning_V = 5.25

# REPO | Lower 5 V bus warning threshold.
Hexa_5V_Bus_Low_Warning_V = 4.75

# REPO | 5 V bus considered off below this voltage.
Hexa_5V_Bus_Off_Below_V = 1.0

# REPO | Initial reconnect backoff, ms.
Module_Connect_Backoff_Initial = 1000

# REPO | Maximum reconnect backoff, ms.
Module_Connect_Backoff_Max = 30000

# REPO | ms.
RMC_Firmware_Application_Return_Timeout = 20000

# REPO | ms.
RMC_Firmware_Block_Ack_Timeout = 2000

# REPO | Maximum retries per firmware block.
RMC_Firmware_Block_Retries = 3

# REPO | Classical CAN firmware bytes per block.
RMC_Firmware_Block_Size = 4

# REPO | ms.
RMC_Firmware_Bootloader_Ready_Timeout = 8000

# REPO | ms.
RMC_Firmware_Enter_Bootloader_Timeout = 3000

# REPO | ms.
RMC_Firmware_Verify_Timeout = 10000

# PROPOSED | De-energized initial outputs; validate current startup behavior.
Safety_12V_Default_Enabled = False

# REPO | Safety arbiter default for unknown state.
Safety_Fail_Safe_On_Unknown = True

# REPO | Module management web UI.
Web_Enabled = True

# REPO | SIM web port; per-module deployment setting.
Web_Port = 8092

