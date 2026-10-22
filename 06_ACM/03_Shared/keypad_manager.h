#pragma once
#include <Arduino.h>
#include <Ethernet.h>
#include "alarm_core.h"
#include "config_store.h"
#include "protocol.h"

class KeypadManager {
 public:
  static constexpr uint32_t OFFLINE_AFTER_MS = 90000;
  static constexpr uint32_t RECONNECT_BACKOFF_MS = 5000;
  void begin(ConfigStore& config, AlarmCore& core);
  void tick(uint32_t now);
  bool authorized(const String& mac) const;
  int8_t enrollIdentity(const String& mac, const String& ip, const String& name, const String& firmware);
  bool enrollKeypad(const IPAddress& ip, uint16_t port = acm_protocol::KEYPAD_PORT);
  bool receiveHeartbeat(const String& mac, const String& ip, uint32_t now);
  bool receiveSnapshot(const String& mac, const bool open[8], uint32_t now);
  bool receiveUpdate(const String& mac, uint8_t channel, bool open, uint32_t now);
  void broadcastAlarmState(const AlarmSnapshot& snapshot);
  bool online(uint8_t index) const { return index < ConfigStore::MAX_KEYPADS && runtime_[index].online; }
  uint8_t logicalSlot(uint8_t keypadIndex, uint8_t input) const { return 24 + keypadIndex * 8 + input; }
 private:
  struct Runtime { bool connected=false; bool online=false; bool snapshot_pending=false; uint32_t last_heartbeat=0; uint32_t next_attempt=0; };
  Runtime runtime_[ConfigStore::MAX_KEYPADS];
  EthernetClient clients_[ConfigStore::MAX_KEYPADS];
  acm_protocol::FrameParser parsers_[ConfigStore::MAX_KEYPADS];
  ConfigStore* config_=nullptr; AlarmCore* core_=nullptr;
  AlarmState alarm_state_=AlarmState::DISARMED;
  void setFault(uint8_t keypadIndex, bool fault);
  void connect(uint8_t index, uint32_t now);
  void process(uint8_t index, uint32_t now);
  void processFrame(uint8_t index, const String& frame, uint32_t now);
  void sendSiren(uint8_t index, bool active);
  void reconcileSiren(uint8_t index);
  static String value(const String& json, const char* key);
  static String normalizeMac(String value);
};
