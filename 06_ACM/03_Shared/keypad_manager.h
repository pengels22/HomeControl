#pragma once
#include <Arduino.h>
#include <Ethernet.h>
#include "alarm_core.h"
#include "config_store.h"

class KeypadManager {
 public:
  static constexpr uint32_t OFFLINE_AFTER_MS=90000;
  void begin(ConfigStore& config, AlarmCore& core);
  void tick(uint32_t now);
  bool authorized(const String& mac) const;
  int8_t enrollIdentity(const String& mac, const String& ip, const String& name, const String& firmware);
  bool receiveHeartbeat(const String& mac, const String& ip, uint32_t now);
  bool receiveSnapshot(const String& mac, const bool open[8], uint32_t now);
  uint8_t logicalSlot(uint8_t keypadIndex, uint8_t input) const { return 24 + keypadIndex * 8 + input; }
 private:
  struct Runtime { bool online=false; bool snapshot_pending=false; uint32_t last_heartbeat=0; } runtime_[ConfigStore::MAX_KEYPADS];
  ConfigStore* config_=nullptr; AlarmCore* core_=nullptr;
  void setFault(uint8_t keypadIndex, bool fault);
};
