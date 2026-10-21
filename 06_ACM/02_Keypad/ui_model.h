#pragma once

#include <Arduino.h>
#include "alarm_types.h"

enum class KeypadPage : uint8_t { HOME, NOTIFICATIONS, SETTINGS, PIN_ENTRY, AREA_DETAIL };

class KeypadUiModel {
 public:
  void apply(const AlarmSnapshot& snapshot) { snapshot_ = snapshot; }
  void page(KeypadPage value) { page_ = value; }
  KeypadPage page() const { return page_; }
  AlarmState state() const { return snapshot_.state; }
  const String& pinBuffer() const { return pin_; }
  void key(char value) {
    if (value >= '0' && value <= '9' && pin_.length() < 12) pin_ += value;
    else if (value == 'B' && pin_.length()) pin_.remove(pin_.length() - 1);
    else if (value == 'C') pin_ = "";
  }
  String takePin() { String value = pin_; pin_ = ""; return value; }

 private:
  KeypadPage page_ = KeypadPage::HOME;
  AlarmSnapshot snapshot_;
  String pin_;
};
