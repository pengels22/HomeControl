"""HomeControl PNL user-adjustable operational defaults.

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

# PROPOSED | Display telemetry refresh, ms; browser refresh behavior not yet pinned.
Panel_Auto_Refresh_Interval = 5000

# PROPOSED | UI-level brightness percentage; hardware control not implemented.
Panel_Default_Brightness = 100

# REPO | Module web routes validate HCM bearer token.
Panel_Require_Authentication = True

# REPO | Panel web interface enabled.
Web_Enabled = True

# REPO | Panel web port; per-module deployment setting.
Web_Port = 8095

