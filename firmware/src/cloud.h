// AWS IoT Core connectivity over MQTT/TLS, plus message (de)serialization.
#pragma once
#include <Arduino.h>
#include <functional>
#include "ac_state.h"
#include "schedule.h"
#include "ir_manager.h"
#include "sensors.h"

class Ota;   // AWS IoT Jobs OTA agent — routed through this MQTT connection

class Cloud {
public:
  // Handlers wired up by main.
  std::function<void(const AcState&, const String& reqId)> onSetState;
  std::function<void(const String& rawCodeId, const String& reqId)> onReplay;
  std::function<void(const String& label, bool enable, uint16_t timeoutSec,
                     const String& reqId)> onCapture;
  std::function<void(const String& reqId)> onIdentify;
  std::function<void(std::vector<Schedule>&&)> onSchedules;

  void begin();
  void loop();              // maintains connection; pumps MQTT
  bool connected() const;

  // Route the AWS IoT Jobs OTA agent through this connection (call before begin()).
  void attachOta(Ota* ota) { ota_ = ota; }

  // ---- publishers ----
  void publishTelemetry(const SensorReading& r, int rssi, bool timeSynced);
  void publishState(const AcState& s, decode_type_t protocol, const char* source);
  void publishCaptured(const String& label, const CapturedCode& c);
  void publishAck(const String& reqId, bool ok, const String& detail);

private:
  void ensureConnected();
  void handleMessage(char* topic, uint8_t* payload, unsigned int len);
  void subscribeAll();

  char topicTelemetry_[64], topicState_[64], topicCaptured_[64];
  char topicCommand_[64], topicSchedules_[64], topicAck_[64];
  uint32_t lastReconnectAttempt_ = 0;
  Ota* ota_ = nullptr;
};
