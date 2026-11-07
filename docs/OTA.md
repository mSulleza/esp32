# OTA firmware updates (AWS IoT Jobs)

Remote, signed firmware updates delivered through **AWS IoT Jobs**. Updates are
**code-signed** (ECDSA P-256 over the image SHA-256) and verified on-device before
flashing, so only firmware you signed can ever install.

## How it works
```
build .bin ──> publish_ota.sh ──> sign (ECDSA) + upload to S3 + create IoT Job
                                          │
        IoT Job (per device/thing-group)  │  doc: {operation:ota, size, sha256, sig, url*}
                                          ▼
device  ◄── notify-next / $next/get ── AWS IoT Jobs
   │  HTTPS GET firmware (presigned S3 URL, presigned per-delivery by IoT)
   │  verify SHA-256 == doc.sha256  AND  ECDSA(sig) valid for embedded public key
   │  Update.write to the inactive OTA slot ──> persist jobId ──> reboot
   ▼
new image boots ──> on first healthy MQTT connect: mark image valid + report SUCCEEDED
```
*`url` is the placeholder `${aws:iot:s3-presigned-url:...}`; IoT substitutes a fresh
presigned URL each time it delivers the job (works even if the device was offline).

## One-time setup
1. **Generate the signing key pair** (private key stays secret; public key is embedded):
   ```bash
   openssl ecparam -name prime256v1 -genkey -noout -out ota_signing_key.pem
   openssl ec -in ota_signing_key.pem -pubout -out ota_signing_pub.pem
   ```
   Paste `ota_signing_pub.pem` into **`firmware/src/ota_pubkey.h`**. Keep
   `ota_signing_key.pem` off the device and out of git.
2. **Partitions** — already set: `firmware/platformio.ini` uses `min_spiffs.csv`
   (two ~1.9 MB OTA slots on the 4 MB module). Don't switch back to `huge_app` (single slot).
3. **Deploy the backend** (`cd backend/cdk && cdk deploy`). Note the two outputs:
   - `FirmwareBucket` — S3 bucket for the .bin files
   - `OtaPresignRoleArn` — role IoT uses to presign the download URL
   The device IoT policy already allows the `$aws/things/<thing>/jobs/*` topics.

## Publishing an update
```bash
cd firmware && pio run                 # builds .pio/build/esp32dev/firmware.bin
cd ../backend/tools
./publish_ota.sh \
  --thing ac-livingroom \
  --bin ../../firmware/.pio/build/esp32dev/firmware.bin \
  --version 1.1.0 \
  --bucket <FirmwareBucket> \
  --role   <OtaPresignRoleArn> \
  --key    ota_signing_key.pem
```
Target a fleet instead of one device with `--target-arn <thing-group-arn>`.

Track it:
```bash
aws iot describe-job-execution --job-id <printed-id> --thing-name ac-livingroom
```
The device reports `IN_PROGRESS` (downloading → rebooting) then `SUCCEEDED` once the
new image boots and reconnects; verification/flash failures report `FAILED` with a reason.

## Security model
- **Authenticity/integrity:** firmware is only flashed if its SHA-256 matches the job
  doc *and* the ECDSA signature verifies against the embedded public key. A tampered
  or wrong binary is rejected regardless of how it arrived.
- **Transport:** the HTTPS download validates the S3 server certificate against the
  same Amazon Root CA 1 (`AWS_ROOT_CA` in `secrets.h`) used for AWS IoT, and only
  `https://` URLs are accepted. If AWS ever moves S3 to a different root, add that
  root or the download fails closed (the job reports `FAILED`, nothing is flashed).
- **Access:** the S3 bucket is private; the device only ever sees a short-lived
  presigned URL minted by IoT at delivery.
- **Bump `FW_VERSION`** in `config.h` each release (it's reported on SUCCEEDED).

### Secrets are in every image
`secrets.h` (Wi-Fi password, the device certificate **and its private key**) is
compiled into the firmware, so every `.bin` you build — and the flash of every
device — contains them. Anyone with the binary, or physical access to a device and
a USB cable, can read them out with `esptool.py read_flash`.

- Treat built `.bin` files as secret: don't attach them to issues/releases, and
  keep the S3 firmware bucket private (it is).
- Build one image per device (each has its own cert) and revoke a device's
  certificate in IoT Core if the device or its image is lost.
- **Recommended:** enable ESP32 **flash encryption** (and ideally Secure Boot v2)
  in release mode so the flash can't simply be dumped. Both burn eFuses and are
  irreversible; they need a custom `sdkconfig` (ESP-IDF or Arduino-as-component)
  rather than the stock Arduino-ESP32 libs. Test on a spare board first.

### Known limitation: no anti-downgrade
The signature covers the image bytes only. Neither the job's `version` nor
`FW_VERSION` is signed or compared on the device, so anyone able to create IoT
Jobs (i.e. with your AWS credentials) can re-deliver **any older image you
signed**, including one with a since-fixed bug. Mitigations until the device
enforces a signed, monotonically increasing version (e.g. ESP-IDF secure version /
anti-rollback eFuses, or signing `version || sha256` and storing the last
accepted version in NVS): keep the signing key offline, restrict who can create
IoT Jobs, and rotate the signing key if an old image must never run again.

## Rollback (caveat)
The device marks the new image valid only after a healthy boot + MQTT reconnect, and
reports `SUCCEEDED` only then — so a job won't show success if the device never returns.
**True automatic rollback** (bootloader reverts a crashing image) requires
`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`, which the stock Arduino-ESP32 precompiled
libs do not enable. To get it, build with a custom `sdkconfig` (or the IDF framework).
Until then, a fatally-bad image must be recovered over USB.
