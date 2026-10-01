/*
  HCM RMC Nano Firmware
  =====================
  Room Monitoring Cluster (RMC) for the HCM House Control System.

  Hardware:
    - Arduino Nano (ATmega328P)
    - MCP2515 CAN controller + TJA1050 transceiver
    - BH1750 / GY-302 ambient light sensor
    - AHT21 temperature/humidity sensor
    - ENS160 air-quality sensor
    - RCWL-0516 presence sensor
    - 4-position DIP address switch (0-15)

  Pinned Nano pin map:
    D0/D1  - USB serial reserved
    D2     - MCP2515 INT
    D3     - RCWL-0516 presence
    D4-D7  - DIP address bits 0-3
    D8/D9  - spare
    D10    - MCP2515 CS
    D11    - SPI MOSI
    D12    - SPI MISO
    D13    - SPI SCK
    A0-A3  - spare analog
    A4     - I2C SDA
    A5     - I2C SCL
    A6/A7  - spare analog

  CAN v1 IDs:
    Telemetry:   0x1N0
    Heartbeat:   0x2N0
    Fault:       0x3N0
    Fault clear: 0x4N0

  where N is the 4-bit DIP address (0x0-0xF).

  Telemetry frame (8 bytes):
    B0 = status flags
         bit0 presence
         bit1 BH1750 healthy
         bit2 AHT21 healthy
         bit3 ENS160 healthy
         bit4 CAN initialized
         bit5 any sensor fault
         bit6 reserved
         bit7 reserved
    B1 = rounded temperature C + 40
    B2 = rounded relative humidity %
    B3 = lux high byte
    B4 = lux low byte
    B5 = ENS160 AQI (1-5, 0 if unavailable)
    B6 = reserved
    B7 = reserved

  Notes:
    - DIP address is sampled once during startup.
    - RMC is sensor-only; no output control is performed here.
    - Timing and CAN physical settings were not previously pinned. They are
      intentionally grouped below as configuration constants.
    - Requires the "MCP_CAN_lib" / mcp_can.h library (Cory J. Fowler style API).
*/

#include <Wire.h>
#include <SPI.h>
#include <mcp_can.h>

// -----------------------------------------------------------------------------
// USER / BUS CONFIGURATION
// -----------------------------------------------------------------------------

// MCP2515 hardware
static const uint8_t PIN_CAN_INT = 2;
static const uint8_t PIN_CAN_CS  = 10;

// RMC inputs
static const uint8_t PIN_PRESENCE = 3;
static const uint8_t PIN_DIP0 = 4;
static const uint8_t PIN_DIP1 = 5;
static const uint8_t PIN_DIP2 = 6;
static const uint8_t PIN_DIP3 = 7;

// These two values MUST match the MCP2515 board / SIM bus.
// Common MCP2515 modules are 8 MHz or 16 MHz.
// Change only here if your hardware differs.
#define RMC_CAN_SPEED CAN_250KBPS
#define RMC_MCP_CLOCK MCP_8MHZ

// Reporting defaults. These were not previously pinned and may be changed here.
static const unsigned long TELEMETRY_INTERVAL_MS = 5000UL;
static const unsigned long HEARTBEAT_INTERVAL_MS = 10000UL;
static const unsigned long SENSOR_RETRY_INTERVAL_MS = 5000UL;

// Presence transitions are sent immediately.
static const bool SEND_IMMEDIATE_PRESENCE = true;

// Serial diagnostics
static const unsigned long SERIAL_BAUD = 115200UL;

// -----------------------------------------------------------------------------
// I2C ADDRESSES / SENSOR CONSTANTS
// -----------------------------------------------------------------------------

// BH1750 / GY-302 default address with ADDR low
static const uint8_t BH1750_ADDR = 0x23;

// AHT21 default address
static const uint8_t AHT21_ADDR = 0x38;

// ENS160 common default address.
// If your board straps ADDR high, this may be 0x53 instead.
static const uint8_t ENS160_ADDR = 0x52;

// ENS160 register map
static const uint8_t ENS160_REG_PART_ID = 0x00;
static const uint8_t ENS160_REG_OPMODE  = 0x10;
static const uint8_t ENS160_REG_DATA_STATUS = 0x20;
static const uint8_t ENS160_REG_DATA_AQI = 0x21;
static const uint8_t ENS160_REG_TEMP_IN = 0x13;
static const uint8_t ENS160_REG_RH_IN   = 0x15;

static const uint8_t ENS160_OPMODE_STANDARD = 0x02;

