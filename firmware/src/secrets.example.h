// Copy this file to "secrets.h" and fill in your values.
// secrets.h is git-ignored — never commit real credentials or certificates.
#pragma once

// ---- Wi-Fi ----
#define WIFI_SSID       "your-ssid"
#define WIFI_PASSWORD   "your-password"

// ---- AWS IoT Core ----
// From `aws iot describe-endpoint --endpoint-type iot:Data-ATS`
#define AWS_IOT_ENDPOINT  "xxxxxxxxxxxxxx-ats.iot.ap-southeast-1.amazonaws.com"
#define AWS_IOT_PORT      8883
// Must match the IoT Thing name. Also used as the device/topic id.
#define DEVICE_ID         "ac-livingroom"

// ---- X.509 certificates (PEM) ----
// Paste the contents the CDK/IoT registration produced for this device.
static const char AWS_ROOT_CA[] = R"EOF(
-----BEGIN CERTIFICATE-----
... Amazon Root CA 1 ...
-----END CERTIFICATE-----
)EOF";

static const char DEVICE_CERT[] = R"EOF(
-----BEGIN CERTIFICATE-----
... device certificate ...
-----END CERTIFICATE-----
)EOF";

static const char DEVICE_PRIVATE_KEY[] = R"EOF(
-----BEGIN RSA PRIVATE KEY-----
... device private key ...
-----END RSA PRIVATE KEY-----
)EOF";
