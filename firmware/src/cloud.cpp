#include "cloud.h"
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "config.h"
#include "secrets.h"
#include "ota.h"

static WiFiClientSecure tlsClient;
static PubSubClient mqtt(tlsClient);
static Cloud* self = nullptr;   // for the static MQTT callback trampoline

// Keep cloud-supplied setpoints inside the range the API accepts.
static int clampTemp(int t) {
  return t < AC_MIN_TEMP_C ? AC_MIN_TEMP_C : (t > AC_MAX_TEMP_C ? AC_MAX_TEMP_C : t);
}

void Cloud::begin() {
  self = this;
  snprintf(topicTelemetry_, sizeof(topicTelemetry_), TOPIC_TELEMETRY, DEVICE_ID);
  snprintf(topicState_,     sizeof(topicState_),     TOPIC_STATE,     DEVICE_ID);
  snprintf(topicCaptured_,  sizeof(topicCaptured_),  TOPIC_CAPTURED,  DEVICE_ID);
  snprintf(topicCommand_,   sizeof(topicCommand_),   TOPIC_COMMAND,   DEVICE_ID);
  snprintf(topicSchedules_, sizeof(topicSchedules_), TOPIC_SCHEDULES, DEVICE_ID);
  snprintf(topicAck_,       sizeof(topicAck_),       TOPIC_ACK,       DEVICE_ID);

  tlsClient.setCACert(AWS_ROOT_CA);
  tlsClient.setCertificate(DEVICE_CERT);
  tlsClient.setPrivateKey(DEVICE_PRIVATE_KEY);

  mqtt.setServer(AWS_IOT_ENDPOINT, AWS_IOT_PORT);
  mqtt.setBufferSize(2048);
  mqtt.setCallback([](char* t, uint8_t* p, unsigned int l) {
    if (self) self->handleMessage(t, p, l);
  });

  if (ota_)
    ota_->begin(DEVICE_ID, AWS_ROOT_CA,
      [](const char* t, const char* pl) { return mqtt.publish(t, pl); },
      [](const char* t) { return mqtt.subscribe(t, 1); });
}

bool Cloud::connected() const { return mqtt.connected(); }

void Cloud::loop() {
  if (!mqtt.connected()) ensureConnected();
  mqtt.loop();
}

void Cloud::ensureConnected() {
  if (millis() - lastReconnectAttempt_ < MQTT_RECONNECT_MS) return;
  lastReconnectAttempt_ = millis();

  Serial.print("[MQTT] connecting to AWS IoT... ");
  if (mqtt.connect(DEVICE_ID)) {
    Serial.println("connected");
    subscribeAll();
  } else {
    Serial.printf("failed rc=%d\n", mqtt.state());
  }
}

void Cloud::subscribeAll() {
  mqtt.subscribe(topicCommand_, 1);
  mqtt.subscribe(topicSchedules_, 1);
  Serial.printf("[MQTT] subscribed %s , %s\n", topicCommand_, topicSchedules_);
  if (ota_) ota_->onMqttConnect();   // subscribe Jobs topics + fetch any pending job
}

