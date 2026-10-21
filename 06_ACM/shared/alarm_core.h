#pragma once

#include <Arduino.h>
#include "alarm_types.h"
#include "pin_store.h"

class AlarmCore {
 public:
  explicit AlarmCore(PinStore& pins) : pins_(pins) {}
  void begin(uint32_t homeExitMs = 30000, uint32_t awayExitMs = 60000);
  void setSensor(uint8_t index, bool open, bool failed = false);
  bool request(RequestType request, const String& pin = "");
  const AlarmSnapshot& snapshot() const { return snapshot_; }
  bool masterRequired() const { return !pins_.hasMaster(); }
  bool provisionMaster(const String& pin) { return pins_.provisionMaster(pin); }
  bool addPin(const String& master, const String& pin) { return pins_.verify(master) && pins_.addPin(pin); }
  void tick(uint32_t now);

 private:
  PinStore& pins_;
  AlarmSnapshot snapshot_;
  SensorState sensors_[24] = {};
  uint32_t homeExitMs_ = 30000, awayExitMs_ = 60000, deadline_ = 0;
  AlarmState armedMode_ = AlarmState::ARMED_HOME;
  bool arm(AlarmState mode, bool force);
  bool disarm(const String& pin);
  void rebuildBitmaps();
};
