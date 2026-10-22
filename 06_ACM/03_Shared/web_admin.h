#pragma once

#include <Arduino.h>
#include <Ethernet.h>
#include "alarm_core.h"
#include "config_store.h"
#include "event_logger.h"
#include "keypad_manager.h"
#include "pin_store.h"
#include "protocol.h"

// Small, bounded HTTP administration surface for the trusted local ACM network.
class AcmWebAdmin {
 public:
  static constexpr uint16_t PORT = 80;
  static constexpr uint32_t SESSION_IDLE_MS = 300000UL;
  class Server final : public EthernetServer { public: explicit Server(uint16_t port) : EthernetServer(port) {} void begin(uint16_t port=0) override { (void)port; EthernetServer::begin(); } };
  AcmWebAdmin() : server_(PORT) {}
  void begin(ConfigStore& config, PinStore& pins, AlarmCore& core, KeypadManager& keypads, EventLogger& logger, const String& hostname = "ACM", const String& device_id = "acm-001");
  void tick(uint32_t now = millis());
  void setHcmConnected(bool connected) { hcm_connected_=connected; }
  void setMcpHealthy(bool healthy) { mcp_healthy_=healthy; }
  void setEthernetMac(const String& mac) { ethernet_mac_=mac; }
 private:
  struct Session { bool used=false; String id; String csrf; uint32_t last=0; };
  Server server_; EthernetClient client_; bool active_=false; String request_; String body_; String cookie_; String method_; String path_; String query_; uint32_t request_started_=0; uint32_t last_failure_=0; uint8_t failures_=0;
  Session sessions_[4]; ConfigStore* config_=nullptr; PinStore* pins_=nullptr; AlarmCore* core_=nullptr; KeypadManager* keypads_=nullptr; EventLogger* logger_=nullptr; String hostname_, device_id_, ethernet_mac_; bool hcm_connected_=false, mcp_healthy_=false;
  void close(); void handle(); bool parseRequest(); bool authenticated(Session*& session); Session* findSession(const String& id); Session* createSession(); void expire(Session& session);
  void response(uint16_t status,const String& type,const String& content,const String& extra=""); void redirect(const String& location,const String& extra="");
  void loginPage(const String& error=""); void page(const String& tab); void applyMutation(Session& session);
  String htmlEscape(const String& value) const; String field(const String& key) const; String queryField(const String& key) const; String urlDecode(const String& value) const; String token() const; String nav(const String& active) const; String statusHeader() const; String typeName(SensorType type) const; String areaName(uint16_t id) const;
  bool requireCsrf(const Session& session) const; void audit(const String& event,const String& metadata="");
};
