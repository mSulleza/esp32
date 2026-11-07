#include "ota.h"
#include <ArduinoJson.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Update.h>
#include <Preferences.h>
#include "mbedtls/md.h"
#include "mbedtls/pk.h"
#include "mbedtls/base64.h"
#include "esp_ota_ops.h"
#include "config.h"
#include "ota_pubkey.h"

static const char* NVS_NS  = "ota";
static const char* NVS_JOB = "pendingJob";   // jobId awaiting post-reboot confirm

// ---------------- helpers ----------------
static void toHex(const uint8_t* in, size_t n, char* out) {
  static const char* h = "0123456789abcdef";
  for (size_t i = 0; i < n; i++) { out[2*i] = h[in[i] >> 4]; out[2*i+1] = h[in[i] & 0xF]; }
  out[2*n] = 0;
}

// Verify ECDSA(P-256) signature (DER, base64) over a 32-byte SHA-256 digest.
static bool verifySignature(const uint8_t hash[32], const String& sigB64) {
  uint8_t der[160]; size_t derLen = 0;
  if (mbedtls_base64_decode(der, sizeof(der), &derLen,
        (const uint8_t*)sigB64.c_str(), sigB64.length()) != 0) return false;
  mbedtls_pk_context pk; mbedtls_pk_init(&pk);
  bool ok = mbedtls_pk_parse_public_key(&pk, (const uint8_t*)OTA_SIGNING_PUBKEY,
              strlen(OTA_SIGNING_PUBKEY) + 1) == 0
         && mbedtls_pk_verify(&pk, MBEDTLS_MD_SHA256, hash, 32, der, derLen) == 0;
  mbedtls_pk_free(&pk);
  return ok;
}

// ---------------- lifecycle ----------------
void Ota::begin(const char* thingName, const char* rootCaPem, PublishFn pub, SubscribeFn sub) {
  strncpy(thing_, thingName, sizeof(thing_) - 1);
  rootCa_ = rootCaPem;
  pub_ = pub; sub_ = sub;
  snprintf(tNotify_, sizeof(tNotify_), "$aws/things/%s/jobs/notify-next", thing_);
  snprintf(tGetAcc_, sizeof(tGetAcc_), "$aws/things/%s/jobs/$next/get/accepted", thing_);
  snprintf(tGet_,    sizeof(tGet_),    "$aws/things/%s/jobs/$next/get", thing_);
}

void Ota::onMqttConnect() {
  if (sub_) { sub_(tNotify_); sub_(tGetAcc_); }
  confirmBootIfPending();   // we just (re)connected — if this boot is post-OTA, finalize it
  requestNextJob();
}

void Ota::requestNextJob() { if (pub_) pub_(tGet_, "{}"); }

void Ota::loop() {
  if (state_ == REBOOTING && millis() >= rebootAt_) {
    Serial.println("[OTA] rebooting into new image...");
    delay(100);
    ESP.restart();
  }
}

// ---------------- post-reboot confirmation / rollback ----------------
void Ota::confirmBootIfPending() {
  Preferences p; p.begin(NVS_NS, false);
  String jobId = p.getString(NVS_JOB, "");
  if (jobId.isEmpty()) { p.end(); return; }

  // This boot is running the freshly-flashed image. Validate it so the bootloader
  // keeps it (cancels rollback); report success to the Job that installed it.
  const esp_partition_t* run = esp_ota_get_running_partition();
  esp_ota_img_states_t st;
  if (esp_ota_get_state_partition(run, &st) == ESP_OK && st == ESP_OTA_IMG_PENDING_VERIFY)
    esp_ota_mark_app_valid_cancel_rollback();

  updateJob(jobId, "SUCCEEDED", String("booted ") + FW_VERSION);
  p.remove(NVS_JOB); p.end();
  Serial.printf("[OTA] confirmed boot, job %s SUCCEEDED\n", jobId.c_str());
}

