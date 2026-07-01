// ESP32 Smart AC Controller — main orchestration.
//
//   - Connects Wi-Fi + AWS IoT (MQTT/TLS)
//   - Reads SHT40 (temp/humidity), publishes telemetry
//   - Learns / replays IR codes; drives AC via decoded protocol or raw replay
//   - Caches + fires schedules locally (NTP time), surviving cloud outages
//
#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <time.h>

#include "config.h"
#include "secrets.h"
#include "ac_state.h"
#include "ir_manager.h"
#include "sensors.h"
#include "schedule.h"
#include "cloud.h"
#include "ota.h"

IrManager      ir;
Sensors        sensors;
ScheduleEngine scheduler;
Cloud          cloud;
Ota            ota;

AcState  currentState;       // last-known AC state we believe we set
bool     timeSynced = false;
uint32_t lastSample = 0;
uint32_t lastTelemetryPub = 0;
float    lastPubTemp = NAN;
float    lastPubHum = NAN;
uint32_t lastScheduleTick = 0;

// ---------- helpers ----------
static void blink(int times, int ms) {
  for (int i = 0; i < times; i++) {
    digitalWrite(PIN_STATUS_LED, HIGH); delay(ms);
    digitalWrite(PIN_STATUS_LED, LOW);  delay(ms);
  }
}

static void persistState() {
  Preferences p;
  p.begin("acstate", false);
  p.putBytes("state", &currentState, sizeof(currentState));
  p.end();
}

static void restoreState() {
  Preferences p;
  p.begin("acstate", true);
  if (p.getBytesLength("state") == sizeof(currentState))
    p.getBytes("state", &currentState, sizeof(currentState));
  p.end();
}

// Apply a target state: try decoded send, fall back to raw "power_on/off".
static bool applyState(const AcState& s, const char* source) {
  bool ok = ir.sendState(s);
  if (!ok) {
    // Fallback: replay a raw code matching power if we have one.
    ok = ir.replayRaw(s.power ? "power_on" : "power_off");
  }
  if (ok) {
    currentState = s;
    persistState();
    cloud.publishState(currentState, ir.protocol(), source);
  }
  return ok;
}

// ---------- Wi-Fi & time ----------
static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("[WIFI] connecting to %s", WIFI_SSID);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(400); Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED)
    Serial.printf("[WIFI] connected, IP=%s RSSI=%d\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  else
    Serial.println("[WIFI] FAILED (will keep retrying; schedules still run)");
}

static void syncTime() {
  configTzTime(TZ_STRING, NTP_SERVER_1, NTP_SERVER_2);
  Serial.print("[TIME] waiting for NTP");
  struct tm tm;
  for (int i = 0; i < 20 && !timeSynced; i++) {
    if (getLocalTime(&tm, 500)) { timeSynced = (tm.tm_year > 120); }
    Serial.print(".");
  }
  Serial.println();
  if (timeSynced) {
    char buf[32]; strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tm);
    Serial.printf("[TIME] synced: %s (%s)\n", buf, TZ_STRING);
  } else {
    Serial.println("[TIME] NTP not synced yet (schedules paused until synced)");
  }
}

// ---------- command handlers ----------
static void wireHandlers() {
  cloud.onSetState = [](const AcState& s, const String& reqId) {
    bool ok = applyState(s, "command");
    cloud.publishAck(reqId, ok, ok ? "setState applied" : "send failed");
  };

  cloud.onReplay = [](const String& rawCodeId, const String& reqId) {
    bool ok = ir.replayRaw(rawCodeId);
    cloud.publishAck(reqId, ok, ok ? "replayed" : "code not found");
  };

  cloud.onCapture = [](const String& label, bool enable, uint16_t timeoutSec,
                       const String& reqId) {
    if (enable) ir.startCapture(label, timeoutSec);
    else        ir.stopCapture();
    cloud.publishAck(reqId, true, enable ? "capture armed" : "capture stopped");
  };

  cloud.onIdentify = [](const String& reqId) {
    blink(6, 120);
    cloud.publishAck(reqId, true, "identified");
  };

  cloud.onSchedules = [](std::vector<Schedule>&& list) {
    scheduler.replaceAll(std::move(list));
  };
}

