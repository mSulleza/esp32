#include "schedule.h"
#include <Preferences.h>
#include <ArduinoJson.h>
#include <time.h>
#include "config.h"

void ScheduleEngine::replaceAll(std::vector<Schedule>&& schedules) {
  schedules_ = std::move(schedules);
  if (schedules_.size() > MAX_SCHEDULES) schedules_.resize(MAX_SCHEDULES);
  saveToNvs();
  Serial.printf("[SCHED] loaded %u schedules\n", (unsigned)schedules_.size());
}

void ScheduleEngine::tick(bool timeSynced) {
  if (!timeSynced || schedules_.empty()) return;

  time_t now = time(nullptr);
  struct tm lt;
  localtime_r(&now, &lt);

  int weekday = lt.tm_wday;          // 0=Sun..6=Sat
  int minOfDay = lt.tm_hour * 60 + lt.tm_min;

  for (auto& s : schedules_) {
    if (!s.enabled) continue;
    if (!(s.daysMask & (1 << weekday))) continue;
    if (s.hour != lt.tm_hour || s.minute != lt.tm_min) continue;
    // Fire once per matching minute per day.
    if (s.lastFiredYday == lt.tm_yday && s.lastFiredMin == minOfDay) continue;

    Serial.printf("[SCHED] firing '%s' at %02d:%02d\n", s.id.c_str(),
                  lt.tm_hour, lt.tm_min);
    if (fire_ && fire_(s)) {
      s.lastFiredYday = lt.tm_yday;
      s.lastFiredMin = minOfDay;
    }
  }
}

void ScheduleEngine::saveToNvs() const {
  JsonDocument doc;
  JsonArray arr = doc.to<JsonArray>();
  for (const auto& s : schedules_) {
    JsonObject o = arr.add<JsonObject>();
    o["id"] = s.id;
    o["enabled"] = s.enabled;
    o["daysMask"] = s.daysMask;
    o["hour"] = s.hour;
    o["minute"] = s.minute;
    o["rawCodeId"] = s.rawCodeId;
    o["updatedAt"] = s.updatedAt;
    JsonObject a = o["action"].to<JsonObject>();
    a["power"] = s.action.power;
    a["mode"]  = toStr(s.action.mode);
    a["tempC"] = s.action.tempC;
    a["fan"]   = toStr(s.action.fan);
    a["swing"] = toStr(s.action.swing);
  }
  String out;
  serializeJson(doc, out);

  Preferences p;
  p.begin("sched", false);
  p.putString("json", out);
  p.end();
}

void ScheduleEngine::loadFromNvs() {
  Preferences p;
  p.begin("sched", true);
  String json = p.getString("json", "[]");
  p.end();

  JsonDocument doc;
  if (deserializeJson(doc, json)) { Serial.println("[SCHED] NVS parse fail"); return; }

  schedules_.clear();
  for (JsonObject o : doc.as<JsonArray>()) {
    Schedule s;
    s.id        = (const char*)(o["id"] | "");
    s.enabled   = o["enabled"] | true;
    s.daysMask  = o["daysMask"] | 0x7F;
    s.hour      = o["hour"] | 0;
    s.minute    = o["minute"] | 0;
    s.rawCodeId = (const char*)(o["rawCodeId"] | "");
    s.updatedAt = o["updatedAt"] | 0;
    JsonObject a = o["action"];
    s.action.power = a["power"] | false;
    s.action.mode  = parseMode(a["mode"] | "cool");
    s.action.tempC = a["tempC"] | 24;
    s.action.fan   = parseFan(a["fan"] | "auto");
    s.action.swing = parseSwing(a["swing"] | "off");
    schedules_.push_back(s);
  }
  Serial.printf("[SCHED] restored %u schedules from NVS\n", (unsigned)schedules_.size());
}
