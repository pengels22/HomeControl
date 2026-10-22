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
byte macAddress[6] = {0x02,0x4b,0x50,0x44,0x00,0x01};
class CompatibleEthernetServer : public EthernetServer {
 public:
  explicit CompatibleEthernetServer(uint16_t port) : EthernetServer(port) {}
  void begin(uint16_t port = 0) override { (void)port; EthernetServer::begin(); }
};
CompatibleEthernetServer keypadServer(acm_protocol::KEYPAD_PORT);
EthernetClient acm;
Preferences config;
String keypadId, hostname = "House Entry";
bool localSiren=false, acmAvailable=false;
KeypadUiModel uiModel; KeypadDisplayBoundary display; KeypadUiController uiController(uiModel,display);
uint32_t lastHeartbeat=0, toneUntil=0;
bool rawOpen[8]={}, debouncedOpen[8]={}, initialized[8]={}; uint32_t rawChangedAt[8]={};
acm_protocol::FrameParser frameParser;

String macString(){uint8_t mac[6]={};Ethernet.MACAddress(mac);String result;for(uint8_t i=0;i<6;++i){if(i)result+=':';if(mac[i]<16)result+='0';result+=String(mac[i],HEX);}return result;}
String jsonValue(const String& json,const char* key){const String needle=String("\"")+key+"\":\"";const int start=json.indexOf(needle);if(start<0)return "";const int b=start+needle.length(),e=json.indexOf('"',b);return e<0?"":json.substring(b,e);}
void toneFeedback(uint16_t frequency,uint16_t duration){ledcSetup(0,frequency,10);ledcAttachPin(acm_hw::KEYPAD_PIEZO,0);ledcWriteTone(0,frequency);toneUntil=millis()+duration;}
void updateTone(){if(toneUntil&&static_cast<int32_t>(millis()-toneUntil)>=0){ledcWriteTone(0,0);toneUntil=0;}}
void logInput(uint8_t index,bool open){if(!SD.begin(acm_hw::SD_CS))return;File f=SD.open("/logs/keypad.log",FILE_APPEND);if(!f)return;f.printf("%lu SENSOR_%s input.%02u\n",millis(),open?"OPEN":"CLOSED",index+1);f.close();}
void sendSnapshot(){if(!acm.connected())return;String payload="{\"keypad_id\":\""+keypadId+"\",\"states\":[";for(uint8_t i=0;i<8;++i){if(i)payload+=',';payload+=debouncedOpen[i]?"true":"false";}payload+="]}";acm_protocol::sendFrame(acm,acm_protocol::SENSOR_SNAPSHOT,payload);}
void sendIdentity(){String payload="{\"mac\":\""+keypadId+"\",\"ip\":\""+Ethernet.localIP().toString()+"\",\"name\":\""+hostname+"\",\"firmware\":\"acm-keypad-1.0\"}";acm_protocol::sendFrame(acm,acm_protocol::IDENTIFY_RESPONSE,payload);}
void sendUpdate(uint8_t index){if(!acm.connected())return;String payload="{\"keypad_id\":\""+keypadId+"\",\"channel\":\""+String(index+1)+"\",\"state\":\""+(debouncedOpen[index]?"OPEN":"CLOSED")+"\"}";acm_protocol::sendFrame(acm,acm_protocol::SENSOR_UPDATE,payload);}
void acceptClient(){EthernetClient candidate=keypadServer.available();if(!candidate)return;if(acm.connected()){candidate.stop();return;}acm=candidate;acmAvailable=true;uiController.setAcmConnected(true);frameParser.reset();toneFeedback(880,40);}
void closeClient(){if(!acmAvailable)return;acm.stop();acmAvailable=false;uiController.setAcmConnected(false);}
void readInputs(){const uint32_t now=millis();for(uint8_t i=0;i<8;++i){const bool open=digitalRead(acm_hw::KEYPAD_INPUT_PINS[i])==HIGH;if(!initialized[i]){rawOpen[i]=debouncedOpen[i]=open;rawChangedAt[i]=now;initialized[i]=true;continue;}if(open!=rawOpen[i]){rawOpen[i]=open;rawChangedAt[i]=now;}if(open!=debouncedOpen[i]&&static_cast<uint32_t>(now-rawChangedAt[i])>=250){debouncedOpen[i]=open;logInput(i,open);sendUpdate(i);}}}
void processFrame(const String& frame){if(frame.indexOf("LOCAL_SIREN_ON")>=0){localSiren=true;digitalWrite(acm_hw::KEYPAD_SIREN,HIGH);}if(frame.indexOf("LOCAL_SIREN_OFF")>=0){localSiren=false;digitalWrite(acm_hw::KEYPAD_SIREN,LOW);}if(frame.indexOf("\"type\":\"IDENTIFY_REQUEST\"")>=0){sendIdentity();return;}if(frame.indexOf("\"type\":\"SENSOR_SNAPSHOT_REQUEST\"")>=0){sendSnapshot();return;}if(frame.indexOf("\"type\":\"HELLO_ACM\"")>=0){acm_protocol::sendFrame(acm,acm_protocol::HELLO_KEYPAD,String("{\"keypad_id\":\"")+keypadId+"\"}");return;}if(frame.indexOf("\"type\":\"ALARM_STATE\"")>=0){AlarmSnapshot snapshot=uiModel.snapshot();const String state=jsonValue(frame,"state");if(state=="ARMED_HOME")snapshot.state=AlarmState::ARMED_HOME;else if(state=="ARMED_AWAY")snapshot.state=AlarmState::ARMED_AWAY;else if(state=="TRIGGERED")snapshot.state=AlarmState::TRIGGERED;else if(state=="TROUBLE")snapshot.state=AlarmState::TROUBLE;else snapshot.state=AlarmState::DISARMED;snapshot.countdown_seconds=static_cast<uint32_t>(jsonValue(frame,"countdown").toInt());uiController.apply(snapshot);}}
void receiveFrames(){while(acm.available()){frameParser.feed(static_cast<uint8_t>(acm.read()));if(frameParser.invalid()){closeClient();return;}if(frameParser.complete())processFrame(frameParser.take());}if(acmAvailable&&!acm.connected())closeClient();}
void sendHeartbeat(){if(!acm.connected())return;acm_protocol::sendFrame(acm,acm_protocol::HELLO_KEYPAD,String("{\"keypad_id\":\"")+keypadId+"\",\"ip\":\""+Ethernet.localIP().toString()+"\",\"health\":\"OK\"}");}
}
void setup(){Serial.begin(115200);config.begin("keypad",false);hostname=config.getString("hostname",hostname);for(uint8_t i=0;i<8;++i)pinMode(acm_hw::KEYPAD_INPUT_PINS[i],INPUT_PULLUP);pinMode(acm_hw::KEYPAD_PANIC,INPUT_PULLUP);pinMode(acm_hw::KEYPAD_SIREN,OUTPUT);digitalWrite(acm_hw::KEYPAD_SIREN,LOW);SPI.begin(acm_hw::ETH_SCK,acm_hw::ETH_MISO,acm_hw::ETH_MOSI,acm_hw::ETH_CS);Ethernet.init(acm_hw::ETH_CS);Ethernet.begin(macAddress);SD.begin(acm_hw::SD_CS,SPI);keypadId=macString();keypadServer.begin();esp_task_wdt_init(10,true);esp_task_wdt_add(nullptr);uiController.begin();}
void loop(){const uint32_t now=millis();esp_task_wdt_reset();acceptClient();readInputs();updateTone();if(digitalRead(acm_hw::KEYPAD_PANIC)==LOW){if(acm.connected())acm_protocol::sendFrame(acm,"KEYPAD_EVENT",String("{\"keypad_id\":\"")+keypadId+"\",\"event\":\"PANIC\"}");toneFeedback(880,80);while(digitalRead(acm_hw::KEYPAD_PANIC)==LOW)delay(5);}if(now-lastHeartbeat>=acm_protocol::HEARTBEAT_INTERVAL_MS){lastHeartbeat=now;sendHeartbeat();}receiveFrames();delay(1);}
