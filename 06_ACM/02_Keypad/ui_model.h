#pragma once

#include <Arduino.h>
#include "alarm_types.h"

enum class KeypadPage : uint8_t {
  HOME,
  ALERTS,
  SETTINGS,
  AREA_DETAIL,
  PASSCODE_ENTRY,
  MASTER_PROVISION,
  FORCE_ARM_CONFIRM,
};

enum class TouchAction : uint8_t {
  NONE, NOTIFICATIONS, SETTINGS, DIGIT_0, DIGIT_1, DIGIT_2, DIGIT_3,
  DIGIT_4, DIGIT_5, DIGIT_6, DIGIT_7, DIGIT_8, DIGIT_9, BACKSPACE, ENTER,
  ARM_HOME, ARM_AWAY, DISARM, BACK, FORCE_ARM, CANCEL,
};

struct TouchRect { int16_t x; int16_t y; int16_t width; int16_t height; };

// One layout source for the future LCD renderer and the design-reference renders.
namespace keypad_layout {
constexpr uint16_t WIDTH = 480;
constexpr uint16_t HEIGHT = 320;
constexpr TouchRect NOTIFICATIONS = {8, 5, 52, 38};
constexpr TouchRect SETTINGS = {420, 5, 52, 38};
constexpr TouchRect DIGITS[12] = {
    {92, 62, 84, 42}, {198, 62, 84, 42}, {304, 62, 84, 42},
    {92, 108, 84, 42}, {198, 108, 84, 42}, {304, 108, 84, 42},
    {92, 154, 84, 42}, {198, 154, 84, 42}, {304, 154, 84, 42},
    {92, 200, 84, 42}, {198, 200, 84, 42}, {304, 200, 84, 42},
};
constexpr TouchRect ACTION_LEFT = {52, 261, 176, 48};
constexpr TouchRect ACTION_RIGHT = {252, 261, 176, 48};
}

// One reusable numeric keypad for every PIN and arm/disarm flow.
class NumericKeypadComponent {
 public:
  static constexpr uint8_t KEY_COUNT = 12;
  static const TouchRect& region(uint8_t index) { return keypad_layout::DIGITS[index < KEY_COUNT ? index : 0]; }
  static char label(uint8_t index) {
    static constexpr char labels[KEY_COUNT] = {'1', '2', '3', '4', '5', '6', '7', '8', '9', 'B', '0', 'E'};
    return labels[index < KEY_COUNT ? index : 0];
  }
};

struct RemoteAreaSummary {
  String name;
  String status;
  bool selectable = false;
};

class KeypadUiModel {
 public:
  void apply(const AlarmSnapshot& snapshot) { snapshot_ = snapshot; }
  void page(KeypadPage value) { page_ = value; if (value == KeypadPage::HOME) clearPin(); }
  KeypadPage page() const { return page_; }
  AlarmState state() const { return snapshot_.state; }
  const AlarmSnapshot& snapshot() const { return snapshot_; }
  const String& pinBuffer() const { return pin_; }
  void setCountdown(uint32_t seconds) { countdown_seconds_ = seconds; }
  uint32_t countdown() const { return countdown_seconds_; }
  void setTriggeringSensor(const String& value) { triggering_sensor_ = value; }
  const String& triggeringSensor() const { return triggering_sensor_; }
  void setLocalArea(const String& value) { local_area_ = value; }
  const String& localArea() const { return local_area_; }
  void setSelectedRemoteArea(const String& value) { selected_remote_area_ = value; }
  const String& selectedRemoteArea() const { return selected_remote_area_; }
  void setAcmConnected(bool value) { acm_connected_ = value; }
  bool acmConnected() const { return acm_connected_; }
  void setPendingArmMode(AlarmState value) { pending_arm_mode_ = value; }
  AlarmState pendingArmMode() const { return pending_arm_mode_; }
  void setOpenSensors(const String& value) { open_sensors_ = value; }
  const String& openSensors() const { return open_sensors_; }
  void setFailedSensors(const String& value) { failed_sensors_ = value; }
  const String& failedSensors() const { return failed_sensors_; }
  void setRemoteAreas(const RemoteAreaSummary* areas, uint8_t count) {
    remote_count_ = count > 8 ? 8 : count;
    for (uint8_t i = 0; i < remote_count_; ++i) remote_areas_[i] = areas[i];
  }
  uint8_t remoteAreaCount() const { return remote_count_; }
  const RemoteAreaSummary& remoteArea(uint8_t index) const { return remote_areas_[index]; }
  void key(char value) {
    if (value >= '0' && value <= '9' && pin_.length() < 12) pin_ += value;
    else if (value == 'B' && pin_.length()) pin_.remove(pin_.length() - 1);
    else if (value == 'C') clearPin();
  }
  String takePin() { String value = pin_; clearPin(); return value; }
  void clearPin() { pin_ = ""; }

 private:
  KeypadPage page_ = KeypadPage::HOME;
  AlarmSnapshot snapshot_;
  AlarmState pending_arm_mode_ = AlarmState::DISARMED;
  String pin_, triggering_sensor_, local_area_, selected_remote_area_, open_sensors_, failed_sensors_;
  RemoteAreaSummary remote_areas_[8];
  uint8_t remote_count_ = 0;
  uint32_t countdown_seconds_ = 0;
  bool acm_connected_ = false;
};
