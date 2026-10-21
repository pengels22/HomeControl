"""HomeControl LCM user-adjustable operational defaults.

REPO: existing repository value; PROPOSED: candidate awaiting approval.
Durations are milliseconds unless the name states otherwise.
This is a template; the module runtime does not automatically read this file.
Keep device identity, IPs, passwords, pin maps and wiring in their owners.
"""

# REPO | Module application heartbeat, ms.
Heartbeat_Interval = 5000

# REPO | Physical I2C driver disabled until hardware commissioning.
I2C_Enabled = False

# PROPOSED | Default requested lighting percentage.
Lighting_Default_Brightness = 100

# REPO-SIMULATOR | Existing simulator step count.
Lighting_Default_Fade_Steps = 30

# REPO-SIMULATOR | Existing simulator fade duration, ms; not yet LCM runtime default.
Lighting_Default_Fade_Time = 3000

# REPO | Runtime output normalization.
Lighting_Dimmer_Max_Percent = 100

# REPO | Runtime output normalization.
Lighting_Dimmer_Min_Percent = 0

# REPO | Shared module reconnect backoff, ms.
Module_Connect_Backoff_Initial = 1000

# REPO | Shared module reconnect backoff, ms.
Module_Connect_Backoff_Max = 30000

# REPO | Safety arbiter default.
Safety_Fail_Safe_On_Unknown = True

# REPO | Management UI enabled.
Web_Enabled = True

# REPO | LCM web port; per-module deployment setting.
Web_Port = 8093