// ---- inbound ----
void Cloud::handleMessage(char* topic, uint8_t* payload, unsigned int len) {
  // AWS IoT Jobs (OTA) topics are handled by the OTA agent.
  if (ota_ && ota_->handleJobsMessage(topic, payload, len)) return;

  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) {
    Serial.println("[MQTT] bad JSON payload");
    return;
  }

  if (!strcmp(topic, topicCommand_)) {
    String cmd   = (const char*)(doc["cmd"] | "");
    String reqId = (const char*)(doc["reqId"] | "");

    if (cmd == "setState" && onSetState) {
      JsonObject st = doc["state"];
      AcState s;
      s.power = st["power"] | false;
      s.mode  = parseMode(st["mode"] | "cool");
      s.tempC = clampTemp(st["tempC"] | 24);
      s.fan   = parseFan(st["fan"] | "auto");
      s.swing = parseSwing(st["swing"] | "off");
      onSetState(s, reqId);
    } else if (cmd == "replay" && onReplay) {
      onReplay((const char*)(doc["rawCodeId"] | ""), reqId);
    } else if (cmd == "capture" && onCapture) {
      onCapture((const char*)(doc["label"] | "code"),
                doc["enable"] | true,
                doc["timeoutSec"] | CAPTURE_DEFAULT_TIMEOUT, reqId);
    } else if (cmd == "identify" && onIdentify) {
      onIdentify(reqId);
    } else {
      Serial.printf("[MQTT] unknown cmd '%s'\n", cmd.c_str());
    }
  }
  else if (!strcmp(topic, topicSchedules_)) {
    std::vector<Schedule> list;
    for (JsonObject o : doc["schedules"].as<JsonArray>()) {
      Schedule s;
      s.id        = (const char*)(o["id"] | "");
      s.enabled   = o["enabled"] | true;
      s.rawCodeId = (const char*)(o["rawCodeId"] | "");
      s.updatedAt = o["updatedAt"] | 0;
      // "time" is "HH:MM"
      String t = (const char*)(o["time"] | "00:00");
      s.hour   = t.substring(0, 2).toInt();
      s.minute = t.substring(3, 5).toInt();
      // daysOfWeek array -> bitmask (ignore anything outside 0..6: shifting by
      // a negative or >= 32 amount is undefined behaviour)
      s.daysMask = 0;
      for (JsonVariant v : o["daysOfWeek"].as<JsonArray>()) {
        if (!v.is<int>()) continue;
        int d = v.as<int>();
        if (d >= 0 && d <= 6) s.daysMask |= (uint8_t)(1u << d);
      }
      if (s.daysMask == 0) s.daysMask = 0x7F;
      JsonObject a = o["action"];
      s.action.power = a["power"] | false;
      s.action.mode  = parseMode(a["mode"] | "cool");
      s.action.tempC = clampTemp(a["tempC"] | 24);
      s.action.fan   = parseFan(a["fan"] | "auto");
      s.action.swing = parseSwing(a["swing"] | "off");
      list.push_back(s);
    }
    if (onSchedules) onSchedules(std::move(list));
  }
}

// ---- outbound ----
void Cloud::publishTelemetry(const SensorReading& r, int rssi, bool timeSynced) {
  if (!mqtt.connected()) return;
  JsonDocument doc;
  doc["ts"] = (uint64_t)time(nullptr) * 1000ULL;
  if (r.valid) {
    doc["tempC"] = r.tempC;
    doc["humidity"] = r.humidity;
  }
  doc["rssi"] = rssi;
  doc["timeSynced"] = timeSynced;
  char buf[256];
  size_t n = serializeJson(doc, buf);
  mqtt.publish(topicTelemetry_, (const uint8_t*)buf, n, false);
}

void Cloud::publishState(const AcState& s, decode_type_t protocol, const char* source) {
  if (!mqtt.connected()) return;
  JsonDocument doc;
  doc["ts"] = (uint64_t)time(nullptr) * 1000ULL;
  doc["power"] = s.power;
  doc["mode"]  = toStr(s.mode);
  doc["tempC"] = s.tempC;
  doc["fan"]   = toStr(s.fan);
  doc["swing"] = toStr(s.swing);
  doc["protocol"] = typeToString(protocol);
  doc["source"] = source;
  char buf[256];
  size_t n = serializeJson(doc, buf);
  mqtt.publish(topicState_, (const uint8_t*)buf, n, false);
}

void Cloud::publishCaptured(const String& label, const CapturedCode& c) {
  if (!mqtt.connected()) return;
  JsonDocument doc;
  doc["ts"] = (uint64_t)time(nullptr) * 1000ULL;
  doc["label"] = label;
  if (c.hasDecoded) {
    JsonObject d = doc["decoded"].to<JsonObject>();
    d["protocol"] = typeToString(c.protocol);
    d["power"]    = c.decoded.power;
    d["mode"]     = (int)c.decoded.mode;
    d["tempC"]    = c.decoded.degrees;
    d["fan"]      = (int)c.decoded.fanspeed;
  } else {
    doc["decoded"] = nullptr;
  }
  JsonObject raw = doc["raw"].to<JsonObject>();
  raw["freqKhz"] = c.freqKhz;
  JsonArray timings = raw["timings"].to<JsonArray>();
  for (uint16_t v : c.raw) timings.add(v);

  // Raw arrays are large; serialize into a heap String to avoid stack overflow.
  String out;
  serializeJson(doc, out);
  mqtt.publish(topicCaptured_, out.c_str());
}

void Cloud::publishAck(const String& reqId, bool ok, const String& detail) {
  if (!mqtt.connected()) return;
  JsonDocument doc;
  doc["reqId"] = reqId;
  doc["ok"] = ok;
  doc["ts"] = (uint64_t)time(nullptr) * 1000ULL;
  doc["detail"] = detail;
  char buf[192];
  size_t n = serializeJson(doc, buf);
  mqtt.publish(topicAck_, (const uint8_t*)buf, n, false);
}