// -----------------------------------------------------------------------------
// CAN OBJECT / IDS
// -----------------------------------------------------------------------------

MCP_CAN CAN0(PIN_CAN_CS);

uint8_t rmcAddress = 0;

uint16_t canIdTelemetry()  { return 0x100U | ((uint16_t)rmcAddress << 4); }
uint16_t canIdHeartbeat()  { return 0x200U | ((uint16_t)rmcAddress << 4); }
uint16_t canIdFault()      { return 0x300U | ((uint16_t)rmcAddress << 4); }
uint16_t canIdFaultClear() { return 0x400U | ((uint16_t)rmcAddress << 4); }

// -----------------------------------------------------------------------------
// FAULT BITS
// -----------------------------------------------------------------------------

enum FaultBits : uint8_t {
  FAULT_BH1750 = 0x01,
  FAULT_AHT21  = 0x02,
  FAULT_ENS160 = 0x04,
  FAULT_CAN    = 0x08
};

uint8_t activeFaults = 0;
uint8_t lastReportedFaults = 0xFF; // force initial fault state report

// -----------------------------------------------------------------------------
// SENSOR STATE
// -----------------------------------------------------------------------------

bool canReady = false;
bool bh1750Healthy = false;
bool aht21Healthy = false;
bool ens160Healthy = false;

bool presenceState = false;
bool lastPresenceState = false;

float temperatureC = 0.0f;
float humidityPct = 0.0f;
float luxValue = 0.0f;
uint8_t ens160Aqi = 0;

unsigned long lastTelemetryMs = 0;
unsigned long lastHeartbeatMs = 0;
unsigned long lastSensorRetryMs = 0;

// -----------------------------------------------------------------------------
// LOW-LEVEL I2C HELPERS
// -----------------------------------------------------------------------------

bool i2cWrite8(uint8_t addr, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(value);
  return (Wire.endTransmission() == 0);
}

bool i2cWrite16LE(uint8_t addr, uint8_t reg, uint16_t value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write((uint8_t)(value & 0xFF));
  Wire.write((uint8_t)((value >> 8) & 0xFF));
  return (Wire.endTransmission() == 0);
}

bool i2cRead(uint8_t addr, uint8_t reg, uint8_t *buf, uint8_t len) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;

  uint8_t got = Wire.requestFrom((int)addr, (int)len);
  if (got != len) {
    while (Wire.available()) (void)Wire.read();
    return false;
  }

  for (uint8_t i = 0; i < len; i++) {
    buf[i] = Wire.read();
  }
  return true;
}

// -----------------------------------------------------------------------------
// DIP ADDRESS
// -----------------------------------------------------------------------------

uint8_t readDipAddress() {
  // INPUT_PULLUP means ON-to-GND reads LOW.
  // Treat ON/LOW as binary 1.
  uint8_t addr = 0;
  if (digitalRead(PIN_DIP0) == LOW) addr |= 0x01;
  if (digitalRead(PIN_DIP1) == LOW) addr |= 0x02;
  if (digitalRead(PIN_DIP2) == LOW) addr |= 0x04;
  if (digitalRead(PIN_DIP3) == LOW) addr |= 0x08;
  return addr;
}

// -----------------------------------------------------------------------------
// BH1750
// -----------------------------------------------------------------------------

bool initBH1750() {
  // Power on
  Wire.beginTransmission(BH1750_ADDR);
  Wire.write(0x01);
  if (Wire.endTransmission() != 0) return false;

  delay(10);

  // Continuously H-resolution mode, 1 lx resolution
  Wire.beginTransmission(BH1750_ADDR);
  Wire.write(0x10);
  return (Wire.endTransmission() == 0);
}

bool readBH1750(float &luxOut) {
  uint8_t got = Wire.requestFrom((int)BH1750_ADDR, 2);
  if (got != 2) {
    while (Wire.available()) (void)Wire.read();
    return false;
  }

  uint16_t raw = ((uint16_t)Wire.read() << 8);
  raw |= Wire.read();

  luxOut = (float)raw / 1.2f;
  return true;
}

// -----------------------------------------------------------------------------
// AHT21
// -----------------------------------------------------------------------------

