#include <Arduino.h>
#include <Ethernet.h>
#include <SD.h>
#include <SPI.h>
#include <Wire.h>
#include <Preferences.h>
#include <esp_task_wdt.h>
#include "board_config.h"
#include "alarm_types.h"
#include "protocol.h"
#include "pin_store.h"
#include "alarm_core.h"
#include "config_store.h"
#include "keypad_manager.h"
#include "event_logger.h"
#include "web_admin.h"

namespace {
constexpr uint8_t MCP_IODIRA = 0x00, MCP_IODIRB = 0x01, MCP_GPPUA = 0x0c, MCP_GPPUB = 0x0d, MCP_GPIOA = 0x12, MCP_GPIOB = 0x13;
constexpr uint32_t TROUBLE_SD = 1u << 0, TROUBLE_HCM = 1u << 1, TROUBLE_SENSOR = 1u << 2, TROUBLE_CONFIG = 1u << 3;
byte macAddress[6] = {0x02, 0x41, 0x43, 0x4d, 0x00, 0x01};
EthernetClient hcm;
PinStore pins;
Preferences config;
ConfigStore configStore;
AlarmSnapshot snapshot;
AlarmCore* alarmCore = nullptr;
KeypadManager keypadManager;
EventLogger eventLogger(acm_hw::SD_CS);
AcmWebAdmin webAdmin;
acm_protocol::FrameParser hcmParser;
bool hcmWasConnected=false;
uint32_t lastTimeRequest=0;
SensorState sensors[24];
bool relayActive[ConfigStore::MAX_RELAYS] = {};
bool relaySiren[ConfigStore::MAX_RELAYS] = {};
String deviceId = "acm-001", hostname = "ACM-001";
uint32_t lastInput = 0, lastHeartbeat = 0, lastSnapshot = 0, lastLogMonth = 0;

void mcpWrite(uint8_t address, uint8_t reg, uint8_t value) { Wire.beginTransmission(address); Wire.write(reg); Wire.write(value); Wire.endTransmission(); }
void setRelay(uint8_t index, bool active) {
  if (index >= ConfigStore::MAX_RELAYS || relayActive[index] == active) return;
  relayActive[index] = active;
  uint8_t value = 0xff;
  for (uint8_t i = 0; i < ConfigStore::MAX_RELAYS; ++i) if (relayActive[i]) value &= static_cast<uint8_t>(~(1u << i));
  mcpWrite(acm_hw::MCP_ACM_RELAYS, MCP_GPIOB, value);
}
void applySirenRelays(AlarmState state) {
  const bool triggered = state == AlarmState::TRIGGERED;
  for (uint8_t i = 0; i < ConfigStore::MAX_RELAYS; ++i) {
    const bool configured = configStore.relay(i).siren;
    if (configured != relaySiren[i]) { relaySiren[i] = configured; if (!configured) setRelay(i, false); }
    if (relaySiren[i]) setRelay(i, triggered);
  }
}
uint8_t mcpRead(uint8_t address, uint8_t reg) { Wire.beginTransmission(address); Wire.write(reg); Wire.endTransmission(false); Wire.requestFrom(address, (uint8_t)1); return Wire.available() ? Wire.read() : 0xff; }
void logEvent(const char* event, uint16_t sensor = 0xffff) { String metadata; if(sensor != 0xffff) metadata=String("Channel=")+String(sensor+1); eventLogger.log(event,metadata); }
void logLocalSensor(uint8_t index,bool open){const ChannelRecord& channel=configStore.channel(index);String metadata=String("Sensor=")+channel.name+" Area="+String(channel.area_id)+" Source=ACM Channel="+String(index+1);eventLogger.log(open?"SENSOR_OPEN":"SENSOR_CLOSED",metadata);}
void scanInputs() {
  const uint8_t a = mcpRead(acm_hw::MCP_ACM_INPUTS, MCP_GPIOA), b = mcpRead(acm_hw::MCP_ACM_INPUTS, MCP_GPIOB);
  const uint32_t raw = (uint32_t)a | ((uint32_t)b << 8); const uint32_t now = millis();
  if (now - lastInput < 250) return; lastInput = now;
  for (uint8_t i = 0; i < 16; ++i) { const bool open = !(raw & (1u << i)); if (open != sensors[i].open) logLocalSensor(i, open); sensors[i].open = open; if (alarmCore) alarmCore->setSensor(i, sensors[i].open); }
  const uint8_t c = mcpRead(acm_hw::MCP_ACM_RELAYS, MCP_GPIOA);
  for (uint8_t i = 0; i < 8; ++i) { const bool open = !(c & (1u << i)); if (open != sensors[16 + i].open) logLocalSensor(16 + i, open); sensors[16 + i].open = open; if (alarmCore) alarmCore->setSensor(16 + i, sensors[16 + i].open); }
  snapshot.open_bitmap[0] = snapshot.open_bitmap[1] = snapshot.open_bitmap[2] = 0;
  for (uint8_t i = 0; i < 24; ++i) if (sensors[i].open && !sensors[i].bypassed) snapshot.open_bitmap[i / 32] |= (1u << (i % 32));
}
void initializeHardware() {
  Wire.begin(acm_hw::I2C_SDA, acm_hw::I2C_SCL); Wire.setClock(400000);
  mcpWrite(acm_hw::MCP_ACM_INPUTS, MCP_IODIRA, 0xff); mcpWrite(acm_hw::MCP_ACM_INPUTS, MCP_IODIRB, 0xff);
  mcpWrite(acm_hw::MCP_ACM_INPUTS, MCP_GPPUA, 0xff); mcpWrite(acm_hw::MCP_ACM_INPUTS, MCP_GPPUB, 0xff);
  mcpWrite(acm_hw::MCP_ACM_RELAYS, MCP_IODIRA, 0xff);
  // Relay outputs are active-low: preload HIGH while still inputs, then switch
  // to outputs so a reboot cannot energize a relay during initialization.
  mcpWrite(acm_hw::MCP_ACM_RELAYS, MCP_GPIOB, 0xff);
  mcpWrite(acm_hw::MCP_ACM_RELAYS, MCP_IODIRB, 0x00);
  SPI.begin(acm_hw::ETH_SCK, acm_hw::ETH_MISO, acm_hw::ETH_MOSI, acm_hw::ETH_CS); Ethernet.init(acm_hw::ETH_CS); Ethernet.begin(macAddress);

}
void requestHcmTime(uint32_t now){if(!hcm.connected())return;if(!lastTimeRequest||static_cast<uint32_t>(now-lastTimeRequest)>=300000UL){lastTimeRequest=now;acm_protocol::sendFrame(hcm,acm_protocol::TIME_REQUEST,"{} ");}}
void processHcmFrames(uint32_t now){while(hcm.available()){hcmParser.feed(static_cast<uint8_t>(hcm.read()));if(hcmParser.invalid()){hcmParser.reset();return;}if(hcmParser.complete()){const String frame=hcmParser.take();if(frame.indexOf("\"type\":\"TIME_RESPONSE\"")>=0){const int key=frame.indexOf("\"unix\":");if(key>=0){const uint32_t unix_seconds=static_cast<uint32_t>(frame.substring(key+7).toInt());if(eventLogger.setTime(unix_seconds,now)){if(eventLogger.takeTimeRestored()){eventLogger.log("TIME_SYNC_RESTORED");}keypadManager.setTimeSync(true,unix_seconds);}}}}}}
void connectHcm() {
  if (hcm.connected()) return;
  hcm.stop();
  // HCM endpoint is configured in NVS; absence is a normal standalone mode.
  String host = config.getString("hcm_host", ""); uint16_t port = config.getUShort("hcm_port", 6501);
  if (host.length() && hcm.connect(host.c_str(), port)) snapshot.trouble_flags &= ~TROUBLE_HCM; else snapshot.trouble_flags |= TROUBLE_HCM;
}
void sendStatus(bool full) { if (hcm.connected()) acm_protocol::sendAlarmStatus(hcm, deviceId, hostname, snapshot, full); }
}

