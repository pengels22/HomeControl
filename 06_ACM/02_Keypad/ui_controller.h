#pragma once

#include "ui_model.h"

class KeypadDisplay {
 public:
  virtual ~KeypadDisplay() = default;
  virtual void begin() = 0;
  virtual void render(const KeypadUiModel& model) = 0;
};

class KeypadTouch {
 public:
  virtual ~KeypadTouch() = default;
  virtual bool read(uint16_t& x, uint16_t& y) = 0;
};

// Driver-neutral boundary: the selected LCD/touch controller is wired here later.
class KeypadDisplayBoundary final : public KeypadDisplay {
 public:
  void begin() override {}
  void render(const KeypadUiModel& model) override { (void)model; }
};

class KeypadUiController {
 public:
  KeypadUiController(KeypadUiModel& model, KeypadDisplay& display) : model_(model), display_(display) {}
  void begin() { display_.begin(); render(); }
  void apply(const AlarmSnapshot& snapshot) { model_.apply(snapshot); render(); }
  void setAcmConnected(bool connected) { model_.setAcmConnected(connected); render(); }
  // Hardware drivers call this after converting a touch sample to display pixels.
  // Business logic receives only the semantic action below.
  void handleTouch(uint16_t x, uint16_t y) { touch(actionAt(x, y)); }
  void touch(TouchAction action) {
    switch (action) {
      case TouchAction::NOTIFICATIONS: model_.page(KeypadPage::ALERTS); break;
      case TouchAction::SETTINGS: model_.page(KeypadPage::SETTINGS); break;
      case TouchAction::BACK: model_.page(KeypadPage::HOME); break;
      case TouchAction::CANCEL: model_.clearPin(); model_.page(KeypadPage::HOME); break;
      case TouchAction::ARM_HOME: model_.setPendingArmMode(AlarmState::ARMED_HOME); model_.page(KeypadPage::PASSCODE_ENTRY); break;
      case TouchAction::ARM_AWAY: model_.setPendingArmMode(AlarmState::ARMED_AWAY); model_.page(KeypadPage::PASSCODE_ENTRY); break;
      case TouchAction::DISARM: model_.page(KeypadPage::PASSCODE_ENTRY); break;
      case TouchAction::BACKSPACE: model_.key('B'); break;
      case TouchAction::DIGIT_0: model_.key('0'); break; case TouchAction::DIGIT_1: model_.key('1'); break;
      case TouchAction::DIGIT_2: model_.key('2'); break; case TouchAction::DIGIT_3: model_.key('3'); break;
      case TouchAction::DIGIT_4: model_.key('4'); break; case TouchAction::DIGIT_5: model_.key('5'); break;
      case TouchAction::DIGIT_6: model_.key('6'); break; case TouchAction::DIGIT_7: model_.key('7'); break;
      case TouchAction::DIGIT_8: model_.key('8'); break; case TouchAction::DIGIT_9: model_.key('9'); break;
      case TouchAction::ENTER: submitPin(); break;
      case TouchAction::NONE: break;
    }
    render();
  }
  KeypadUiModel& model() { return model_; }

 private:
  TouchAction actionAt(uint16_t x, uint16_t y) const {
    auto inside = [x, y](const TouchRect& r) { return x >= r.x && y >= r.y && x < r.x + r.width && y < r.y + r.height; };
    if (inside(keypad_layout::NOTIFICATIONS)) return TouchAction::NOTIFICATIONS;
    if (inside(keypad_layout::SETTINGS)) return TouchAction::SETTINGS;
    for (uint8_t i = 0; i < NumericKeypadComponent::KEY_COUNT; ++i) if (inside(NumericKeypadComponent::region(i))) {
      if (i == 9) return TouchAction::BACKSPACE;
      if (i == 10) return TouchAction::DIGIT_0;
      if (i == 11) return TouchAction::ENTER;
      return static_cast<TouchAction>(static_cast<uint8_t>(TouchAction::DIGIT_1) + i);
    }
    if (inside(keypad_layout::ACTION_LEFT)) {
      if (model_.state() == AlarmState::DISARMED) return TouchAction::ARM_HOME;
      return TouchAction::DISARM;
    }
    if (inside(keypad_layout::ACTION_RIGHT)) {
      if (model_.state() == AlarmState::DISARMED) return TouchAction::ARM_AWAY;
      return TouchAction::BACK;
    }
    return TouchAction::NONE;
  }
  void submitPin() { model_.takePin(); }
  void render() { display_.render(model_); }
  KeypadUiModel& model_;
  KeypadDisplay& display_;
};
