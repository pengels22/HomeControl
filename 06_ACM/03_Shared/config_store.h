#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include "alarm_types.h"

struct AreaRecord { uint16_t id=0; String name; };
struct ChannelRecord { uint8_t index=0; String name; uint16_t area_id=0; SensorType type=SensorType::OPENING; };
struct RelayRecord { uint8_t index=0; String name; uint16_t area_id=0; bool siren=false; };

class ConfigStore {
 public:
  static constexpr uint8_t SCHEMA_VERSION=1, MAX_AREAS=32, MAX_CHANNELS=24, MAX_RELAYS=8;
  bool begin(const char* ns="acm_config");
  uint8_t areaCount() const { return area_count_; } const AreaRecord& area(uint8_t i) const { return areas_[i]; }
  const ChannelRecord& channel(uint8_t i) const { return channels_[i]; }
  const RelayRecord& relay(uint8_t i) const { return relays_[i]; }
  uint8_t addArea(const String& name); bool renameArea(uint16_t id,const String& name);
  bool saveChannel(const ChannelRecord& value); bool saveRelay(const RelayRecord& value);
 private:
  Preferences prefs_; uint8_t area_count_=0; AreaRecord areas_[MAX_AREAS]; ChannelRecord channels_[MAX_CHANNELS]; RelayRecord relays_[MAX_RELAYS];
  void seedDefaults(); void load(); void persistArea(uint8_t i); void persistChannel(uint8_t i); void persistRelay(uint8_t i);
};