// ---------------- inbound Jobs messages ----------------
bool Ota::handleJobsMessage(const char* topic, const uint8_t* payload, unsigned int len) {
  char prefix[80]; snprintf(prefix, sizeof(prefix), "$aws/things/%s/jobs/", thing_);
  if (strncmp(topic, prefix, strlen(prefix)) != 0) return false;   // not ours

  // We only act on notify-next / $next/get/accepted (both carry an "execution").
  if (strcmp(topic, tNotify_) == 0 || strcmp(topic, tGetAcc_) == 0) {
    JsonDocument doc;
    if (deserializeJson(doc, payload, len)) return true;
    JsonObject ex = doc["execution"];
    if (ex.isNull()) return true;                 // no pending job
    if (state_ != IDLE) return true;              // already installing
    String jobId = (const char*)(ex["jobId"] | "");
    JsonObject jd = ex["jobDocument"];
    if (jobId.isEmpty() || jd.isNull()) return true;
    if (String((const char*)(jd["operation"] | "")) != "ota") return true;

    activeJob_ = jobId; state_ = INSTALLING;
    Serial.printf("[OTA] job %s accepted\n", jobId.c_str());
    updateJob(jobId, "IN_PROGRESS", "downloading");

    String err;
    bool ok = downloadVerifyFlash(
        (const char*)(jd["url"]    | ""), (size_t)(jd["size"] | 0),
        (const char*)(jd["sha256"] | ""), (const char*)(jd["sig"] | ""), err);
    if (!ok) {
      Serial.printf("[OTA] FAILED: %s\n", err.c_str());
      updateJob(jobId, "FAILED", err);
      state_ = IDLE; activeJob_ = "";
      return true;
    }
    // Flashed + verified. Persist jobId so the *next* boot reports SUCCEEDED, then reboot.
    { Preferences p; p.begin(NVS_NS, false); p.putString(NVS_JOB, jobId); p.end(); }
    updateJob(jobId, "IN_PROGRESS", "rebooting");
    state_ = REBOOTING; rebootAt_ = millis() + 1500;
  }
  return true;
}

// ---------------- job status reporting ----------------
void Ota::updateJob(const String& jobId, const char* status, const String& detail) {
  if (!pub_) return;
  char topic[112];
  snprintf(topic, sizeof(topic), "$aws/things/%s/jobs/%s/update", thing_, jobId.c_str());
  JsonDocument doc;
  doc["status"] = status;
  doc["statusDetails"]["detail"] = detail;
  char buf[256]; size_t n = serializeJson(doc, buf); buf[n] = 0;
  pub_(topic, buf);
}

// ---------------- download + verify + flash ----------------
bool Ota::downloadVerifyFlash(const String& url, size_t size,
                              const String& sha256Hex, const String& sigB64, String& err) {
  if (url.isEmpty() || sha256Hex.isEmpty() || sigB64.isEmpty()) { err = "bad job doc"; return false; }
  if (!url.startsWith("https://")) { err = "url not https"; return false; }
  if (!rootCa_ || !*rootCa_)       { err = "no root CA";    return false; }

  // Validate the S3 server certificate (chains to Amazon Root CA 1, the same
  // root used for AWS IoT). The ECDSA signature check below still decides
  // whether the image is flashed; TLS validation stops a man-in-the-middle from
  // substituting or tampering with the download in the first place.
  WiFiClientSecure client;
  client.setCACert(rootCa_);
  HTTPClient http;
  if (!http.begin(client, url)) { err = "http begin"; return false; }
  int code = http.GET();
  if (code != HTTP_CODE_OK) { http.end(); err = String("http ") + code; return false; }

  int len = http.getSize();
  size_t total = (len > 0) ? (size_t)len : size;
  if (total == 0 || !Update.begin(total)) { http.end(); err = "Update.begin"; return false; }

  mbedtls_md_context_t md; mbedtls_md_init(&md);
  mbedtls_md_setup(&md, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 0);
  mbedtls_md_starts(&md);

  WiFiClient* stream = http.getStreamPtr();
  uint8_t buf[1024]; size_t got = 0;
  bool writeOk = true;
  while (http.connected() && (len > 0 || len == -1)) {
    size_t avail = stream->available();
    if (avail) {
      int n = stream->readBytes(buf, avail > sizeof(buf) ? sizeof(buf) : avail);
      if (n <= 0) break;
      if (Update.write(buf, n) != (size_t)n) { writeOk = false; break; }
      mbedtls_md_update(&md, buf, n);
      got += n;
      if (len > 0) len -= n;
    } else delay(1);
    if (len == 0) break;
  }
  http.end();

  uint8_t hash[32]; mbedtls_md_finish(&md, hash); mbedtls_md_free(&md);

  if (!writeOk)      { Update.abort(); err = "flash write"; return false; }
  if (got != total)  { Update.abort(); err = String("short read ") + got + "/" + total; return false; }

  char hex[65]; toHex(hash, 32, hex);
  if (!sha256Hex.equalsIgnoreCase(hex)) { Update.abort(); err = "sha256 mismatch"; return false; }
  if (!verifySignature(hash, sigB64))   { Update.abort(); err = "bad signature";  return false; }

  if (!Update.end(true)) { err = String("Update.end ") + Update.getError(); return false; }
  Serial.printf("[OTA] verified + flashed %u bytes\n", (unsigned)got);
  return true;
}
