#include "protocol.h"

namespace acm_protocol {
const char* alarmStateName(AlarmState state) {
  switch (state) {
    case AlarmState::ARMED_HOME: return "ARMED_HOME";
    case AlarmState::ARMED_AWAY: return "ARMED_AWAY";
    case AlarmState::ARMING_DELAY: return "ARMING_DELAY";
    case AlarmState::ENTRY_DELAY: return "ENTRY_DELAY";
    case AlarmState::TRIGGERED: return "TRIGGERED";
    case AlarmState::TROUBLE: return "TROUBLE";
    default: return "DISARMED";
  }
}

bool sendFrame(Client& client, const String& type, const String& payloadJson) {
  if (!client || payloadJson.length() > MAX_FRAME) return false;
  String frame = String("{\"version\":") + VERSION + ",\"type\":\"" + type + "\",\"payload\":" + payloadJson + "}";
  const uint32_t length = frame.length();
  uint8_t header[4] = {static_cast<uint8_t>(length >> 24), static_cast<uint8_t>(length >> 16), static_cast<uint8_t>(length >> 8), static_cast<uint8_t>(length)};
  if (client.write(header, sizeof(header)) != sizeof(header)) return false;
  return client.print(frame) == frame.length();
}

bool sendHeartbeat(Client& client, const String& deviceId, const String& hostname, uint32_t sequence) {
  String payload = String("{\"device_id\":\"") + deviceId + "\",\"hostname\":\"" + hostname +
                   "\",\"sequence\":" + sequence + ",\"health\":\"OK\",\"status\":\"ALARM_STANDALONE\"}";
  return sendFrame(client, "HEARTBEAT", payload);
}

bool sendAlarmStatus(Client& client, const String& deviceId, const String& hostname, const AlarmSnapshot& snapshot, bool full) {
  String payload = String("{\"device_id\":\"") + deviceId + "\",\"hostname\":\"" + hostname +
                   "\",\"sequence\":" + snapshot.sequence + ",\"state\":\"" + alarmStateName(snapshot.state) +
                   "\",\"countdown\":" + snapshot.countdown_seconds + ",\"trouble\":" +
                   ((snapshot.trouble_flags != 0) ? "true" : "false") + "}";
  return sendFrame(client, "ACM_STATUS", payload);
}
}
