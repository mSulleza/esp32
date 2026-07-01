#!/usr/bin/env bash
# Provision an AWS IoT device: Thing + certificate + policy attachment.
# Usage: ./provision-device.sh <device-id> <output-dir>
set -euo pipefail

DEVICE_ID="${1:?usage: provision-device.sh <device-id> <output-dir>}"
OUT_DIR="${2:?usage: provision-device.sh <device-id> <output-dir>}"
POLICY_NAME="AcDevicePolicy"

mkdir -p "$OUT_DIR"
echo ">> Creating Thing: $DEVICE_ID"
aws iot create-thing --thing-name "$DEVICE_ID" >/dev/null

echo ">> Creating keys + certificate"
CERT_ARN=$(aws iot create-keys-and-certificate \
  --set-as-active \
  --certificate-pem-outfile "$OUT_DIR/device.cert.pem" \
  --private-key-outfile "$OUT_DIR/device.private.key" \
  --public-key-outfile "$OUT_DIR/device.public.key" \
  --query certificateArn --output text)
echo "   cert ARN: $CERT_ARN"

echo ">> Attaching policy '$POLICY_NAME' and Thing"
aws iot attach-policy --policy-name "$POLICY_NAME" --target "$CERT_ARN"
aws iot attach-thing-principal --thing-name "$DEVICE_ID" --principal "$CERT_ARN"

echo ">> Downloading Amazon Root CA 1"
curl -s https://www.amazontrust.com/repository/AmazonRootCA1.pem \
  -o "$OUT_DIR/AmazonRootCA1.pem"

cat <<EOF

Done. Files in $OUT_DIR:
  device.cert.pem      -> DEVICE_CERT in secrets.h
  device.private.key   -> DEVICE_PRIVATE_KEY in secrets.h
  AmazonRootCA1.pem    -> AWS_ROOT_CA in secrets.h

MQTT endpoint:
  $(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text)
EOF
