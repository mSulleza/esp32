#!/usr/bin/env bash
# Sign + publish a firmware update as an AWS IoT Job (OTA).
#
# What it does:
#   1. SHA-256 the .bin and ECDSA-sign that hash with your private signing key
#      (the device verifies it with the public key embedded in ota_pubkey.h).
#   2. Upload the .bin to the firmware S3 bucket.
#   3. Create an IoT Job whose document carries {url(placeholder), size, sha256, sig}.
#      IoT presigns the S3 URL per-delivery using the OtaPresignRole.
#
# One-time key generation (keep the private key SECRET; commit only the public one):
#   openssl ecparam -name prime256v1 -genkey -noout -out ota_signing_key.pem
#   openssl ec -in ota_signing_key.pem -pubout -out ota_signing_pub.pem
#   # paste ota_signing_pub.pem into firmware/src/ota_pubkey.h
#
# Usage:
#   ./publish_ota.sh --thing ac-livingroom --bin ../../firmware/.pio/build/esp32dev/firmware.bin \
#                    --version 1.1.0 --bucket <FirmwareBucket> --role <OtaPresignRoleArn> \
#                    [--key ota_signing_key.pem] [--region ap-southeast-1] [--expires 3600]
#
# Target a fleet instead of one device by passing a thing-group ARN to --target-arn.
set -euo pipefail

KEY="ota_signing_key.pem"; REGION="${AWS_REGION:-ap-southeast-1}"; EXPIRES=3600
THING=""; BIN=""; VERSION=""; BUCKET=""; ROLE=""; TARGET_ARN=""
while [[ $# -gt 0 ]]; do case "$1" in
  --thing) THING="$2"; shift 2;;
  --bin) BIN="$2"; shift 2;;
  --version) VERSION="$2"; shift 2;;
  --bucket) BUCKET="$2"; shift 2;;
  --role) ROLE="$2"; shift 2;;
  --key) KEY="$2"; shift 2;;
  --region) REGION="$2"; shift 2;;
  --expires) EXPIRES="$2"; shift 2;;
  --target-arn) TARGET_ARN="$2"; shift 2;;
  *) echo "unknown arg: $1" >&2; exit 1;;
esac; done

[[ -f "$BIN" ]]    || { echo "need --bin <firmware.bin>"; exit 1; }
[[ -n "$VERSION" ]]|| { echo "need --version"; exit 1; }
[[ -n "$BUCKET" ]] || { echo "need --bucket <FirmwareBucket from CDK output>"; exit 1; }
[[ -n "$ROLE" ]]   || { echo "need --role <OtaPresignRoleArn from CDK output>"; exit 1; }
[[ -f "$KEY" ]]    || { echo "signing key $KEY not found (see keygen in header)"; exit 1; }

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
if [[ -z "$TARGET_ARN" ]]; then
  [[ -n "$THING" ]] || { echo "need --thing or --target-arn"; exit 1; }
  TARGET_ARN="arn:aws:iot:${REGION}:${ACCOUNT}:thing/${THING}"
fi

SHA=$(openssl dgst -sha256 -binary "$BIN" | xxd -p -c 256)
SIZE=$(stat -c%s "$BIN" 2>/dev/null || stat -f%z "$BIN")
SIG=$(openssl dgst -sha256 -sign "$KEY" "$BIN" | base64 | tr -d '\n')   # DER ECDSA sig, base64
KEYPATH="firmware/${VERSION}/firmware.bin"
JOB_ID="ota-${VERSION}-$(date +%s)"

echo "sha256 = $SHA"
echo "size   = $SIZE bytes"
echo "uploading s3://${BUCKET}/${KEYPATH}"
aws s3 cp "$BIN" "s3://${BUCKET}/${KEYPATH}" --region "$REGION"

DOC=$(cat <<JSON
{
  "operation": "ota",
  "version": "${VERSION}",
  "size": ${SIZE},
  "sha256": "${SHA}",
  "sig": "${SIG}",
  "url": "\${aws:iot:s3-presigned-url:https://s3.${REGION}.amazonaws.com/${BUCKET}/${KEYPATH}}"
}
JSON
)

echo "creating IoT Job ${JOB_ID} -> ${TARGET_ARN}"
aws iot create-job \
  --job-id "$JOB_ID" \
  --targets "$TARGET_ARN" \
  --document "$DOC" \
  --presigned-url-config "roleArn=${ROLE},expiresInSec=${EXPIRES}" \
  --target-selection SNAPSHOT \
  --region "$REGION"

echo "done. Track: aws iot describe-job-execution --job-id $JOB_ID --thing-name <thing> --region $REGION"
