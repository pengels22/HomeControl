#pragma once

#include <stdint.h>

enum class AlarmState : uint8_t { DISARMED, ARMING_DELAY, ARMED_HOME, ARMED_AWAY, ENTRY_DELAY, TRIGGERED, TROUBLE };
enum class SensorType : uint8_t { OPENING, MOTION };
enum class RequestType : uint8_t { ARM_HOME, ARM_AWAY, DISARM, PIN_AUTH, PANIC, SETTINGS };

struct SensorState {
  bool open = false;
  bool failed = false;
  bool bypassed = false;
};

struct AlarmSnapshot {
  AlarmState state = AlarmState::DISARMED;
  uint32_t sequence = 0;
  uint32_t open_bitmap[3] = {0, 0, 0};
  uint32_t failed_bitmap[3] = {0, 0, 0};
  uint16_t trigger_sensor = 0xffff;
  uint32_t countdown_seconds = 0;
  uint32_t trouble_flags = 0;
};
