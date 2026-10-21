#include <Arduino.h>
#include <Ethernet.h>
#include <SD.h>
#include <SPI.h>
#include <Preferences.h>
#include <esp_task_wdt.h>
#include "board_config.h"
#include "alarm_types.h"
#include "protocol.h"
#include "ui_controller.h"

namespace {
byte macAddress[6] = {0x02, 0x4b, 0x50, 0x44, 0x00, 0x01};
EthernetClient acm;
Preferences config;
String keypadId = "keypad-001", hostname = "House Entry";
bool localSiren = false, acmAvailable = false;
KeypadUiModel uiModel;
KeypadDisplayBoundary display;
KeypadUiController uiController(uiModel, display);
uint32_t lastHeartbeat = 0, lastInput = 0;
bool inputState[8] = {};
uint8_t frameHeader[4] = {}; uint8_t frameHeaderUsed = 0; uint32_t frameLength = 0; String framePayload;
uint32_t toneUntil = 0;
void toneFeedback(uint16_t frequency, uint16_t duration) { ledcSetup(0, frequency, 10); ledcAttachPin(acm_hw::KEYPAD_PIEZO, 0); ledcWriteTone(0, frequency); toneUntil = millis() + duration; }
void updateTone() { if (toneUntil && static_cast<int32_t>(millis() - toneUntil) >= 0) { ledcWriteTone(0, 0); toneUntil = 0; } }
void logFault(uint8_t index, bool failed) {
  if (!SD.begin(acm_hw::SD_CS)) return;
  File f = SD.open("/logs/keypad.log", FILE_APPEND); if (!f) return;
  f.printf("%lu SENSOR_%s input.%02u\n", millis(), failed ? "FAULT" : "RESTORED", index + 1); f.close();
}
void readInputs() {
  if (millis() - lastInput < 250) return; lastInput = millis();
  for (uint8_t i = 0; i < 8; ++i) { const bool value = digitalRead(acm_hw::KEYPAD_INPUT_PINS[i]) == LOW; if (value != inputState[i]) { inputState[i] = value; logFault(i, value); } }
}
void connectAcm() {
  if (acm.connected()) { acmAvailable = true; return; }
  acm.stop(); String host = config.getString("acm_host", ""); uint16_t port = config.getUShort("acm_port", 6502);
  acmAvailable = host.length() && acm.connect(host.c_str(), port);
  uiController.setAcmConnected(acmAvailable);
  if (!acmAvailable) toneFeedback(220, 40);
}
void sendIntent(const char* intent, const String& detail = "") {
  if (!acm.connected()) return;
  acm_protocol::sendFrame(acm, "KEYPAD_REQUEST", String("{\"keypad_id\":\"") + keypadId + "\",\"intent\":\"" + intent + "\",\"detail\":\"" + detail + "\"}");
}
void receiveFrames() {
  while (acm.available()) {
    if (frameHeaderUsed < sizeof(frameHeader)) { frameHeader[frameHeaderUsed++] = acm.read(); if (frameHeaderUsed < sizeof(frameHeader)) continue;
      frameLength = ((uint32_t)frameHeader[0] << 24) | ((uint32_t)frameHeader[1] << 16) | ((uint32_t)frameHeader[2] << 8) | frameHeader[3]; framePayload = ""; }
    while (framePayload.length() < frameLength && acm.available()) framePayload += static_cast<char>(acm.read());
    if (framePayload.length() < frameLength) return;
    if (framePayload.indexOf("LOCAL_SIREN_ON") >= 0) { localSiren = true; digitalWrite(acm_hw::KEYPAD_SIREN, HIGH); }
    if (framePayload.indexOf("LOCAL_SIREN_OFF") >= 0) { localSiren = false; digitalWrite(acm_hw::KEYPAD_SIREN, LOW); }
    frameHeaderUsed = 0; frameLength = 0; framePayload = "";
  }
}
}

void setup() {
  Serial.begin(115200); config.begin("keypad", false); keypadId = config.getString("device_id", keypadId); hostname = config.getString("hostname", hostname);
  for (uint8_t i = 0; i < 8; ++i) pinMode(acm_hw::KEYPAD_INPUT_PINS[i], INPUT_PULLUP); pinMode(acm_hw::KEYPAD_PANIC, INPUT_PULLUP); pinMode(acm_hw::KEYPAD_SIREN, OUTPUT); digitalWrite(acm_hw::KEYPAD_SIREN, LOW);
  SPI.begin(acm_hw::ETH_SCK, acm_hw::ETH_MISO, acm_hw::ETH_MOSI, acm_hw::ETH_CS); Ethernet.init(acm_hw::ETH_CS); Ethernet.begin(macAddress); SD.begin(acm_hw::SD_CS, SPI);
  esp_task_wdt_init(10, true); esp_task_wdt_add(nullptr);
  uiController.begin();
}
void loop() {
  const uint32_t now = millis(); esp_task_wdt_reset(); readInputs(); updateTone();
  if (digitalRead(acm_hw::KEYPAD_PANIC) == LOW) { sendIntent("PANIC"); toneFeedback(880, 80); while (digitalRead(acm_hw::KEYPAD_PANIC) == LOW) delay(5); }
  if (now - lastHeartbeat >= acm_protocol::HEARTBEAT_INTERVAL_MS) { lastHeartbeat = now; connectAcm(); if (acm.connected()) acm_protocol::sendHeartbeat(acm, keypadId, hostname, now); }
  receiveFrames();
  delay(1);
}
