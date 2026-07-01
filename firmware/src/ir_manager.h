// IR capture (learn) + send (decoded via IRac, or raw replay).
#pragma once
#include <Arduino.h>
#include <vector>
#include <IRrecv.h>
#include <IRsend.h>
#include <IRac.h>
#include <IRutils.h>
#include "ac_state.h"

// Result of a capture event handed to the cloud layer.
struct CapturedCode {
  bool        hasDecoded = false;
  stdAc::state_t decoded;      // valid when hasDecoded
  decode_type_t protocol = decode_type_t::UNKNOWN;
  std::vector<uint16_t> raw;   // raw timings (always populated)
  uint16_t    freqKhz = 38;
};

class IrManager {
public:
  IrManager();
  void begin();

  // Call every loop(); handles capture decode + timeout.
  void loop();

  // ---- Learn mode ----
  void startCapture(const String& label, uint16_t timeoutSec);
  void stopCapture();
  bool isCapturing() const { return capturing_; }
  // Set by loop() when a code is captured; consume via takeCaptured().
  bool hasNewCapture() const { return hasNewCapture_; }
  CapturedCode takeCaptured();         // returns + clears the pending capture
  String lastCaptureLabel() const { return captureLabel_; }

  // ---- Sending ----
  // Send a semantic state. Returns false if no protocol is known yet.
  bool sendState(const AcState& s);
  // Replay a previously-learned raw code by label. Returns false if unknown.
  bool replayRaw(const String& label);

  // ---- Learned protocol / codes ----
  bool hasKnownProtocol() const { return protocol_ != decode_type_t::UNKNOWN; }
  decode_type_t protocol() const { return protocol_; }
  void setProtocol(decode_type_t p) { protocol_ = p; }

  void storeRaw(const String& label, const std::vector<uint16_t>& timings, uint16_t freqKhz);
  bool getRawLabels(std::vector<String>& out) const;

  // NVS persistence of raw codes + protocol.
  void loadFromNvs();
  void saveToNvs() const;

private:
  IRrecv  recv_;
  IRsend  send_;
  IRac    ac_;
  decode_type_t protocol_ = decode_type_t::UNKNOWN;

  bool    capturing_ = false;
  bool    hasNewCapture_ = false;
  String  captureLabel_;
  uint32_t captureDeadlineMs_ = 0;
  CapturedCode pending_;

  struct RawCode { String label; std::vector<uint16_t> timings; uint16_t freqKhz; };
  std::vector<RawCode> rawCodes_;

  void applyToIrac(const AcState& s);
};
