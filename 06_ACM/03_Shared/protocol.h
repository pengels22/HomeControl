#pragma once

#include <Arduino.h>
#include <Client.h>
#include "alarm_types.h"

namespace acm_protocol {
constexpr uint8_t VERSION = 1;
constexpr uint16_t MAX_FRAME = 2048;
constexpr uint32_t HEARTBEAT_INTERVAL_MS = 30000;
constexpr uint32_t SNAPSHOT_INTERVAL_MS = 60000;
constexpr uint16_t KEYPAD_PORT = 6502;
constexpr char IDENTIFY_REQUEST[] = "IDENTIFY_REQUEST";
constexpr char IDENTIFY_RESPONSE[] = "IDENTIFY_RESPONSE";
constexpr char HELLO_ACM[] = "HELLO_ACM";
constexpr char HELLO_KEYPAD[] = "HELLO_KEYPAD";
constexpr char SENSOR_SNAPSHOT_REQUEST[] = "SENSOR_SNAPSHOT_REQUEST";
constexpr char SENSOR_SNAPSHOT[] = "SENSOR_SNAPSHOT";
constexpr char SENSOR_UPDATE[] = "SENSOR_UPDATE";
constexpr char ALARM_STATE[] = "ALARM_STATE";
constexpr char LOCAL_SIREN_ON[] = "LOCAL_SIREN_ON";
constexpr char LOCAL_SIREN_OFF[] = "LOCAL_SIREN_OFF";

// Incremental parser for the single, bounded, big-endian length-prefixed frame
// used by both firmware targets. It is deliberately ArduinoJson-free so the
// framing can be exercised with small host-side fixtures later.
class FrameParser {
 public:
  bool feed(uint8_t byte);
  bool complete() const { return complete_; }
  bool invalid() const { return invalid_; }
  String take();
  void reset();
 private:
  uint8_t header_[4] = {};
  uint8_t header_used_ = 0;
  uint16_t expected_ = 0;
  String payload_;
  bool complete_ = false;
  bool invalid_ = false;
};

const char* alarmStateName(AlarmState state);
bool sendFrame(Client& client, const String& type, const String& payloadJson);
bool sendHeartbeat(Client& client, const String& deviceId, const String& hostname, uint32_t sequence);
bool sendAlarmStatus(Client& client, const String& deviceId, const String& hostname, const AlarmSnapshot& snapshot, bool full);
}
