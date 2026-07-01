// Shared AC state model used across IR, schedules, and cloud.
#pragma once
#include <Arduino.h>

enum class AcMode  { Cool, Heat, Dry, Fan, Auto };
enum class AcFan   { Auto, Low, Med, High, Max };
enum class AcSwing { Off, Vertical, Horizontal, Both };

struct AcState {
  bool    power  = false;
  AcMode  mode   = AcMode::Cool;
  int     tempC  = 24;
  AcFan   fan    = AcFan::Auto;
  AcSwing swing  = AcSwing::Off;
};

// ---- string <-> enum helpers (used for JSON (de)serialization) ----
const char* toStr(AcMode m);
const char* toStr(AcFan f);
const char* toStr(AcSwing s);
AcMode  parseMode(const char* s, AcMode def = AcMode::Cool);
AcFan   parseFan(const char* s, AcFan def = AcFan::Auto);
AcSwing parseSwing(const char* s, AcSwing def = AcSwing::Off);
