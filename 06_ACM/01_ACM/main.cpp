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
SensorState sensors[24];
String deviceId = "acm-001", hostname = "ACM-001";
uint32_t lastInput = 0, lastHeartbeat = 0, lastSnapshot = 0, lastLogMonth = 0;

void mcpWrite(uint8_t address, uint8_t reg, uint8_t value) { Wire.beginTransmission(address); Wire.write(reg); Wire.write(value); Wire.endTransmission(); }
uint8_t mcpRead(uint8_t address, uint8_t reg) { Wire.beginTransmission(address); Wire.write(reg); Wire.endTransmission(false); Wire.requestFrom(address, (uint8_t)1); return Wire.available() ? Wire.read() : 0xff; }
void logEvent(const char* event, uint16_t sensor = 0xffff) {
  if (!SD.begin(acm_hw::SD_CS)) { snapshot.trouble_flags |= TROUBLE_SD; return; }
  String path = String("/logs/") + (lastLogMonth ? lastLogMonth : 202610) + ".log";
  File f = SD.open(path, FILE_APPEND); if (!f) { snapshot.trouble_flags |= TROUBLE_SD; return; }
  f.printf("%lu %s%s%s\n", millis(), event, sensor == 0xffff ? "" : " sensor=", sensor == 0xffff ? "" : String(sensor + 1).c_str()); f.close();
}
void scanInputs() {
  const uint8_t a = mcpRead(acm_hw::MCP_ACM_INPUTS, MCP_GPIOA), b = mcpRead(acm_hw::MCP_ACM_INPUTS, MCP_GPIOB);
  const uint32_t raw = (uint32_t)a | ((uint32_t)b << 8); const uint32_t now = millis();
  if (now - lastInput < 250) return; lastInput = now;
  for (uint8_t i = 0; i < 16; ++i) { sensors[i].open = !(raw & (1u << i)); if (alarmCore) alarmCore->setSensor(i, sensors[i].open); }
  const uint8_t c = mcpRead(acm_hw::MCP_ACM_RELAYS, MCP_GPIOA);
  for (uint8_t i = 0; i < 8; ++i) { sensors[16 + i].open = !(c & (1u << i)); if (alarmCore) alarmCore->setSensor(16 + i, sensors[16 + i].open); }
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
  if (!SD.begin(acm_hw::SD_CS, SPI)) snapshot.trouble_flags |= TROUBLE_SD;
}
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
  pins.begin("alarm"); configStore.begin(); initializeHardware(); snapshot.state = pins.hasMaster() ? AlarmState::DISARMED : AlarmState::TROUBLE; logEvent("ACM_BOOT");
  static AlarmCore core(pins); alarmCore = &core; alarmCore->begin(config.getUInt("home_exit_ms", 0), config.getUInt("away_exit_ms", 30000));
  for (uint8_t i = 0; i < ConfigStore::MAX_CHANNELS; ++i) alarmCore->setSensorType(i, configStore.channel(i).type);
  snapshot = alarmCore->snapshot(); if (configStore.recoveryRequired()) snapshot.trouble_flags |= TROUBLE_CONFIG;
  esp_task_wdt_init(10, true); esp_task_wdt_add(nullptr);
}
void loop() {
  const uint32_t now = millis(); esp_task_wdt_reset(); scanInputs(); if (alarmCore) { const uint32_t trouble = snapshot.trouble_flags; alarmCore->tick(now); snapshot = alarmCore->snapshot(); snapshot.trouble_flags |= trouble; }
  if (now - lastHeartbeat >= acm_protocol::HEARTBEAT_INTERVAL_MS) { lastHeartbeat = now; connectHcm(); if (hcm.connected()) acm_protocol::sendHeartbeat(hcm, deviceId, hostname, ++snapshot.sequence); }
  if (now - lastSnapshot >= acm_protocol::SNAPSHOT_INTERVAL_MS) { lastSnapshot = now; sendStatus(true); }
  static uint32_t previousBitmap = 0; if (snapshot.open_bitmap[0] != previousBitmap) { previousBitmap = snapshot.open_bitmap[0]; ++snapshot.sequence; sendStatus(false); }
  delay(1);
}
