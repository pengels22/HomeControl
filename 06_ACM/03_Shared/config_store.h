#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include "alarm_types.h"

struct AreaRecord { uint16_t id=0; String name; };
struct ChannelRecord { uint8_t index=0; String name; uint16_t area_id=0; SensorType type=SensorType::OPENING; };
struct RelayRecord { uint8_t index=0; String name; uint16_t area_id=0; bool siren=false; };
struct KeypadRecord { bool authorized=false; String mac; String name; String ip; uint16_t area_id=0; String firmware; String input_names[8]; SensorType input_types[8] = {}; };
struct RoomRecord { String name; bool custom=false; };
enum class ConfigStatus : uint8_t { FRESH, CURRENT, MIGRATED, RECOVERY_REQUIRED };

class ConfigStore {
 public:
  // Slots 0-23 are local ACM inputs; the remaining 56 slots support seven
  // complete eight-input keypads without exceeding AlarmCore's 80-slot pool.
  static constexpr uint8_t SCHEMA_VERSION=2, MAX_AREAS=32, MAX_CHANNELS=24, MAX_RELAYS=8, MAX_KEYPADS=7, MAX_ROOMS=48;
  bool begin(const char* ns="acm_config");
  ConfigStatus status() const { return status_; }
  bool recoveryRequired() const { return status_ == ConfigStatus::RECOVERY_REQUIRED; }
  uint8_t areaCount() const { return area_count_; } const AreaRecord& area(uint8_t i) const { return areas_[i]; }
  const ChannelRecord& channel(uint8_t i) const { return channels_[i]; }
  const RelayRecord& relay(uint8_t i) const { return relays_[i]; }
  const KeypadRecord& keypad(uint8_t i) const { return keypads_[i]; }
  uint8_t keypadCount() const { return keypad_count_; }
  uint8_t roomCount() const { return room_count_; } const RoomRecord& room(uint8_t i) const { return rooms_[i]; }
  int8_t findKeypad(const String& mac) const;
  int8_t saveKeypad(const KeypadRecord& value);
  bool removeKeypad(uint8_t index);
  uint8_t addArea(const String& name); bool renameArea(uint16_t id,const String& name);
  bool saveChannel(const ChannelRecord& value); bool saveRelay(const RelayRecord& value);
  bool addRoom(const String& name);
 private:
  Preferences prefs_; ConfigStatus status_=ConfigStatus::FRESH; uint8_t area_count_=0, keypad_count_=0, room_count_=0; AreaRecord areas_[MAX_AREAS]; ChannelRecord channels_[MAX_CHANNELS]; RelayRecord relays_[MAX_RELAYS]; KeypadRecord keypads_[MAX_KEYPADS]; RoomRecord rooms_[MAX_ROOMS];
  void seedDefaults(); void seedRooms(); void load(); void persistArea(uint8_t i); void persistChannel(uint8_t i); void persistRelay(uint8_t i);
};
