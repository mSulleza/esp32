#include "ac_state.h"
#include <string.h>

const char* toStr(AcMode m) {
  switch (m) {
    case AcMode::Cool: return "cool";
    case AcMode::Heat: return "heat";
    case AcMode::Dry:  return "dry";
    case AcMode::Fan:  return "fan";
    case AcMode::Auto: return "auto";
  }
  return "cool";
}

const char* toStr(AcFan f) {
  switch (f) {
    case AcFan::Auto: return "auto";
    case AcFan::Low:  return "low";
    case AcFan::Med:  return "med";
    case AcFan::High: return "high";
    case AcFan::Max:  return "max";
  }
  return "auto";
}

const char* toStr(AcSwing s) {
  switch (s) {
    case AcSwing::Off:        return "off";
    case AcSwing::Vertical:   return "vertical";
    case AcSwing::Horizontal: return "horizontal";
    case AcSwing::Both:       return "both";
  }
  return "off";
}

AcMode parseMode(const char* s, AcMode def) {
  if (!s) return def;
  if (!strcmp(s, "cool")) return AcMode::Cool;
  if (!strcmp(s, "heat")) return AcMode::Heat;
  if (!strcmp(s, "dry"))  return AcMode::Dry;
  if (!strcmp(s, "fan"))  return AcMode::Fan;
  if (!strcmp(s, "auto")) return AcMode::Auto;
  return def;
}

AcFan parseFan(const char* s, AcFan def) {
  if (!s) return def;
  if (!strcmp(s, "auto")) return AcFan::Auto;
  if (!strcmp(s, "low"))  return AcFan::Low;
  if (!strcmp(s, "med"))  return AcFan::Med;
  if (!strcmp(s, "high")) return AcFan::High;
  if (!strcmp(s, "max"))  return AcFan::Max;
  return def;
}

AcSwing parseSwing(const char* s, AcSwing def) {
  if (!s) return def;
  if (!strcmp(s, "off"))        return AcSwing::Off;
  if (!strcmp(s, "vertical"))   return AcSwing::Vertical;
  if (!strcmp(s, "horizontal")) return AcSwing::Horizontal;
  if (!strcmp(s, "both"))       return AcSwing::Both;
  return def;
}