bool initAHT21() {
  delay(40);

  // Soft reset
  Wire.beginTransmission(AHT21_ADDR);
  Wire.write(0xBA);
  if (Wire.endTransmission() != 0) return false;
  delay(20);

  // Check calibration/status
  Wire.requestFrom((int)AHT21_ADDR, 1);
  if (!Wire.available()) return false;
  uint8_t status = Wire.read();

  // If not calibrated, issue initialize command.
  if ((status & 0x08) == 0) {
    Wire.beginTransmission(AHT21_ADDR);
    Wire.write(0xBE);
    Wire.write(0x08);
    Wire.write(0x00);
    if (Wire.endTransmission() != 0) return false;
    delay(10);
  }

  return true;
}

bool readAHT21(float &tempOut, float &rhOut) {
  Wire.beginTransmission(AHT21_ADDR);
  Wire.write(0xAC);
  Wire.write(0x33);
  Wire.write(0x00);
  if (Wire.endTransmission() != 0) return false;

  delay(85);

  Wire.requestFrom((int)AHT21_ADDR, 6);
  if (Wire.available() < 6) {
    while (Wire.available()) (void)Wire.read();
    return false;
  }

  uint8_t data[6];
  for (uint8_t i = 0; i < 6; i++) data[i] = Wire.read();

  // Busy bit still set means conversion not ready.
  if (data[0] & 0x80) return false;

  uint32_t rawHumidity =
      ((uint32_t)data[1] << 12) |
      ((uint32_t)data[2] << 4) |
      ((uint32_t)data[3] >> 4);

  uint32_t rawTemperature =
      (((uint32_t)data[3] & 0x0F) << 16) |
      ((uint32_t)data[4] << 8) |
      (uint32_t)data[5];

  rhOut = ((float)rawHumidity * 100.0f) / 1048576.0f;
  tempOut = ((float)rawTemperature * 200.0f) / 1048576.0f - 50.0f;

  if (rhOut < 0.0f || rhOut > 100.0f) return false;
  if (tempOut < -50.0f || tempOut > 150.0f) return false;

  return true;
}

// -----------------------------------------------------------------------------
// ENS160
// -----------------------------------------------------------------------------

bool initENS160() {
  uint8_t part[2] = {0, 0};
  if (!i2cRead(ENS160_ADDR, ENS160_REG_PART_ID, part, 2)) return false;

  uint16_t partId = ((uint16_t)part[1] << 8) | part[0];

  // ENS160 PART_ID is normally 0x0160.
  if (partId != 0x0160) return false;

  if (!i2cWrite8(ENS160_ADDR, ENS160_REG_OPMODE, ENS160_OPMODE_STANDARD)) {
    return false;
  }

  delay(100);
  return true;
}

uint16_t encodeEns160Temp(float tempC) {
  // ENS160 compensation temperature:
  // Kelvin * 64, little-endian.
  float kelvin = tempC + 273.15f;
  if (kelvin < 0.0f) kelvin = 0.0f;

  long raw = lroundf(kelvin * 64.0f);
  if (raw < 0) raw = 0;
  if (raw > 65535L) raw = 65535L;
  return (uint16_t)raw;
}

uint16_t encodeEns160Humidity(float rhPct) {
  // ENS160 compensation humidity:
  // %RH * 512, little-endian.
  if (rhPct < 0.0f) rhPct = 0.0f;
  if (rhPct > 100.0f) rhPct = 100.0f;

  long raw = lroundf(rhPct * 512.0f);
  if (raw < 0) raw = 0;
  if (raw > 65535L) raw = 65535L;
  return (uint16_t)raw;
}

bool readENS160(uint8_t &aqiOut) {
  // Feed current AHT21 temperature/RH into ENS160 compensation when available.
  if (aht21Healthy) {
    (void)i2cWrite16LE(ENS160_ADDR, ENS160_REG_TEMP_IN,
                       encodeEns160Temp(temperatureC));
    (void)i2cWrite16LE(ENS160_ADDR, ENS160_REG_RH_IN,
                       encodeEns160Humidity(humidityPct));
  }

  uint8_t status = 0;
  if (!i2cRead(ENS160_ADDR, ENS160_REG_DATA_STATUS, &status, 1)) return false;

  // Read AQI regardless of NEWDAT status so the last valid value remains useful.
  uint8_t aqi = 0;
  if (!i2cRead(ENS160_ADDR, ENS160_REG_DATA_AQI, &aqi, 1)) return false;

  // ENS160 AQI is 1..5. Zero means not ready / invalid for our protocol.
  if (aqi < 1 || aqi > 5) {
    aqiOut = 0;
    return false;
  }

  aqiOut = aqi;
  return true;
}

// -----------------------------------------------------------------------------
// CAN
// -----------------------------------------------------------------------------

