#pragma once
#include <Arduino.h>
#include "alarm_types.h"
#include "pin_store.h"
class AlarmCore {
 public:
  static constexpr uint8_t MAX_LOGICAL_SENSORS=80;
  explicit AlarmCore(PinStore& pins) : pins_(pins) {}
  void begin(uint32_t homeExitMs = 0, uint32_t awayExitMs = 30000);
  void setSensor(uint8_t index, bool open, bool failed = false);
  void setSensorInUse(uint8_t index, bool value) { if (index < MAX_LOGICAL_SENSORS) inUse_[index] = value; }
  void setSensorType(uint8_t index, SensorType type) { if (index < MAX_LOGICAL_SENSORS) sensorTypes_[index] = type; }
  bool request(RequestType request, const String& pin = "");
  const AlarmSnapshot& snapshot() const { return snapshot_; }
  bool masterRequired() const { return !pins_.hasMaster(); } bool credentialReprovisionRequired() const { return pins_.credentialReprovisionRequired(); }
  bool provisionMaster(const String& pin) { const bool ok = pins_.provisionMaster(pin); if (ok && snapshot_.state == AlarmState::TROUBLE) snapshot_.state = AlarmState::DISARMED; return ok; }
  bool addPin(const String& master, const String& pin) { return pins_.addPin(master, pin); }
  void tick(uint32_t now);
 private:
  PinStore& pins_; AlarmSnapshot snapshot_; SensorState sensors_[MAX_LOGICAL_SENSORS] = {}; SensorType sensorTypes_[MAX_LOGICAL_SENSORS] = {}; bool inUse_[MAX_LOGICAL_SENSORS] = {}; bool motionActive_[MAX_LOGICAL_SENSORS] = {}; uint32_t motionStarted_[MAX_LOGICAL_SENSORS] = {};
  uint32_t awayExitMs_ = 30000, deadline_ = 0; AlarmState armedMode_ = AlarmState::ARMED_HOME;
  bool arm(AlarmState mode, const String& pin); bool disarm(const String& pin); void beginEntryDelay(uint8_t sensor, uint32_t now); void rebuildBitmaps();
};
