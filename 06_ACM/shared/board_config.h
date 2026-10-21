#pragma once

#include <Arduino.h>

namespace acm_hw {
constexpr uint8_t ETH_CS = 10;
constexpr uint8_t ETH_MOSI = 11;
constexpr uint8_t ETH_MISO = 12;
constexpr uint8_t ETH_SCK = 13;
constexpr uint8_t ETH_RST = 9;
constexpr uint8_t ETH_INT = 14;
constexpr uint8_t SD_CS = 4;
constexpr uint8_t SD_MISO = 5;
constexpr uint8_t SD_MOSI = 6;
constexpr uint8_t SD_SCK = 7;
constexpr uint8_t I2C_SDA = 8;
constexpr uint8_t I2C_SCL = 18;
constexpr uint8_t MCP_ACM_INPUTS = 0x20;
constexpr uint8_t MCP_ACM_RELAYS = 0x21;
constexpr uint8_t KEYPAD_PANIC = 16;
constexpr uint8_t KEYPAD_PIEZO = 17;
constexpr uint8_t KEYPAD_SIREN = 15;
// Keypad input header allocation is board-revision dependent. These are the
// currently reserved ESP32-S3 GPIOs and must be confirmed against the final
// keypad PCB before production flashing. They avoid Ethernet, SD, I2C, panic,
// piezo, and siren pins above.
constexpr uint8_t KEYPAD_INPUT_PINS[8] = {35, 36, 37, 38, 39, 40, 41, 42};
// Display controller/pins are intentionally isolated until the LCD variant is confirmed.
constexpr int TOUCH_CS = -1;
constexpr int TOUCH_IRQ = -1;
constexpr int DISPLAY_CS = -1;
constexpr int DISPLAY_DC = -1;
constexpr int DISPLAY_RST = -1;
constexpr int DISPLAY_SCK = -1;
constexpr int DISPLAY_MOSI = -1;
constexpr int DISPLAY_MISO = -1;
constexpr int DISPLAY_WIDTH = 480;
constexpr int DISPLAY_HEIGHT = 320;
}
