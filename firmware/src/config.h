// Compile-time configuration: pin map, timing, topics.
#pragma once

// ---- GPIO pin map (see docs/HARDWARE.md) ----
#define PIN_IR_TX        4    // RMT-capable; drives transistor base via 1k
#define PIN_IR_RX        14   // IR receiver OUT
#define PIN_I2C_SDA      21
#define PIN_I2C_SCL      22
#define PIN_STATUS_LED   2    // on-board LED
#define PIN_CAPTURE_BTN  0    // optional push-to-GND learn button (boot strap)

// ---- SHT40 (temp + humidity, fixed I2C address) ----
#define SHT40_ADDR  0x44

// ---- Timing ----
// Cost note: every telemetry publish is 1 IoT message + 1 DynamoDB write. Room
// temp/humidity change slowly, so we sample often but only *publish* on a
// meaningful change (delta) or a periodic heartbeat. This cuts cloud volume
// ~5-10x vs publishing every sample. See docs/COST.md.
#define SENSOR_SAMPLE_MS        30000UL   // how often we read the SHT40
#define TELEMETRY_HEARTBEAT_MS  600000UL  // force a publish at least every 10 min
#define TELEMETRY_DELTA_TEMP    0.3f      // °C change that triggers a publish
#define TELEMETRY_DELTA_HUM     2.0f      // %RH change that triggers a publish
#define SCHEDULE_TICK_MS        15000UL   // how often the schedule engine evaluates
#define MQTT_RECONNECT_MS       5000UL
#define CAPTURE_DEFAULT_TIMEOUT 30        // seconds in learn mode before auto-exit

// ---- Time / NTP ----
#define NTP_SERVER_1   "pool.ntp.org"
#define NTP_SERVER_2   "time.nist.gov"
// POSIX TZ string. Examples: "SGT-8" (Singapore), "GMT0BST,M3.5.0/1,M10.5.0"
// (UK), "EST5EDT,M3.2.0,M11.1.0" (US Eastern). Change to your zone.
#define TZ_STRING      "SGT-8"

// ---- IR capture buffer ----
#define IR_CAPTURE_BUFFER_SIZE  1024  // raw timing entries; AC frames are long
#define IR_CAPTURE_TIMEOUT      50    // ms idle gap that ends a capture
#define IR_MIN_UNKNOWN_SIZE     12

// ---- MQTT topics (printf templates, %s = DEVICE_ID) ----
#define TOPIC_TELEMETRY   "ac/%s/telemetry"
#define TOPIC_STATE       "ac/%s/state"
#define TOPIC_CAPTURED    "ac/%s/captured"
#define TOPIC_COMMAND     "ac/%s/command"
#define TOPIC_SCHEDULES   "ac/%s/schedules"
#define TOPIC_ACK         "ac/%s/ack"

// Setpoint range accepted from the cloud (most IRremoteESP8266 AC protocols
// support at least 16-30 °C). Keep in sync with TEMP_MIN_C / TEMP_MAX_C in
// backend/lambdas/api/index.mjs.
#define AC_MIN_TEMP_C   16
#define AC_MAX_TEMP_C   30

#define FW_VERSION   "1.0.0"
#define MAX_SCHEDULES   32
#define MAX_RAW_CODES   24