// ---------- setup / loop ----------
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n=== ESP32 Smart AC Controller v%s (device=%s) ===\n",
                FW_VERSION, DEVICE_ID);

  pinMode(PIN_STATUS_LED, OUTPUT);
  pinMode(PIN_CAPTURE_BTN, INPUT_PULLUP);

  restoreState();
  ir.begin();
  if (!sensors.begin()) blink(3, 80);   // visible warning if sensor missing

  scheduler.begin([](const Schedule& s) -> bool {
    if (!s.rawCodeId.isEmpty()) {
      bool ok = ir.replayRaw(s.rawCodeId);
      if (ok) cloud.publishState(currentState, ir.protocol(), "schedule");
      return ok;
    }
    return applyState(s.action, "schedule");
  });

  connectWifi();
  syncTime();

  cloud.attachOta(&ota);   // route AWS IoT Jobs OTA through the MQTT connection
  cloud.begin();
  wireHandlers();

  blink(2, 60);
  Serial.println("[BOOT] ready");
}

void loop() {
  // Network is best-effort; schedules and sensing run regardless.
  if (WiFi.status() == WL_CONNECTED) cloud.loop();
  else if (millis() % 30000 < 5) connectWifi();   // periodic reconnect attempt

  ota.loop();   // executes a deferred reboot after a verified OTA install
  ir.loop();

  // Hand a freshly-captured code up to the cloud.
  if (ir.hasNewCapture()) {
    String label = ir.lastCaptureLabel();
    CapturedCode c = ir.takeCaptured();
    cloud.publishCaptured(label, c);
    Serial.printf("[MAIN] captured '%s' (decoded=%d)\n", label.c_str(), c.hasDecoded);
  }

  // Optional physical learn button: arm capture for the next pressed remote key.
  static uint32_t btnGuard = 0;
  if (digitalRead(PIN_CAPTURE_BTN) == LOW && millis() - btnGuard > 1000) {
    btnGuard = millis();
    if (!ir.isCapturing()) ir.startCapture("button_code", CAPTURE_DEFAULT_TIMEOUT);
  }

  // Re-check NTP sync state cheaply.
  if (!timeSynced && WiFi.status() == WL_CONNECTED) {
    struct tm tm;
    if (getLocalTime(&tm, 0) && tm.tm_year > 120) {
      timeSynced = true;
      Serial.println("[TIME] NTP synced");
    }
  }

  // Telemetry — sample often, publish only on meaningful change or heartbeat.
  // This keeps IoT messages + DynamoDB writes low (see docs/COST.md).
  if (millis() - lastSample >= SENSOR_SAMPLE_MS) {
    lastSample = millis();
    SensorReading r = sensors.read();
    if (r.valid) {
      bool bigChange = isnan(lastPubTemp) ||
                       fabsf(r.tempC - lastPubTemp) >= TELEMETRY_DELTA_TEMP ||
                       fabsf(r.humidity - lastPubHum) >= TELEMETRY_DELTA_HUM;
      bool heartbeat = (millis() - lastTelemetryPub) >= TELEMETRY_HEARTBEAT_MS;
      if (bigChange || heartbeat) {
        cloud.publishTelemetry(r, WiFi.RSSI(), timeSynced);
        lastTelemetryPub = millis();
        lastPubTemp = r.tempC;
        lastPubHum = r.humidity;
        Serial.printf("[TLM] %.1fC %.0f%%RH (%s)\n", r.tempC, r.humidity,
                      heartbeat ? "heartbeat" : "delta");
      }
    }
  }

  // Schedule evaluation.
  if (millis() - lastScheduleTick >= SCHEDULE_TICK_MS) {
    lastScheduleTick = millis();
    scheduler.tick(timeSynced);
  }

  delay(5);
}