void setup() {
  Serial.begin(115200); config.begin("acm", false); deviceId = config.getString("device_id", deviceId); hostname = config.getString("hostname", hostname);
  pins.begin("alarm"); configStore.begin(); initializeHardware(); eventLogger.begin(); snapshot.state = pins.hasMaster() ? AlarmState::DISARMED : AlarmState::TROUBLE; logEvent("ACM_BOOT");
  static AlarmCore core(pins); alarmCore = &core; alarmCore->begin(config.getUInt("home_exit_ms", 0), config.getUInt("away_exit_ms", 30000));
  for (uint8_t i = 0; i < ConfigStore::MAX_CHANNELS; ++i) { alarmCore->setSensorInUse(i, true); alarmCore->setSensorType(i, configStore.channel(i).type); }
  keypadManager.begin(configStore, *alarmCore, &eventLogger);
  webAdmin.begin(configStore, pins, *alarmCore, keypadManager, eventLogger, hostname, deviceId);
  snapshot = alarmCore->snapshot(); for (uint8_t i = 0; i < ConfigStore::MAX_RELAYS; ++i) relaySiren[i] = configStore.relay(i).siren; if (configStore.recoveryRequired()) snapshot.trouble_flags |= TROUBLE_CONFIG;
  esp_task_wdt_init(10, true); esp_task_wdt_add(nullptr);
}
void loop() {
  const uint32_t now = millis(); esp_task_wdt_reset(); webAdmin.tick(now); eventLogger.tick(now); if(eventLogger.takeTimeLost()){eventLogger.log("TIME_SYNC_LOST");keypadManager.setTimeSync(false,0);} scanInputs(); if (alarmCore) keypadManager.tick(now); if (alarmCore) { const uint32_t trouble = snapshot.trouble_flags; alarmCore->tick(now); snapshot = alarmCore->snapshot(); snapshot.trouble_flags |= trouble; applySirenRelays(snapshot.state); }
  const bool connectedBefore=hcm.connected(); if (now - lastHeartbeat >= acm_protocol::HEARTBEAT_INTERVAL_MS) { lastHeartbeat = now; connectHcm(); if (hcm.connected()) acm_protocol::sendHeartbeat(hcm, deviceId, hostname, ++snapshot.sequence); }
  const bool connected=hcm.connected(); if(connected&&!hcmWasConnected){eventLogger.log("HCM_COMMS_RESTORED");hcmWasConnected=true;hcmParser.reset();lastTimeRequest=0;} if(!connected&&hcmWasConnected){eventLogger.log("HCM_COMMS_LOST");hcmWasConnected=false;} if(connected) { requestHcmTime(now); processHcmFrames(now); } (void)connectedBefore;
  if (now - lastSnapshot >= acm_protocol::SNAPSHOT_INTERVAL_MS) { lastSnapshot = now; sendStatus(true); }
  static AlarmState previousState = AlarmState::TROUBLE; static uint32_t previousBitmap = 0; static uint32_t previousCountdown = 0xffffffff; if (snapshot.state != previousState || snapshot.open_bitmap[0] != previousBitmap || snapshot.countdown_seconds != previousCountdown) { const AlarmState oldState=previousState; previousState = snapshot.state; previousBitmap = snapshot.open_bitmap[0]; previousCountdown = snapshot.countdown_seconds; ++snapshot.sequence; if(snapshot.state!=oldState){String auditEvent,auditMetadata;const bool audited=keypadManager.takeActionAudit(auditEvent,auditMetadata);if(audited)eventLogger.log(auditEvent.c_str(),auditMetadata); else if(snapshot.state==AlarmState::ARMING_DELAY)eventLogger.log("ARMING_DELAY"); else if(snapshot.state==AlarmState::ARMED_HOME)eventLogger.log("ARMED_HOME"); else if(snapshot.state==AlarmState::ARMED_AWAY)eventLogger.log("ARMED_AWAY"); else if(snapshot.state==AlarmState::ENTRY_DELAY)eventLogger.log("ENTRY_DELAY"); else if(snapshot.state==AlarmState::TRIGGERED){String metadata;if(snapshot.trigger_sensor!=0xffff&&snapshot.trigger_sensor<ConfigStore::MAX_CHANNELS)metadata=String("Sensor=")+configStore.channel(snapshot.trigger_sensor).name+" Area="+String(configStore.channel(snapshot.trigger_sensor).area_id)+" PriorMode=ARMED_AWAY";eventLogger.log("ALARM_TRIGGERED",metadata);} else if(snapshot.state==AlarmState::DISARMED)eventLogger.log("DISARMED"); if(oldState!=AlarmState::TRIGGERED&&snapshot.state==AlarmState::TRIGGERED)eventLogger.log("SIRENS_ON"); if(oldState==AlarmState::TRIGGERED&&snapshot.state!=AlarmState::TRIGGERED)eventLogger.log("SIRENS_OFF");} sendStatus(false); keypadManager.broadcastAlarmState(snapshot); }
  if(eventLogger.sdFailed())snapshot.trouble_flags|=TROUBLE_SD; delay(1);
}
