#include "alarm_core.h"

void AlarmCore::begin(uint32_t homeExitMs, uint32_t awayExitMs) {
  homeExitMs_ = homeExitMs; awayExitMs_ = awayExitMs; snapshot_ = AlarmSnapshot{};
  snapshot_.state = pins_.hasMaster() ? AlarmState::DISARMED : AlarmState::TROUBLE;
  rebuildBitmaps();
}

void AlarmCore::rebuildBitmaps() {
  snapshot_.open_bitmap[0] = snapshot_.open_bitmap[1] = snapshot_.open_bitmap[2] = 0;
  snapshot_.failed_bitmap[0] = snapshot_.failed_bitmap[1] = snapshot_.failed_bitmap[2] = 0;
  for (uint8_t i = 0; i < 24; ++i) {
    if (sensors_[i].open && !sensors_[i].bypassed) snapshot_.open_bitmap[i / 32] |= 1u << (i % 32);
    if (sensors_[i].failed) snapshot_.failed_bitmap[i / 32] |= 1u << (i % 32);
  }
}

void AlarmCore::setSensor(uint8_t index, bool open, bool failed) {
  if (index >= 24) return;
  sensors_[index].open = open; sensors_[index].failed = failed;
  if (!open) sensors_[index].bypassed = false;
  rebuildBitmaps(); ++snapshot_.sequence;
  if ((snapshot_.state == AlarmState::ARMED_HOME || snapshot_.state == AlarmState::ARMED_AWAY) && open && !sensors_[index].bypassed) {
    snapshot_.state = AlarmState::TRIGGERED; snapshot_.trigger_sensor = index; ++snapshot_.sequence;
  }
}

bool AlarmCore::arm(AlarmState mode, bool force) {
  rebuildBitmaps();
  if (snapshot_.open_bitmap[0] || snapshot_.open_bitmap[1] || snapshot_.open_bitmap[2] || snapshot_.failed_bitmap[0] || snapshot_.failed_bitmap[1] || snapshot_.failed_bitmap[2]) {
    if (!force) return false;
    for (auto& sensor : sensors_) if (sensor.open || sensor.failed) sensor.bypassed = true;
    rebuildBitmaps();
  }
  armedMode_ = mode; snapshot_.state = AlarmState::EXIT_DELAY; deadline_ = millis() + (mode == AlarmState::ARMED_HOME ? homeExitMs_ : awayExitMs_); ++snapshot_.sequence; return true;
}

bool AlarmCore::disarm(const String& pin) {
  if (!pins_.verify(pin)) return false;
  snapshot_.state = AlarmState::DISARMED; snapshot_.trigger_sensor = 0xffff; deadline_ = 0; ++snapshot_.sequence; return true;
}

bool AlarmCore::request(RequestType request, const String& pin) {
  switch (request) {
    case RequestType::ARM_HOME: return arm(AlarmState::ARMED_HOME, false);
    case RequestType::ARM_AWAY: return arm(AlarmState::ARMED_AWAY, false);
    case RequestType::FORCE_ARM_HOME: return arm(AlarmState::ARMED_HOME, true);
    case RequestType::FORCE_ARM_AWAY: return arm(AlarmState::ARMED_AWAY, true);
    case RequestType::DISARM: return disarm(pin);
    case RequestType::PANIC: snapshot_.state = AlarmState::TRIGGERED; snapshot_.trigger_sensor = 0xffff; ++snapshot_.sequence; return true;
    case RequestType::PIN_AUTH: return pins_.verify(pin);
    default: return false;
  }
}

void AlarmCore::tick(uint32_t now) {
  if (snapshot_.state == AlarmState::EXIT_DELAY && static_cast<int32_t>(now - deadline_) >= 0) {
    snapshot_.state = (snapshot_.open_bitmap[0] || snapshot_.open_bitmap[1] || snapshot_.open_bitmap[2]) ? AlarmState::TROUBLE : armedMode_;
    ++snapshot_.sequence;
  }
}
