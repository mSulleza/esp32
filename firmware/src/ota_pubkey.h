// OTA firmware-signing PUBLIC key (ECDSA P-256, SEC1/SPKI PEM).
// Not secret — it's the public half; safe to commit. The matching PRIVATE key
// stays on your build/signing machine and is used by tools/sign_firmware.py.
//
// Generate the pair once:
//   openssl ecparam -name prime256v1 -genkey -noout -out ota_signing_key.pem
//   openssl ec -in ota_signing_key.pem -pubout -out ota_signing_pub.pem
// then paste the contents of ota_signing_pub.pem below.
#pragma once

static const char OTA_SIGNING_PUBKEY[] = R"PEM(
-----BEGIN PUBLIC KEY-----
PASTE_YOUR_ota_signing_pub.pem_CONTENTS_HERE
-----END PUBLIC KEY-----
)PEM";
