#pragma once

#include <Arduino.h>
#include <Preferences.h>

class PinStore {
 public:
  bool begin(const char* ns = "alarm");
  bool hasMaster() const { return masterConfigured_; }
  bool provisionMaster(const String& pin);
  bool addPin(const String& pin);
  bool verify(const String& pin) const;
  bool changeMaster(const String& oldPin, const String& newPin);

 private:
  Preferences prefs_;
  bool masterConfigured_ = false;
  uint8_t salt_[16] = {};
  uint8_t masterHash_[32] = {};
  uint8_t pinHash_[32] = {};
  size_t count_ = 0;
  bool derive(const String& pin, uint8_t out[32]) const;
  bool verifyHash(const uint8_t hash[32]) const;
};
