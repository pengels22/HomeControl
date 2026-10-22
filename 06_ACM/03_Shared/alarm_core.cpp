#include "alarm_core.h"

void AlarmCore::begin(uint32_t homeExitMs, uint32_t awayExitMs) {
  (void)homeExitMs; awayExitMs_ = awayExitMs ? awayExitMs : 30000;
  snapshot_ = AlarmSnapshot{}; snapshot_.state = pins_.hasMaster() ? AlarmState::DISARMED : AlarmState::TROUBLE; rebuildBitmaps();
}
void AlarmCore::rebuildBitmaps() {
  snapshot_.open_bitmap[0] = snapshot_.open_bitmap[1] = snapshot_.open_bitmap[2] = 0;
  snapshot_.failed_bitmap[0] = snapshot_.failed_bitmap[1] = snapshot_.failed_bitmap[2] = 0;
  for (uint8_t i = 0; i < 24; ++i) { if (sensors_[i].open && !sensors_[i].bypassed) snapshot_.open_bitmap[i / 32] |= 1u << (i % 32); if (sensors_[i].failed) snapshot_.failed_bitmap[i / 32] |= 1u << (i % 32); }
}
void AlarmCore::setSensor(uint8_t index, bool open, bool failed) {
  if (index >= 24) return; const bool changed = sensors_[index].open != open || sensors_[index].failed != failed;
  sensors_[index].open = open; sensors_[index].failed = failed; if (!open) sensors_[index].bypassed = false; rebuildBitmaps(); if (changed) ++snapshot_.sequence;
  if (snapshot_.state == AlarmState::ARMING_DELAY || !open || sensors_[index].bypassed) return;
  if (snapshot_.state != AlarmState::ARMED_HOME && snapshot_.state != AlarmState::ARMED_AWAY) return;
  if (sensorTypes_[index] == SensorType::MOTION) { if (snapshot_.state == AlarmState::ARMED_AWAY && !motionActive_[index]) { motionActive_[index] = true; motionStarted_[index] = millis(); } return; }
  beginEntryDelay(index, millis());
}
bool AlarmCore::arm(AlarmState mode, const String& pin) {
  if (!pins_.verify(pin)) return false; armedMode_ = mode;
  for (uint8_t i = 0; i < 24; ++i) if (sensors_[i].open) sensors_[i].bypassed = true;
  rebuildBitmaps(); snapshot_.trigger_sensor = 0xffff; snapshot_.countdown_seconds = 0;
  if (mode == AlarmState::ARMED_HOME) { snapshot_.state = AlarmState::ARMED_HOME; ++snapshot_.sequence; return true; }
  snapshot_.state = AlarmState::ARMING_DELAY; deadline_ = millis() + awayExitMs_; ++snapshot_.sequence; return true;
}
bool AlarmCore::disarm(const String& pin) {
  if (!pins_.verify(pin)) return false; snapshot_.state = AlarmState::DISARMED; snapshot_.trigger_sensor = 0xffff; snapshot_.countdown_seconds = 0; deadline_ = 0;
  for (uint8_t i = 0; i < 24; ++i) motionActive_[i] = false; ++snapshot_.sequence; return true;
}
bool AlarmCore::request(RequestType request, const String& pin) {
  switch (request) { case RequestType::ARM_HOME: return arm(AlarmState::ARMED_HOME, pin); case RequestType::ARM_AWAY: return arm(AlarmState::ARMED_AWAY, pin); case RequestType::DISARM: return disarm(pin); case RequestType::PANIC: snapshot_.state = AlarmState::TRIGGERED; snapshot_.trigger_sensor = 0xffff; ++snapshot_.sequence; return true; case RequestType::PIN_AUTH: return pins_.verify(pin); default: return false; }
}
void AlarmCore::beginEntryDelay(uint8_t sensor, uint32_t now) { snapshot_.state = AlarmState::ENTRY_DELAY; snapshot_.trigger_sensor = sensor; deadline_ = now + 30000; snapshot_.countdown_seconds = 30; ++snapshot_.sequence; }
void AlarmCore::tick(uint32_t now) {
  if (snapshot_.state == AlarmState::ARMING_DELAY) { snapshot_.countdown_seconds = deadline_ > now ? (deadline_ - now + 999) / 1000 : 0; if (static_cast<int32_t>(now - deadline_) >= 0) { snapshot_.state = AlarmState::ARMED_AWAY; snapshot_.countdown_seconds = 0; ++snapshot_.sequence; } return; }
  if (snapshot_.state == AlarmState::ENTRY_DELAY) { snapshot_.countdown_seconds = deadline_ > now ? (deadline_ - now + 999) / 1000 : 0; if (static_cast<int32_t>(now - deadline_) >= 0) { snapshot_.state = AlarmState::TRIGGERED; snapshot_.countdown_seconds = 0; ++snapshot_.sequence; } return; }
  if (snapshot_.state != AlarmState::ARMED_AWAY) return;
  for (uint8_t i = 0; i < 24; ++i) if (sensorTypes_[i] == SensorType::MOTION && motionActive_[i]) { if (!sensors_[i].open) motionActive_[i] = false; else if (now - motionStarted_[i] >= 10000) { beginEntryDelay(i, now); return; } }
}
