#include "event_logger.h"
#include <sys/time.h>

namespace {
void configureTimezone() { setenv("TZ", "EST5EDT,M3.2.0/2,M11.1.0/2", 1); tzset(); }
}

void EventLogger::begin() {
  configureTimezone();
  started_=true;
  sd_ready_=SD.begin(cs_pin_);
  sd_failed_=!sd_ready_; had_sd_failure_=sd_failed_;
  next_sd_retry_=millis()+SD_RETRY_MS;
}

bool EventLogger::ensureStorage(uint32_t now) {
  if (!started_) begin();
  if (sd_ready_) return true;
  if (static_cast<int32_t>(now-next_sd_retry_) < 0) return false;
  next_sd_retry_=now+SD_RETRY_MS;
  sd_ready_=SD.begin(cs_pin_);
  if (sd_ready_) { /* retain had_sd_failure_ so restoration can be audited */ }
  return sd_ready_;
}

String EventLogger::localDate(uint32_t now) const {
  if (!time_synced_) return "";
  time_t current=time(nullptr); struct tm local{}; localtime_r(&current,&local);
  char buffer[16]; strftime(buffer,sizeof(buffer),"%Y-%m-%d",&local); (void)now; return String(buffer);
}
String EventLogger::monthlyPath(uint32_t now) const {
  time_t current=time(nullptr); struct tm local{}; localtime_r(&current,&local);
  char buffer[24]; strftime(buffer,sizeof(buffer),"/logs/%Y-%m.log",&local); (void)now; return String(buffer);
}
String EventLogger::timestamp(uint32_t now) const {
  if (!time_synced_) return String("UNSYNC+")+String(now)+"ms";
  time_t current=time(nullptr); struct tm local{}; localtime_r(&current,&local);
  char buffer[24]; strftime(buffer,sizeof(buffer),"%Y-%m-%d %H:%M:%S",&local); return String(buffer);
}

bool EventLogger::writeLine(const String& line) {
  File file=SD.open(time_synced_ ? monthlyPath(millis()) : String("/logs/unsynced.log"),FILE_APPEND);
  if (!file) { sd_ready_=false; sd_failed_=true; had_sd_failure_=true; next_sd_retry_=millis()+SD_RETRY_MS; return false; }
  const size_t written=file.println(line); file.close();
  if (written==0) { sd_ready_=false; sd_failed_=true; had_sd_failure_=true; next_sd_retry_=millis()+SD_RETRY_MS; return false; }
  return true;
}

bool EventLogger::writeSeparatorIfNeeded(uint32_t now) {
  const String date=localDate(now); if (!date.length() || date==last_date_) return true;
  File file=SD.open(monthlyPath(now),FILE_APPEND); if (!file) return false;
  file.println("*****"); file.println(date); file.println("*****"); file.close(); last_date_=date; return true;
}

bool EventLogger::log(const String& event,const String& metadata) {
  const uint32_t now=millis(); if(!ensureStorage(now)) return false;
  if(!writeSeparatorIfNeeded(now)) { sd_ready_=false; sd_failed_=true; had_sd_failure_=true; next_sd_retry_=now+SD_RETRY_MS; return false; }
  if (had_sd_failure_) { if(writeLine(String(timestamp(now))+" SD_LOGGING_RESTORED")){had_sd_failure_=false;sd_failed_=false;} }
  String line=timestamp(now)+" "+event; if(metadata.length()){line+=' ';line+=metadata;} return writeLine(line);
}

bool EventLogger::setTime(uint32_t unix_seconds,uint32_t now) {
  if(unix_seconds<1609459200UL || unix_seconds>4102444800UL) return false;
  struct timeval tv{static_cast<time_t>(unix_seconds),0}; if(settimeofday(&tv,nullptr)!=0)return false;
  configureTimezone(); const bool was=time_synced_; time_synced_=true; had_time_sync_=true; last_sync_millis_=now;
  if(!was) time_restored_pending_=true; return true;
}

void EventLogger::tick(uint32_t now) {
  if(time_synced_ && static_cast<uint32_t>(now-last_sync_millis_)>=TIME_STALE_MS){time_synced_=false;time_lost_pending_=true;}
  if(!sd_ready_ && static_cast<int32_t>(now-next_sd_retry_)>=0)ensureStorage(now);
}
bool EventLogger::takeTimeLost(){const bool value=time_lost_pending_;time_lost_pending_=false;return value;}
bool EventLogger::takeTimeRestored(){const bool value=time_restored_pending_;time_restored_pending_=false;return value;}
String EventLogger::localTime() const {if(!time_synced_)return "";time_t current=time(nullptr);struct tm local{};localtime_r(&current,&local);char buffer[24];strftime(buffer,sizeof(buffer),"%Y-%m-%d %H:%M:%S",&local);return String(buffer)+" America/Detroit";}
String EventLogger::recentLines(uint16_t max_lines){if(!sd_ready_||!max_lines)return "";File file=SD.open(time_synced_?monthlyPath(millis()):String("/logs/unsynced.log"),FILE_READ);if(!file)return "";const size_t size=file.size();const size_t start=size>8192?size-8192:0;file.seek(start);if(start)file.readStringUntil('\n');String lines[100];uint16_t count=0;while(file.available()){String line=file.readStringUntil('\n');if(count<100)lines[count++]=line;else{for(uint16_t i=1;i<100;++i)lines[i-1]=lines[i];lines[99]=line;}}file.close();if(max_lines>100)max_lines=100;String out;const uint16_t begin=count>max_lines?count-max_lines:0;for(uint16_t i=begin;i<count;++i){out+=lines[i];if(i+1<count)out+='\n';}return out;}
