#include "sensors.h"
#include <Wire.h>
#include <Adafruit_SHT4x.h>
#include "config.h"

static Adafruit_SHT4x sht4;

bool Sensors::begin() {
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

  if (sht4.begin(&Wire)) {              // SHT40 lives at the fixed address 0x44
    present_ = true;
    addr_ = SHT40_ADDR;
    // Room sensing: highest precision, heater off (heater is only for condensation
    // recovery and would bias the temperature reading).
    sht4.setPrecision(SHT4X_HIGH_PRECISION);
    sht4.setHeater(SHT4X_NO_HEATER);
    Serial.printf("[SENSOR] SHT40 found at 0x%02X\n", SHT40_ADDR);
    return true;
  }
  Serial.println("[SENSOR] SHT40 NOT found (check wiring / address 0x44)");
  return false;
}

SensorReading Sensors::read() {
  SensorReading r;
  if (!present_) return r;
  sensors_event_t humidity, temp;
  if (!sht4.getEvent(&humidity, &temp)) return r;   // r.valid stays false on I2C error
  r.tempC = temp.temperature;
  r.humidity = humidity.relative_humidity;
  r.valid = !isnan(r.tempC) && !isnan(r.humidity);
  return r;
}