bool initCAN() {
  pinMode(PIN_CAN_INT, INPUT);

  byte result = CAN0.begin(MCP_ANY, RMC_CAN_SPEED, RMC_MCP_CLOCK);
  if (result != CAN_OK) {
    return false;
  }

  CAN0.setMode(MCP_NORMAL);
  delay(10);
  return true;
}

bool sendCanFrame(uint16_t id, const uint8_t *data, uint8_t len) {
  if (!canReady) return false;

  byte result = CAN0.sendMsgBuf(id, 0, len, (byte *)data);
  if (result != CAN_OK) {
    activeFaults |= FAULT_CAN;
    canReady = false;
    return false;
  }

  activeFaults &= ~FAULT_CAN;
  return true;
}

// -----------------------------------------------------------------------------
// SENSOR / FAULT MANAGEMENT
// -----------------------------------------------------------------------------

void refreshFaultMask() {
  if (bh1750Healthy) activeFaults &= ~FAULT_BH1750;
  else activeFaults |= FAULT_BH1750;

  if (aht21Healthy) activeFaults &= ~FAULT_AHT21;
  else activeFaults |= FAULT_AHT21;

  if (ens160Healthy) activeFaults &= ~FAULT_ENS160;
  else activeFaults |= FAULT_ENS160;

  if (canReady) activeFaults &= ~FAULT_CAN;
  else activeFaults |= FAULT_CAN;
}

void retryFailedHardware() {
  unsigned long now = millis();
  if ((now - lastSensorRetryMs) < SENSOR_RETRY_INTERVAL_MS) return;
  lastSensorRetryMs = now;

  if (!canReady) {
    canReady = initCAN();
  }

  if (!bh1750Healthy) {
    bh1750Healthy = initBH1750();
  }

  if (!aht21Healthy) {
    aht21Healthy = initAHT21();
  }

  if (!ens160Healthy) {
    ens160Healthy = initENS160();
  }

  refreshFaultMask();
}

void readSensors() {
  bool ok;

  float newTemp = temperatureC;
  float newRh = humidityPct;
  ok = readAHT21(newTemp, newRh);
  if (ok) {
    temperatureC = newTemp;
    humidityPct = newRh;
    aht21Healthy = true;
  } else {
    aht21Healthy = false;
  }

  float newLux = luxValue;
  ok = readBH1750(newLux);
  if (ok) {
    luxValue = newLux;
    bh1750Healthy = true;
  } else {
    bh1750Healthy = false;
  }

  uint8_t newAqi = ens160Aqi;
  ok = readENS160(newAqi);
  if (ok) {
    ens160Aqi = newAqi;
    ens160Healthy = true;
  } else {
    ens160Aqi = 0;
    ens160Healthy = false;
  }

  refreshFaultMask();
}

// -----------------------------------------------------------------------------
// FRAME BUILDERS
// -----------------------------------------------------------------------------

uint8_t buildStatusFlags() {
  uint8_t flags = 0;

  if (presenceState)  flags |= 0x01;
  if (bh1750Healthy)  flags |= 0x02;
  if (aht21Healthy)   flags |= 0x04;
  if (ens160Healthy)  flags |= 0x08;
  if (canReady)       flags |= 0x10;
  if (activeFaults & (FAULT_BH1750 | FAULT_AHT21 | FAULT_ENS160)) flags |= 0x20;

  return flags;
}

uint8_t encodeTemperature(float c) {
  long v = lroundf(c) + 40L;
  if (v < 0) v = 0;
  if (v > 255) v = 255;
  return (uint8_t)v;
}

uint8_t encodeHumidity(float rh) {
  long v = lroundf(rh);
  if (v < 0) v = 0;
  if (v > 100) v = 100;
  return (uint8_t)v;
}

uint16_t encodeLux(float lux) {
  long v = lroundf(lux);
  if (v < 0) v = 0;
  if (v > 65535L) v = 65535L;
  return (uint16_t)v;
}

void sendTelemetry() {
  uint16_t lux = encodeLux(luxValue);

  uint8_t frame[8] = {
    buildStatusFlags(),
    encodeTemperature(temperatureC),
    encodeHumidity(humidityPct),
    (uint8_t)((lux >> 8) & 0xFF),
    (uint8_t)(lux & 0xFF),
    ens160Aqi,
    0x00,
    0x00
  };

  (void)sendCanFrame(canIdTelemetry(), frame, 8);
}

