#include "config_store.h"
namespace { const char* const DEFAULT_AREAS[] = {"House","Garage","Basement","Exterior","Shop","She Shed","Shed","Barn","Detached Garage","Utility / Mechanical"}; }
bool ConfigStore::begin(const char* ns){
  if(!prefs_.begin(ns,false)) return false;
  const bool hasSchema=prefs_.isKey("schema"); const uint8_t schema=prefs_.getUChar("schema",0);
  if(!hasSchema && !prefs_.isKey("area_count")){ seedDefaults(); prefs_.putUChar("schema",SCHEMA_VERSION); status_=ConfigStatus::FRESH; }
  else if(schema==SCHEMA_VERSION){ load(); status_=ConfigStatus::CURRENT; }
  else if(schema==0 || schema==1){ load(); prefs_.putUChar("schema",SCHEMA_VERSION); status_=ConfigStatus::MIGRATED; }
  else { load(); status_=ConfigStatus::RECOVERY_REQUIRED; }
  return true;
}
void ConfigStore::seedDefaults(){ area_count_=sizeof(DEFAULT_AREAS)/sizeof(DEFAULT_AREAS[0]); for(uint8_t i=0;i<area_count_;++i){areas_[i].id=i+1; areas_[i].name=DEFAULT_AREAS[i];persistArea(i);} for(uint8_t i=0;i<MAX_CHANNELS;++i){channels_[i].index=i+1; channels_[i].name=String("Channel ")+String(i+1); channels_[i].area_id=0; channels_[i].type=SensorType::OPENING;persistChannel(i);} for(uint8_t i=0;i<MAX_RELAYS;++i){relays_[i].index=i+1; relays_[i].name=String("Relay ")+String(i+1); relays_[i].area_id=0; relays_[i].siren=false;persistRelay(i);} prefs_.putUChar("area_count",area_count_);}
void ConfigStore::load(){
 area_count_=prefs_.getUChar("area_count",0); if(area_count_>MAX_AREAS) area_count_=MAX_AREAS;
 keypad_count_=prefs_.getUChar("keypad_count",0); if(keypad_count_>MAX_KEYPADS) keypad_count_=MAX_KEYPADS;
 for(uint8_t i=0;i<area_count_;++i){ areas_[i].id=prefs_.getUShort((String("a_id")+i).c_str(),i+1); areas_[i].name=prefs_.getString((String("a_name")+i).c_str(),""); }
 for(uint8_t i=0;i<MAX_CHANNELS;++i){ channels_[i].index=i+1; channels_[i].name=prefs_.getString((String("c_name")+i).c_str(),String("Channel ")+String(i+1)); channels_[i].area_id=prefs_.getUShort((String("c_area")+i).c_str(),0); channels_[i].type=static_cast<SensorType>(prefs_.getUChar((String("c_type")+i).c_str(),0)); }
 for(uint8_t i=0;i<MAX_RELAYS;++i){ relays_[i].index=i+1; relays_[i].name=prefs_.getString((String("r_name")+i).c_str(),String("Relay ")+String(i+1)); relays_[i].area_id=prefs_.getUShort((String("r_area")+i).c_str(),0); relays_[i].siren=prefs_.getBool((String("r_siren")+i).c_str(),false); }
 for(uint8_t i=0;i<keypad_count_;++i){ keypads_[i].authorized=prefs_.getBool((String("k_auth")+i).c_str(),false); keypads_[i].mac=prefs_.getString((String("k_mac")+i).c_str(),""); keypads_[i].name=prefs_.getString((String("k_name")+i).c_str(),""); keypads_[i].ip=prefs_.getString((String("k_ip")+i).c_str(),""); keypads_[i].area_id=prefs_.getUShort((String("k_area")+i).c_str(),0); keypads_[i].firmware=prefs_.getString((String("k_fw")+i).c_str(),""); for(uint8_t j=0;j<8;++j){ keypads_[i].input_names[j]=prefs_.getString((String("k_in")+i+"_"+j).c_str(),""); keypads_[i].input_types[j]=static_cast<SensorType>(prefs_.getUChar((String("k_type")+i+"_"+j).c_str(),0)); } }
}
void ConfigStore::persistArea(uint8_t i){prefs_.putUShort((String("a_id")+i).c_str(),areas_[i].id);prefs_.putString((String("a_name")+i).c_str(),areas_[i].name);}
void ConfigStore::persistChannel(uint8_t i){prefs_.putString((String("c_name")+i).c_str(),channels_[i].name);prefs_.putUShort((String("c_area")+i).c_str(),channels_[i].area_id);prefs_.putUChar((String("c_type")+i).c_str(),static_cast<uint8_t>(channels_[i].type));}
void ConfigStore::persistRelay(uint8_t i){prefs_.putString((String("r_name")+i).c_str(),relays_[i].name);prefs_.putUShort((String("r_area")+i).c_str(),relays_[i].area_id);prefs_.putBool((String("r_siren")+i).c_str(),relays_[i].siren);}
uint8_t ConfigStore::addArea(const String& name){if(!name.length()||area_count_>=MAX_AREAS)return 0;uint16_t id=area_count_?areas_[area_count_-1].id+1:1;areas_[area_count_].id=id; areas_[area_count_].name=name;persistArea(area_count_);++area_count_;prefs_.putUChar("area_count",area_count_);return static_cast<uint8_t>(area_count_);}
bool ConfigStore::renameArea(uint16_t id,const String& name){for(uint8_t i=0;i<area_count_;++i)if(areas_[i].id==id){areas_[i].name=name;persistArea(i);return true;}return false;}
bool ConfigStore::saveChannel(const ChannelRecord& value){if(value.index<1||value.index>MAX_CHANNELS)return false;channels_[value.index-1]=value;persistChannel(value.index-1);return true;}
bool ConfigStore::saveRelay(const RelayRecord& value){if(value.index<1||value.index>MAX_RELAYS)return false;relays_[value.index-1]=value;persistRelay(value.index-1);return true;}

int8_t ConfigStore::findKeypad(const String& mac) const { for(uint8_t i=0;i<keypad_count_;++i) if(keypads_[i].mac==mac) return i; return -1; }
int8_t ConfigStore::saveKeypad(const KeypadRecord& value) {
  if(!value.mac.length()) return -1; int8_t found=findKeypad(value.mac); uint8_t i=found>=0?found:keypad_count_; if(found<0 && keypad_count_>=MAX_KEYPADS)return -1;
  keypads_[i]=value; if(found<0) ++keypad_count_; prefs_.putUChar("keypad_count",keypad_count_);
  prefs_.putBool((String("k_auth")+i).c_str(),value.authorized); prefs_.putString((String("k_mac")+i).c_str(),value.mac); prefs_.putString((String("k_name")+i).c_str(),value.name); prefs_.putString((String("k_ip")+i).c_str(),value.ip); prefs_.putUShort((String("k_area")+i).c_str(),value.area_id); prefs_.putString((String("k_fw")+i).c_str(),value.firmware); for(uint8_t j=0;j<8;++j){ prefs_.putString((String("k_in")+i+"_"+j).c_str(),value.input_names[j]); prefs_.putUChar((String("k_type")+i+"_"+j).c_str(),static_cast<uint8_t>(value.input_types[j])); } return i;
}
bool ConfigStore::removeKeypad(uint8_t index) { if(index>=keypad_count_)return false; keypads_[index].authorized=false; prefs_.putBool((String("k_auth")+index).c_str(),false); return true; }
