// AWS IoT Jobs OTA agent.
//
// Flow (AWS IoT Jobs MQTT protocol):
//   connect -> subscribe $aws/things/<thing>/jobs/notify-next + .../$next/get/accepted
//           -> publish {} to .../$next/get  (fetch any pending job)
//   job arrives -> parse jobDocument {operation:"ota", url, size, sha256, sig}
//           -> report IN_PROGRESS -> HTTPS download -> verify SHA-256 + ECDSA(P-256)
//           -> Update.write -> persist jobId -> reboot
//   after reboot -> new image validates health -> mark valid + report SUCCEEDED
//                   (a bad image that never marks valid is rolled back by the
//                    bootloader when rollback is enabled in sdkconfig)
//
// Firmware is authenticated by code signature (ECDSA over its SHA-256) using the
// public key in ota_pubkey.h. The HTTPS download is also certificate-validated
// against the root CA passed to begin() (Amazon Root CA 1 covers both AWS IoT
// and S3), so a network attacker cannot substitute or tamper with the download.
#pragma once
#include <Arduino.h>
#include <functional>

class Ota {
public:
  // Wire MQTT in/out through the Cloud layer (PubSubClient is private there).
  using PublishFn   = std::function<bool(const char* topic, const char* payload)>;
  using SubscribeFn = std::function<bool(const char* topic)>;

  // rootCaPem: PEM trust anchor for the HTTPS firmware download (must outlive Ota).
  void begin(const char* thingName, const char* rootCaPem, PublishFn pub, SubscribeFn sub);
  void onMqttConnect();        // (re)subscribe to Jobs topics + request next job
  void loop();                 // time-based retries / deferred reboot

  // Returns true if the message was a Jobs topic and was consumed.
  bool handleJobsMessage(const char* topic, const uint8_t* payload, unsigned int len);

  // Call once after the app is up and healthy: validates a freshly-flashed image
  // (cancels rollback) and reports SUCCEEDED for the job that installed it.
  void confirmBootIfPending();

  bool busy() const { return state_ != IDLE; }

private:
  enum State { IDLE, FETCHING, INSTALLING, REBOOTING };

  void requestNextJob();
  void startJob(const String& jobId, const char* jobDocJson, unsigned int len);
  void updateJob(const String& jobId, const char* status, const String& detail);
  bool downloadVerifyFlash(const String& url, size_t size,
                           const String& sha256Hex, const String& sigB64,
                           String& err);

  char thing_[48] = {0};
  const char* rootCa_ = nullptr;
  char tNotify_[96], tGetAcc_[96], tGet_[96];
  PublishFn pub_;
  SubscribeFn sub_;
  State state_ = IDLE;
  String activeJob_;
  uint32_t rebootAt_ = 0;
};
