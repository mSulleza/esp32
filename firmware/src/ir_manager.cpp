#include "ir_manager.h"
#include <Preferences.h>
#include "config.h"

// Map our enums onto IRremoteESP8266's stdAc enums.
static stdAc::opmode_t mapMode(AcMode m) {
  switch (m) {
    case AcMode::Cool: return stdAc::opmode_t::kCool;
    case AcMode::Heat: return stdAc::opmode_t::kHeat;
    case AcMode::Dry:  return stdAc::opmode_t::kDry;
    case AcMode::Fan:  return stdAc::opmode_t::kFan;
    case AcMode::Auto: return stdAc::opmode_t::kAuto;
  }
  return stdAc::opmode_t::kCool;
}

static stdAc::fanspeed_t mapFan(AcFan f) {
  switch (f) {
    case AcFan::Auto: return stdAc::fanspeed_t::kAuto;
    case AcFan::Low:  return stdAc::fanspeed_t::kLow;
    case AcFan::Med:  return stdAc::fanspeed_t::kMedium;
    case AcFan::High: return stdAc::fanspeed_t::kHigh;
    case AcFan::Max:  return stdAc::fanspeed_t::kMax;
  }
  return stdAc::fanspeed_t::kAuto;
}

static stdAc::swingv_t mapSwingV(AcSwing s) {
  return (s == AcSwing::Vertical || s == AcSwing::Both)
           ? stdAc::swingv_t::kAuto : stdAc::swingv_t::kOff;
}
static stdAc::swingh_t mapSwingH(AcSwing s) {
  return (s == AcSwing::Horizontal || s == AcSwing::Both)
           ? stdAc::swingh_t::kAuto : stdAc::swingh_t::kOff;
}

IrManager::IrManager()
  : recv_(PIN_IR_RX, IR_CAPTURE_BUFFER_SIZE, IR_CAPTURE_TIMEOUT, true),
    send_(PIN_IR_TX),
    ac_(PIN_IR_TX) {}

void IrManager::begin() {
  send_.begin();
  recv_.setUnknownThreshold(IR_MIN_UNKNOWN_SIZE);
  // Receiver stays disabled until we enter learn mode, to avoid CPU churn.
  loadFromNvs();
}

void IrManager::startCapture(const String& label, uint16_t timeoutSec) {
  captureLabel_ = label;
  capturing_ = true;
  hasNewCapture_ = false;
  captureDeadlineMs_ = millis() + (uint32_t)timeoutSec * 1000UL;
  recv_.enableIRIn();
  Serial.printf("[IR] capture started: label=%s timeout=%us\n", label.c_str(), timeoutSec);
}

void IrManager::stopCapture() {
  if (!capturing_) return;
  capturing_ = false;
  recv_.disableIRIn();
  Serial.println("[IR] capture stopped");
}

void IrManager::loop() {
  if (!capturing_) return;

  if ((int32_t)(millis() - captureDeadlineMs_) >= 0) {
    Serial.println("[IR] capture timed out");
    stopCapture();
    return;
  }

  decode_results results;
  if (!recv_.decode(&results)) return;

  pending_ = CapturedCode{};
  pending_.protocol = results.decode_type;
  pending_.freqKhz = 38;

  // Raw timings (skip the leading gap entry at index 0).
  uint16_t len = getCorrectedRawLength(&results);
  uint16_t* arr = resultToRawArray(&results);
  if (arr) {
    pending_.raw.assign(arr, arr + len);
    delete[] arr;
  }

  // Try to decode into a semantic AC state.
  if (IRAcUtils::decodeToState(&results, &pending_.decoded)) {
    pending_.hasDecoded = true;
    protocol_ = results.decode_type;
    Serial.printf("[IR] decoded AC protocol=%s\n",
                  typeToString(results.decode_type).c_str());
  } else {
    Serial.printf("[IR] captured raw (protocol=%s, %u entries)\n",
                  typeToString(results.decode_type).c_str(), len);
  }

  // Always store a raw copy under the label for guaranteed replay.
  storeRaw(captureLabel_, pending_.raw, pending_.freqKhz);
  saveToNvs();

  hasNewCapture_ = true;
  recv_.resume();
  stopCapture();   // one code per learn request; app re-arms for the next button
}

CapturedCode IrManager::takeCaptured() {
  hasNewCapture_ = false;
  return pending_;
}

