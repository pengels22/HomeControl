#include "pin_store.h"
#include "mbedtls/pkcs5.h"
#include "mbedtls/md.h"
#include "esp_system.h"

namespace { constexpr uint32_t ITERATIONS = 12000; }

bool PinStore::begin(const char* ns) {
  if (!prefs_.begin(ns, false)) return false;
  masterConfigured_ = prefs_.getBool("master", false);
  prefs_.getBytes("salt", salt_, sizeof(salt_));
  prefs_.getBytes("master_hash", masterHash_, sizeof(masterHash_));
  count_ = prefs_.getBytes("pin_hash", pinHash_, sizeof(pinHash_)) == sizeof(pinHash_) ? 1 : 0;
  return true;
}

bool PinStore::derive(const String& pin, uint8_t out[32]) const {
  mbedtls_md_context_t context;
  mbedtls_md_init(&context);
  const mbedtls_md_info_t* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  const bool ready = info != nullptr && mbedtls_md_setup(&context, info, 1) == 0;
  const int result = ready ? mbedtls_pkcs5_pbkdf2_hmac(&context,
      reinterpret_cast<const unsigned char*>(pin.c_str()), pin.length(), salt_, sizeof(salt_), ITERATIONS, 32, out) : -1;
  mbedtls_md_free(&context);
  return result == 0;
}

bool PinStore::verifyHash(const uint8_t hash[32]) const {
  uint8_t expected[32];
  memcpy(expected, masterHash_, sizeof(expected));
  return memcmp(expected, hash, sizeof(expected)) == 0 || memcmp(pinHash_, hash, sizeof(expected)) == 0;
}

bool PinStore::provisionMaster(const String& pin) {
  if (masterConfigured_ || pin.length() < 4 || pin.length() > 12) return false;
  esp_fill_random(salt_, sizeof(salt_));
  if (!derive(pin, masterHash_)) return false;
  prefs_.putBytes("salt", salt_, sizeof(salt_)); prefs_.putBytes("master_hash", masterHash_, sizeof(masterHash_));
  prefs_.putBool("master", true); masterConfigured_ = true; return true;
}

bool PinStore::addPin(const String& pin) {
  if (!masterConfigured_ || pin.length() < 4 || pin.length() > 12 || count_ >= 1) return false;
  if (!derive(pin, pinHash_)) return false;
  prefs_.putBytes("pin_hash", pinHash_, sizeof(pinHash_)); count_ = 1; return true;
}

bool PinStore::verify(const String& pin) const {
  if (!masterConfigured_) return false;
  uint8_t hash[32]; return derive(pin, hash) && verifyHash(hash);
}

bool PinStore::changeMaster(const String& oldPin, const String& newPin) {
  if (!verify(oldPin) || newPin.length() < 4 || newPin.length() > 12) return false;
  uint8_t hash[32]; if (!derive(newPin, hash)) return false;
  memcpy(masterHash_, hash, sizeof(hash)); prefs_.putBytes("master_hash", masterHash_, sizeof(masterHash_)); return true;
}
