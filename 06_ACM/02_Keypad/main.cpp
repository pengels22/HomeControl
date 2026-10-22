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
#include "event_logger.h"

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
bool localSiren=false, acmAvailable=false, hadSession=false;
KeypadUiModel uiModel; KeypadDisplayBoundary display; KeypadUiController uiController(uiModel,display); EventLogger eventLogger(acm_hw::SD_CS);
uint32_t lastHeartbeat=0, toneUntil=0, lastChirpedCountdown=0xffffffff;
bool rawOpen[8]={}, debouncedOpen[8]={}, initialized[8]={}; uint32_t rawChangedAt[8]={};
acm_protocol::FrameParser frameParser;
bool panicRaw=false, panicAsserted=false, panicInitialized=false; uint32_t panicRawChangedAt=0;

String macString(){uint8_t mac[6]={};Ethernet.MACAddress(mac);String result;for(uint8_t i=0;i<6;++i){if(i)result+=':';if(mac[i]<16)result+='0';result+=String(mac[i],HEX);}return result;}
String jsonValue(const String& json,const char* key){const String prefix=String("\"")+key+"\":";const int start=json.indexOf(prefix);if(start<0)return "";int b=start+prefix.length();if(b<json.length()&&json[b]=='"'){++b;const int e=json.indexOf('"',b);return e<0?"":json.substring(b,e);}int e=json.indexOf(',',b);const int close=json.indexOf('}',b);if(e<0||(close>=0&&close<e))e=close;return e<0?json.substring(b):json.substring(b,e);}
void toneFeedback(uint16_t frequency,uint16_t duration){ledcSetup(0,frequency,10);ledcAttachPin(acm_hw::KEYPAD_PIEZO,0);ledcWriteTone(0,frequency);toneUntil=millis()+duration;}
void stopTone(){ledcWriteTone(0,0);toneUntil=0;}
void updateTone(){if(toneUntil&&static_cast<int32_t>(millis()-toneUntil)>=0)stopTone();}
void logInput(uint8_t index,bool open){eventLogger.log(open?"SENSOR_OPEN":"SENSOR_CLOSED",String("Channel=")+String(index+1));}
void sendSnapshot(){if(!acm.connected())return;String payload="{\"keypad_id\":\""+keypadId+"\",\"states\":[";for(uint8_t i=0;i<8;++i){if(i)payload+=',';payload+=debouncedOpen[i]?"true":"false";}payload+="]}";acm_protocol::sendFrame(acm,acm_protocol::SENSOR_SNAPSHOT,payload);}
void sendIdentity(){String payload="{\"mac\":\""+keypadId+"\",\"ip\":\""+Ethernet.localIP().toString()+"\",\"name\":\""+hostname+"\",\"firmware\":\"acm-keypad-1.0\"}";acm_protocol::sendFrame(acm,acm_protocol::IDENTIFY_RESPONSE,payload);}
void sendUpdate(uint8_t index){if(!acm.connected())return;String payload="{\"keypad_id\":\""+keypadId+"\",\"channel\":\""+String(index+1)+"\",\"state\":\""+(debouncedOpen[index]?"OPEN":"CLOSED")+"\"}";acm_protocol::sendFrame(acm,acm_protocol::SENSOR_UPDATE,payload);}
void sendAction(const char* action,const String& pin){if(!acm.connected()){toneFeedback(220,160);return;}String payload=String("{\"keypad_id\":\"")+keypadId+"\",\"action\":\""+action+"\",\"pin\":\""+pin+"\"}";acm_protocol::sendFrame(acm,acm_protocol::KEYPAD_ACTION,payload);}
void acceptClient(){EthernetClient candidate=keypadServer.available();if(!candidate)return;if(acm.connected()){candidate.stop();return;}acm=candidate;acmAvailable=true;uiController.setAcmConnected(true);frameParser.reset();toneFeedback(880,40);}
void closeClient(){if(!acmAvailable)return;acm.stop();acmAvailable=false;uiController.setAcmConnected(false);if(hadSession){eventLogger.log("ACM_COMMS_LOST");hadSession=false;}}
void readInputs(){const uint32_t now=millis();for(uint8_t i=0;i<8;++i){const bool open=digitalRead(acm_hw::KEYPAD_INPUT_PINS[i])==HIGH;if(!initialized[i]){rawOpen[i]=debouncedOpen[i]=open;rawChangedAt[i]=now;initialized[i]=true;continue;}if(open!=rawOpen[i]){rawOpen[i]=open;rawChangedAt[i]=now;}if(open!=debouncedOpen[i]&&static_cast<uint32_t>(now-rawChangedAt[i])>=250){debouncedOpen[i]=open;logInput(i,open);sendUpdate(i);}}}
void readPanic(){const uint32_t now=millis();const bool asserted=digitalRead(acm_hw::KEYPAD_PANIC)==LOW;if(!panicInitialized){panicRaw=panicAsserted=asserted;panicRawChangedAt=now;panicInitialized=true;return;}if(asserted!=panicRaw){panicRaw=asserted;panicRawChangedAt=now;}if(asserted!=panicAsserted&&static_cast<uint32_t>(now-panicRawChangedAt)>=30){panicAsserted=asserted;if(panicAsserted){if(acm.connected())acm_protocol::sendFrame(acm,"KEYPAD_EVENT",String("{\"keypad_id\":\"")+keypadId+"\",\"event\":\"PANIC\"}");toneFeedback(880,80);}}}
void processFrame(const String& frame){
  if(frame.indexOf("LOCAL_SIREN_ON")>=0){localSiren=true;digitalWrite(acm_hw::KEYPAD_SIREN,HIGH);}
  if(frame.indexOf("LOCAL_SIREN_OFF")>=0){localSiren=false;digitalWrite(acm_hw::KEYPAD_SIREN,LOW);}
  if(frame.indexOf("\"type\":\"IDENTIFY_REQUEST\"")>=0){sendIdentity();return;}
  if(frame.indexOf("\"type\":\"SENSOR_SNAPSHOT_REQUEST\"")>=0){sendSnapshot();return;}
  if(frame.indexOf("\"type\":\"HELLO_KEYPAD\"")>=0){if(!hadSession){hadSession=true;eventLogger.log("ACM_COMMS_RESTORED");}acm_protocol::sendFrame(acm,acm_protocol::HELLO_ACM,String("{\"keypad_id\":\"")+keypadId+"\",\"mac\":\""+keypadId+"\"}");return;}
  if(frame.indexOf("\"type\":\"TIME_SYNC\"")>=0){const uint32_t unix_seconds=static_cast<uint32_t>(jsonValue(frame,"unix").toInt());if(eventLogger.setTime(unix_seconds)){if(eventLogger.takeTimeRestored())eventLogger.log("TIME_SYNC_RESTORED");}return;}
  if(frame.indexOf("\"type\":\"ACTION_RESULT\"")>=0){toneFeedback(jsonValue(frame,"success")=="true"?880:220,jsonValue(frame,"success")=="true"?100:220);return;}
  if(frame.indexOf("\"type\":\"ALARM_STATE\"")>=0){
    AlarmSnapshot snapshot=uiModel.snapshot(); const String state=jsonValue(frame,"state");
    if(state=="ARMING_DELAY")snapshot.state=AlarmState::ARMING_DELAY;
    else if(state=="ENTRY_DELAY")snapshot.state=AlarmState::ENTRY_DELAY;
    else if(state=="ARMED_HOME")snapshot.state=AlarmState::ARMED_HOME;
    else if(state=="ARMED_AWAY")snapshot.state=AlarmState::ARMED_AWAY;
    else if(state=="TRIGGERED")snapshot.state=AlarmState::TRIGGERED;
    else if(state=="TROUBLE")snapshot.state=AlarmState::TROUBLE;
    else snapshot.state=AlarmState::DISARMED;
    snapshot.countdown_seconds=static_cast<uint32_t>(jsonValue(frame,"countdown").toInt()); uiController.apply(snapshot);
    if(snapshot.state==AlarmState::ARMING_DELAY||snapshot.state==AlarmState::ENTRY_DELAY){if(snapshot.countdown_seconds!=lastChirpedCountdown){lastChirpedCountdown=snapshot.countdown_seconds;if(snapshot.countdown_seconds>0)toneFeedback(880,100);}}
    else {lastChirpedCountdown=0xffffffff;stopTone();}
  }
}
void receiveFrames(){while(acm.available()){frameParser.feed(static_cast<uint8_t>(acm.read()));if(frameParser.invalid()){closeClient();return;}if(frameParser.complete())processFrame(frameParser.take());}if(acmAvailable&&!acm.connected())closeClient();}
void sendHeartbeat(){if(!acm.connected())return;acm_protocol::sendFrame(acm,acm_protocol::HELLO_ACM,String("{\"keypad_id\":\"")+keypadId+"\",\"mac\":\""+keypadId+"\",\"ip\":\""+Ethernet.localIP().toString()+"\",\"health\":\"OK\"}");}
}
void setup(){Serial.begin(115200);config.begin("keypad",false);hostname=config.getString("hostname",hostname);for(uint8_t i=0;i<8;++i)pinMode(acm_hw::KEYPAD_INPUT_PINS[i],INPUT_PULLUP);pinMode(acm_hw::KEYPAD_PANIC,INPUT_PULLUP);pinMode(acm_hw::KEYPAD_SIREN,OUTPUT);digitalWrite(acm_hw::KEYPAD_SIREN,LOW); // Safe boot: 5 V siren is inactive before network initialization.
 SPI.begin(acm_hw::ETH_SCK,acm_hw::ETH_MISO,acm_hw::ETH_MOSI,acm_hw::ETH_CS);eventLogger.begin();Ethernet.init(acm_hw::ETH_CS);Ethernet.begin(macAddress);keypadId=macString();keypadServer.begin();eventLogger.log("KEYPAD_BOOT");esp_task_wdt_init(10,true);esp_task_wdt_add(nullptr);uiController.setActionHandler(sendAction);uiController.begin();}
void loop(){const uint32_t now=millis();esp_task_wdt_reset();eventLogger.tick(now);if(eventLogger.takeTimeLost())eventLogger.log("TIME_SYNC_LOST");acceptClient();readInputs();readPanic();updateTone();if(now-lastHeartbeat>=acm_protocol::HEARTBEAT_INTERVAL_MS){lastHeartbeat=now;sendHeartbeat();}receiveFrames();delay(1);}
