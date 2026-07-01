// SHT40 temperature / humidity (Sensirion, I2C 0x44). No pressure.
#pragma once
#include <Arduino.h>

struct SensorReading {
  bool  valid = false;
  float tempC = NAN;
  float humidity = NAN;
};

class Sensors {
public:
  bool begin();                 // returns false if SHT40 not found
  SensorReading read();
  bool present() const { return present_; }
  uint8_t address() const { return addr_; }

private:
  bool present_ = false;
  uint8_t addr_ = 0;
};