void sendHeartbeat() {
  /*
    Heartbeat payload is intentionally simple because only the heartbeat ID was
    previously pinned, not its byte layout.

    B0 protocol version
    B1 RMC address
    B2 active fault mask
    B3 status flags
    B4-B7 uptime seconds, big-endian
  */
  uint32_t uptimeSec = millis() / 1000UL;

  uint8_t frame[8] = {
    0x01,
    rmcAddress,
    activeFaults,
    buildStatusFlags(),
    (uint8_t)((uptimeSec >> 24) & 0xFF),
    (uint8_t)((uptimeSec >> 16) & 0xFF),
    (uint8_t)((uptimeSec >> 8) & 0xFF),
    (uint8_t)(uptimeSec & 0xFF)
  };

  (void)sendCanFrame(canIdHeartbeat(), frame, 8);
}

void sendFaultStateIfChanged() {
  if (activeFaults == lastReportedFaults) return;

  uint8_t frame[8] = {
    activeFaults,
    buildStatusFlags(),
    rmcAddress,
    0x01,  // protocol version
    0x00,
    0x00,
    0x00,
    0x00
  };

  if (activeFaults != 0) {
    if (sendCanFrame(canIdFault(), frame, 8)) {
      lastReportedFaults = activeFaults;
    }
  } else {
    if (sendCanFrame(canIdFaultClear(), frame, 8)) {
      lastReportedFaults = activeFaults;
    }
  }
}

// -----------------------------------------------------------------------------
// SERIAL DIAGNOSTICS
// -----------------------------------------------------------------------------

void printDiagnostics() {
  Serial.print(F("RMC "));
  Serial.print(rmcAddress, HEX);
  Serial.print(F(" | P="));
  Serial.print(presenceState ? 1 : 0);
  Serial.print(F(" T="));
  Serial.print(temperatureC, 1);
  Serial.print(F("C RH="));
  Serial.print(humidityPct, 1);
  Serial.print(F("% Lux="));
  Serial.print(luxValue, 0);
  Serial.print(F(" AQI="));
  Serial.print(ens160Aqi);
  Serial.print(F(" Fault=0x"));
  if (activeFaults < 0x10) Serial.print('0');
  Serial.println(activeFaults, HEX);
}

// -----------------------------------------------------------------------------
// SETUP / LOOP
// -----------------------------------------------------------------------------

void setup() {
  Serial.begin(SERIAL_BAUD);

  pinMode(PIN_PRESENCE, INPUT);

  pinMode(PIN_DIP0, INPUT_PULLUP);
  pinMode(PIN_DIP1, INPUT_PULLUP);
  pinMode(PIN_DIP2, INPUT_PULLUP);
  pinMode(PIN_DIP3, INPUT_PULLUP);

  delay(20);
  rmcAddress = readDipAddress();

  Wire.begin();
  Wire.setClock(100000UL);

  SPI.begin();

  Serial.println();
  Serial.println(F("HCM RMC Nano starting"));
  Serial.print(F("DIP address: 0x"));
  Serial.println(rmcAddress, HEX);

  canReady = initCAN();
  bh1750Healthy = initBH1750();
  aht21Healthy = initAHT21();
  ens160Healthy = initENS160();

  presenceState = (digitalRead(PIN_PRESENCE) == HIGH);
  lastPresenceState = presenceState;

  refreshFaultMask();

  // Give sensors a moment, then get first readings.
  delay(200);
  readSensors();

  // Publish startup state immediately.
  sendTelemetry();
  sendHeartbeat();
  sendFaultStateIfChanged();

  unsigned long now = millis();
  lastTelemetryMs = now;
  lastHeartbeatMs = now;
  lastSensorRetryMs = now;

  printDiagnostics();
}

void loop() {
  unsigned long now = millis();

  // Presence is digital and may be reported immediately on transition.
  presenceState = (digitalRead(PIN_PRESENCE) == HIGH);

  if (SEND_IMMEDIATE_PRESENCE && presenceState != lastPresenceState) {
    lastPresenceState = presenceState;
    sendTelemetry();
    printDiagnostics();
  }

  // Retry hardware that is currently failed.
  retryFailedHardware();

  // Periodic environmental telemetry.
  if ((now - lastTelemetryMs) >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryMs = now;

    readSensors();
    sendFaultStateIfChanged();
    sendTelemetry();
    printDiagnostics();
  }

  // Periodic RMC health heartbeat.
  if ((now - lastHeartbeatMs) >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;

    refreshFaultMask();
    sendFaultStateIfChanged();
    sendHeartbeat();
  }
}
