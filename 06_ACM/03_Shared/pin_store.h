#pragma once
#include <Arduino.h>
#include <Preferences.h>
enum class PinRole : uint8_t { MASTER = 0, STANDARD = 1 };
struct PinAuthResult { bool valid=false; uint8_t pin_id=0xff; String friendly_name; PinRole role=PinRole::STANDARD; };
class PinStore {
 public:
  static constexpr uint8_t MAX_RECORDS=16;
  bool begin(const char* ns="alarm"); bool hasMaster() const { return count_>0 && enabled_[0]; }
  PinAuthResult authenticate(const String& pin) const; bool verify(const String& pin) const { return authenticate(pin).valid; }
  bool isMaster(const String& pin) const; bool provisionMaster(const String& pin,const String& name="Master PIN");
  bool addPin(const String& master,const String& pin,const String& name="Standard PIN"); bool removePin(const String& master,uint8_t pinId); bool changeMaster(const String& oldPin,const String& newPin);
  uint8_t count() const { return count_; } const String& name(uint8_t id) const { return names_[id<MAX_RECORDS?id:0]; } PinRole role(uint8_t id) const { return roles_[id<MAX_RECORDS?id:0]; }
 private:
  Preferences prefs_; uint8_t count_=0; uint8_t salts_[MAX_RECORDS][16]={}; uint8_t hashes_[MAX_RECORDS][32]={}; PinRole roles_[MAX_RECORDS]={}; bool enabled_[MAX_RECORDS]={}; String names_[MAX_RECORDS];
  bool derive(const String& pin,const uint8_t salt[16],uint8_t out[32]) const; bool validPin(const String& pin) const { return pin.length()>=4 && pin.length()<=12; } bool persist(uint8_t id);
};
