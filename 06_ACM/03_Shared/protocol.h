#pragma once

#include <Arduino.h>
#include <Client.h>
#include "alarm_types.h"

namespace acm_protocol {
constexpr uint8_t VERSION = 1;
constexpr uint16_t MAX_FRAME = 2048;
constexpr uint32_t HEARTBEAT_INTERVAL_MS = 30000;
constexpr uint32_t SNAPSHOT_INTERVAL_MS = 60000;

const char* alarmStateName(AlarmState state);
bool sendFrame(Client& client, const String& type, const String& payloadJson);
bool sendHeartbeat(Client& client, const String& deviceId, const String& hostname, uint32_t sequence);
bool sendAlarmStatus(Client& client, const String& deviceId, const String& hostname, const AlarmSnapshot& snapshot, bool full);
}