void IrManager::applyToIrac(const AcState& s) {
  ac_.next.protocol  = protocol_;
  ac_.next.power     = s.power;
  ac_.next.mode      = mapMode(s.mode);
  ac_.next.degrees   = (float)s.tempC;
  ac_.next.celsius   = true;
  ac_.next.fanspeed  = mapFan(s.fan);
  ac_.next.swingv    = mapSwingV(s.swing);
  ac_.next.swingh    = mapSwingH(s.swing);
  ac_.next.light     = false;
  ac_.next.beep      = false;
  ac_.next.econo     = false;
  ac_.next.turbo     = false;
  ac_.next.quiet     = false;
  ac_.next.clean     = false;
  ac_.next.sleep     = -1;
  ac_.next.clock     = -1;
}

bool IrManager::sendState(const AcState& s) {
  if (protocol_ == decode_type_t::UNKNOWN) {
    Serial.println("[IR] sendState: no known protocol, fall back to raw replay");
    return false;
  }
  if (!IRac::isProtocolSupported(protocol_)) {
    Serial.println("[IR] sendState: protocol not IRac-supported, use raw replay");
    return false;
  }
  applyToIrac(s);
  bool ok = ac_.sendAc();
  Serial.printf("[IR] sendState power=%d mode=%s temp=%d fan=%s -> %d\n",
                s.power, toStr(s.mode), s.tempC, toStr(s.fan), ok);
  return ok;
}

bool IrManager::replayRaw(const String& label) {
  for (auto& c : rawCodes_) {
    if (c.label == label) {
      send_.sendRaw(c.timings.data(), c.timings.size(), c.freqKhz);
      Serial.printf("[IR] replayed raw '%s' (%u entries)\n", label.c_str(),
                    (unsigned)c.timings.size());
      return true;
    }
  }
  Serial.printf("[IR] replayRaw: label '%s' not found\n", label.c_str());
  return false;
}

void IrManager::storeRaw(const String& label, const std::vector<uint16_t>& timings,
                         uint16_t freqKhz) {
  for (auto& c : rawCodes_) {
    if (c.label == label) { c.timings = timings; c.freqKhz = freqKhz; return; }
  }
  if (rawCodes_.size() >= MAX_RAW_CODES) rawCodes_.erase(rawCodes_.begin());
  rawCodes_.push_back({label, timings, freqKhz});
}

bool IrManager::getRawLabels(std::vector<String>& out) const {
  for (auto& c : rawCodes_) out.push_back(c.label);
  return !out.empty();
}

// ---- NVS persistence ----
// Raw codes can be large; we store them under their own Preferences namespace,
// one blob per code, plus a comma-joined index of labels.
void IrManager::saveToNvs() const {
  Preferences p;
  p.begin("ircodes", false);
  p.putUChar("proto", (uint8_t)protocol_);
  String index;
  for (size_t i = 0; i < rawCodes_.size(); i++) {
    if (i) index += ",";
    index += rawCodes_[i].label;
    String key = "c" + String(i);
    const auto& t = rawCodes_[i].timings;
    p.putBytes(key.c_str(), t.data(), t.size() * sizeof(uint16_t));
    p.putUShort(("f" + String(i)).c_str(), rawCodes_[i].freqKhz);
  }
  p.putString("index", index);
  p.putUChar("count", (uint8_t)rawCodes_.size());
  p.end();
}

void IrManager::loadFromNvs() {
  Preferences p;
  p.begin("ircodes", true);
  protocol_ = (decode_type_t)p.getUChar("proto", (uint8_t)decode_type_t::UNKNOWN);
  String index = p.getString("index", "");
  uint8_t count = p.getUChar("count", 0);
  rawCodes_.clear();
  int start = 0;
  for (uint8_t i = 0; i < count; i++) {
    int comma = index.indexOf(',', start);
    String label = (comma < 0) ? index.substring(start) : index.substring(start, comma);
    start = comma + 1;
    String key = "c" + String(i);
    size_t bytes = p.getBytesLength(key.c_str());
    if (bytes) {
      std::vector<uint16_t> t(bytes / sizeof(uint16_t));
      p.getBytes(key.c_str(), t.data(), bytes);
      uint16_t f = p.getUShort(("f" + String(i)).c_str(), 38);
      rawCodes_.push_back({label, t, f});
    }
  }
  p.end();
  Serial.printf("[IR] loaded %u raw codes, protocol=%s\n",
                (unsigned)rawCodes_.size(), typeToString(protocol_).c_str());
}
