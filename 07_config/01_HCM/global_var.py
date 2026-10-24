"""HomeControl HCM user-adjustable defaults (proposal; not wired into runtime).

Alphabetical, flat names for ``global_var.Name`` access. All time durations are
milliseconds unless the variable explicitly ends in ``_Seconds``. This module is
NOT the authoritative configuration for standalone Conflict/Jetson V3 daemons,
board-specific pinmaps, secrets, IP addresses, or CAN electrical settings.

Labels: [REPO] documented or coded default; [USER] user-approved; [PROPOSED]
recommended new default pending approval. Some [REPO] timings were converted
from seconds to milliseconds without changing their meaning.

Do not use these settings to weaken authorization, safety classification, or
hardwired protection. Values still require validation and explicit integration.
"""

# [PROPOSED] Input contact debounce for dedicated alarm loop, ms.
Alarm_Contact_Debounce = 250
# [PROPOSED] Report a safety-input state as stale after this period, ms.
Alarm_Input_Stale_Timeout = 15000
# [REPO] HCM web/API listener TCP port (settings.py).
API_HCM_Port = 8080
# [REPO] HCM-to-module control session TCP port (settings.py).
API_Module_Port = 6501
# [REPO] HCM module update service TCP port (settings.py).
API_Update_Port = 6503
# [REPO] OAuth/passkey auth challenge validity, ms (settings.py: 300 s).
Auth_Challenge_TTL = 300000
# [REPO] Password hash PBKDF2 iteration count (auth.py); security policy, not casual tuning.
Auth_Password_PBKDF2_Iterations = 260000
# [REPO] Persistent user session lifetime, ms (settings.py: 3600 s).
Auth_Session_TTL = 3600000
# [REPO] CAN firmware application return timeout, ms.
CAN_Firmware_Application_Return_Timeout = 20000
# [REPO] CAN firmware transfer max retries per block.
CAN_Firmware_Block_Max_Retries = 3
# [REPO] CAN firmware transfer data bytes per classical CAN block.
CAN_Firmware_Block_Size = 4
# [REPO] CAN firmware ACK timeout for each block, ms.
CAN_Firmware_Block_Timeout = 2000
# [REPO] CAN firmware bootloader readiness timeout, ms.
CAN_Firmware_Bootloader_Ready_Timeout = 8000
# [REPO] CAN firmware enter-bootloader acknowledgment timeout, ms.
CAN_Firmware_Enter_Bootloader_Timeout = 3000
# [REPO] CAN firmware verification timeout, ms.
CAN_Firmware_Verify_Timeout = 10000
# [REPO] HCM commissioning default (settings.py); permission/policy guarded.
Commissioning_Enabled = True
# [REPO] Module command response timeout, ms (registry.py).
Control_Command_Timeout = 10000
# [REPO] Initial module reconnect delay, ms (agent.py).
Control_Reconnect_Initial_Delay = 1000
# [REPO] Maximum backoff for module reconnection, ms (agent.py).
Control_Reconnect_Max_Delay = 30000
# [REPO] Module TCP session liveness interval, ms (module YAML).
Control_Session_Heartbeat_Interval = 5000
# [USER] Default door REX dry-contact closure duration, ms.
Door_Open_Pulse = 3000
# [PROPOSED] Upper limit for configurable REX pulse, ms.
Door_Open_Pulse_Max = 10000
# [PROPOSED] Lower limit for configurable REX pulse, ms.
Door_Open_Pulse_Min = 250
# [REPO] Dry contact fire input debounce, ms (hcm.yaml; fire_input.py).
Fire_Contact_Debounce = 250
# [REPO] Safety input alarm polarity: True=high (hcm.yaml/fire_input.py).
Fire_Input_Alarm_High = True
# [REPO] Safe-on-unknown condition supported by shared arbiter.
Fire_Input_Unknown_Default_Safe = True
# [REPO] Development mode default disabled (settings.py).
HCM_Dev_Mode = False
# [REPO] TLS currently off in development settings; production must require TLS.
HCM_TLS_Enabled = False
# [REPO] Require module client certificate when TLS enabled (settings.py).
HCM_TLS_Require_Client_Cert = True
# [REPO] Heartbeat timing from 00_Heartbeat/config-jetson.json, ms.
Heartbeat_Interval = 5000
# [REPO] Fault if available memory < percent in heartbeat daemon.
Heartbeat_Min_Available_Memory_Percent = 5
# [REPO] Unacknowledged Conflict peer threshold, ms.
Heartbeat_Peer_Timeout = 15000
# [REPO] HTTP request timeout for Conflict ACK, ms.
Heartbeat_Request_Timeout = 4000
# [REPO] Fault if root disk used >= percent in heartbeat daemon.
Heartbeat_Root_Disk_Fail_Percent = 95
# [REPO] Startup grace before missing peer is faulted, ms.
Heartbeat_Startup_Grace = 45000
# [REPO] Heartbeat V3 TCP port; protocol/deployment change requires coordination.
Heartbeat_TCP_Port = 6004
# [REPO] Fault if max reported temperature >= Celsius threshold.
Heartbeat_Thermal_Fail_C = 90
# [PROPOSED] Heartbeat module watchdog pulse interval, ms; actual watchdogs must be configured per module.
Heartbeat_Watchdog_Pulse_Interval = 5000
# [PROPOSED] Recommended app watchdog deadline, ms; must exceed pulse interval.
Heartbeat_Watchdog_Timeout = 15000
# [REPO] Cooling minimum run, ms (hvac.py; hcm.yaml).
HVAC_Cool_Min_Run = 120000
# [REPO] Cooling restart lockout, ms (hcm.yaml).
HVAC_Cool_Restart_Lockout = 300000
# [REPO] Damper movement lead delay, ms (hvac.py).
HVAC_Damper_Lead = 500
# [REPO] Heat/cool deadband, Fahrenheit.
HVAC_Deadband_F = 1.0
# [REPO] Default HCM thermostat setpoint, Fahrenheit.
HVAC_Default_Setpoint_F = 70.0
# [REPO] Fan lead delay, ms (hvac.py).
HVAC_Fan_Lead = 500
# [REPO] Fan postrun delay, ms (hvac.py).
HVAC_Fan_Postrun = 60000
# [REPO] Heating minimum run, ms (hvac.py).
HVAC_Heat_Min_Run = 60000
# [REPO] Heating restart lockout, ms (hcm.yaml).
HVAC_Heat_Restart_Lockout = 300000
# [REPO] Real LCM I2C output disabled pending commissioning (lcm.yaml).
LCM_Real_I2C_Enabled = False
# [REPO] LCM web UI enabled (lcm.yaml).
LCM_Web_Enabled = True
# [PROPOSED] Initial brightness for newly commissioned nonemergency light, percent.
Lighting_Default_Brightness = 100
# [REPO] Simulated fade interpolation step count.
Lighting_Fade_Steps = 30
# [REPO] Simulated LCM fade duration, ms (simulate_homecontrol.py).
Lighting_Fade_Time = 3000
# [REPO] Pairing glyph payload accepted age, ms (pairing_glyph.py).
Pairing_Code_Max_Age = 300000
# [REPO] Panel embedded UI enabled in pnl.yaml.
PNL_Web_Enabled = True
# [REPO] RCM web UI enabled (rcm.yaml).
RCM_Web_Enabled = True
# [PROPOSED] Auxiliary HCM safety relay pulse default; only for pulse-mode relays, ms.
Safety_Aux_Relay_Pulse = 1000
# [PROPOSED] Debounce for general dedicated safety DI contacts, ms.
Safety_Contact_Debounce = 250
# [PROPOSED] Require explicit fresh command after lockout clears.
Safety_Lockout_Release_Requires_New_Command = True
# [PROPOSED] Flag output feedback discrepancy after grace period, ms.
Safety_Output_Feedback_Timeout = 2000
# [REPO] Module -> HCM V3 Unix socket read timeout, ms (agent.py).
Supervision_Local_Socket_Timeout = 1000
# [REPO] Poll cadence during post-update reconnect, ms (updater.py).
Updater_Module_Poll_Interval = 2000
# [REPO] Wait for module to reconnect after update, ms (updater.py).
Updater_Module_Return_Timeout = 180000
# [REPO] API authentication check timeout to central HCM, ms (agent.py).
Web_HCM_Auth_Request_Timeout = 5000
# [REPO] Module UI normal listen enabled setting defaults true (module YAML).
Web_Module_Enabled = True
# [PROPOSED] UI refresh interval, ms. Current client polling is implementation-specific.
Web_Status_Refresh_Interval = 5000
