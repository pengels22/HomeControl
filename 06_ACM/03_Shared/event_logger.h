#pragma once
#include <Arduino.h>
#include <SD.h>
#include <time.h>

class EventLogger {
 public:
  enum class TimeStatus : uint8_t { NEVER_SYNCHRONIZED, SYNCHRONIZED, STALE };
  static constexpr uint32_t SD_RETRY_MS = 30000;
  static constexpr uint32_t TIME_STALE_MS = 15UL * 60UL * 1000UL;
  explicit EventLogger(uint8_t cs_pin) : cs_pin_(cs_pin) {}
  void begin();
  void tick(uint32_t now = millis());
  bool log(const String& event, const String& metadata = "");
  bool setTime(uint32_t unix_seconds, uint32_t now = millis());
  bool timeSynchronized() const { return time_synced_; }
  TimeStatus timeStatus() const { return time_synced_ ? TimeStatus::SYNCHRONIZED : (had_time_sync_ ? TimeStatus::STALE : TimeStatus::NEVER_SYNCHRONIZED); }
  String localTime() const;
  bool takeTimeLost();
  bool takeTimeRestored();
  bool sdFailed() const { return sd_failed_; }
  String recentLines(uint16_t max_lines = 100);
 private:
  uint8_t cs_pin_;
  bool started_=false, sd_ready_=false, sd_failed_=false, had_sd_failure_=false, time_synced_=false, had_time_sync_=false;
  bool time_lost_pending_=false, time_restored_pending_=false;
  uint32_t last_sync_millis_=0, next_sd_retry_=0;
  String last_date_;
  bool ensureStorage(uint32_t now);
  bool writeLine(const String& line);
  String timestamp(uint32_t now) const;
  String localDate(uint32_t now) const;
  String monthlyPath(uint32_t now) const;
  bool writeSeparatorIfNeeded(uint32_t now);
};
