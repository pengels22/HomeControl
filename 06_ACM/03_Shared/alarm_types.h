#pragma once

#include <stdint.h>

enum class AlarmState : uint8_t { DISARMED, ARMED_HOME, ARMED_AWAY, EXIT_DELAY, ENTRY_DELAY, TRIGGERED, TROUBLE };
enum class RequestType : uint8_t { ARM_HOME, ARM_AWAY, FORCE_ARM_HOME, FORCE_ARM_AWAY, DISARM, PIN_AUTH, PANIC, SETTINGS };

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
  uint32_t trouble_flags = 0;
};
