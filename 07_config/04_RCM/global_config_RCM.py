"""HomeControl RCM user-adjustable operational defaults.

REPO: existing repository value; PROPOSED: candidate awaiting approval.
Durations are milliseconds unless the name states otherwise.
This is a template; the module runtime does not automatically read this file.
Keep device identity, IPs, passwords, pin maps and wiring in their owners.
"""

# REPO | Module application heartbeat, ms.
Heartbeat_Interval = 5000

# REPO | Shared module reconnect backoff, ms.
Module_Connect_Backoff_Initial = 1000

# REPO | Shared module reconnect backoff, ms.
Module_Connect_Backoff_Max = 30000

# PROPOSED | Normal startup output command is de-energized; verify physical polarity.
RCM_Default_Relay_On = False

# REPO | 4 banks A-D x 8 outputs; topology reference, not an arbitrary runtime user override.
RCM_Relay_Count = 32

# REPO | Safety arbiter default.
Safety_Fail_Safe_On_Unknown = True

# REPO | Management UI enabled.
Web_Enabled = True

# REPO | RCM web port; per-module deployment setting.
Web_Port = 8094

