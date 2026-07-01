// On-device schedule storage + evaluation against NTP local time.
#pragma once
#include <Arduino.h>
#include <vector>
#include <functional>
#include "ac_state.h"

struct Schedule {
  String   id;
  bool     enabled = true;
  uint8_t  daysMask = 0x7F;     // bit i (0=Sun..6=Sat); 0x7F = every day
  uint8_t  hour = 0;
  uint8_t  minute = 0;
  AcState  action;              // target state to apply
  String   rawCodeId;           // if non-empty, replay this raw code instead
  uint32_t updatedAt = 0;
  int      lastFiredYday = -1;  // day-of-year guard so it fires once per day
  int      lastFiredMin = -1;   // minute-of-day guard within that day
};

class ScheduleEngine {
public:
  // Callback applies a schedule's action; returns true on success.
  using FireFn = std::function<bool(const Schedule&)>;

  void begin(FireFn fire) { fire_ = fire; loadFromNvs(); }

  // Replace the entire schedule set (from a cloud sync). Persists to NVS.
  void replaceAll(std::vector<Schedule>&& schedules);

  // Evaluate against current local time; call ~every SCHEDULE_TICK_MS.
  // timeSynced=false means NTP hasn't synced — we skip firing to avoid
  // firing at the wrong time, but keep schedules loaded.
  void tick(bool timeSynced);

  const std::vector<Schedule>& all() const { return schedules_; }

  void loadFromNvs();
  void saveToNvs() const;

private:
  std::vector<Schedule> schedules_;
  FireFn fire_;
};
