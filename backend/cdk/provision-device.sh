#!/usr/bin/env bash
# Provision an AWS IoT device: Devices-table row (with its owner) + Thing +
# certificate + policy attachment.
#
# Usage: ./provision-device.sh <device-id> <output-dir> <owner-cognito-sub> [display-name]
#
# The owner's Cognito `sub` (not their email) is what the API checks. Look it up:
#   aws cognito-idp admin-get-user --user-pool-id <UserPoolId> --username <email> \
#     --query "UserAttributes[?Name=='sub'].Value" --output text
#
# The Devices table name is read from the AcControllerBackend stack outputs, or
# set DEVICES_TABLE to override.
set -euo pipefail

USAGE="usage: provision-device.sh <device-id> <output-dir> <owner-cognito-sub> [display-name]"
DEVICE_ID="${1:?$USAGE}"
OUT_DIR="${2:?$USAGE}"
OWNER_SUB="${3:?$USAGE}"
DEVICE_NAME="${4:-$DEVICE_ID}"
POLICY_NAME="AcDevicePolicy"
STACK_NAME="${STACK_NAME:-AcControllerBackend}"

# Thing names double as MQTT topic segments and DynamoDB keys: keep them plain
# (and short: the firmware holds the Thing name in a 48-byte buffer).
if ! [[ "$DEVICE_ID" =~ ^[A-Za-z0-9_-]{1,40}$ ]]; then
  echo "device-id must be 1-40 characters of A-Z, a-z, 0-9, _ or -" >&2; exit 1
fi
# Cognito subs are UUIDs.
if ! [[ "$OWNER_SUB" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  echo "owner-cognito-sub must be the user's Cognito sub (a UUID), not an email" >&2; exit 1
fi

DEVICES_TABLE="${DEVICES_TABLE:-$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='DevicesTableName'].OutputValue" --output text)}"
if [[ -z "$DEVICES_TABLE" || "$DEVICES_TABLE" == "None" ]]; then
  echo "could not find DevicesTableName output on stack $STACK_NAME; set DEVICES_TABLE" >&2; exit 1
fi

# Create the owned Devices row first. The condition refuses to overwrite an
# existing row, so re-running this can't hand someone else's device to a new
# owner. The ingest Lambda only updates rows that already exist, and the API only
# serves a device to its ownerSub, so a device is unusable until this row exists.
echo ">> Registering $DEVICE_ID in $DEVICES_TABLE"
ITEM=$(python3 -c 'import json,sys; print(json.dumps({"deviceId":{"S":sys.argv[1]},"ownerSub":{"S":sys.argv[2]},"name":{"S":sys.argv[3]}}))' \
  "$DEVICE_ID" "$OWNER_SUB" "$DEVICE_NAME")
aws dynamodb put-item --table-name "$DEVICES_TABLE" --item "$ITEM" \
  --condition-expression "attribute_not_exists(deviceId)"

umask 077   # the private key written below must not be world-readable
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
curl -fsS https://www.amazontrust.com/repository/AmazonRootCA1.pem \
  -o "$OUT_DIR/AmazonRootCA1.pem"

cat <<EOF

Done. $DEVICE_ID is registered to owner $OWNER_SUB. Files in $OUT_DIR:
  device.cert.pem      -> DEVICE_CERT in secrets.h
  device.private.key   -> DEVICE_PRIVATE_KEY in secrets.h
  AmazonRootCA1.pem    -> AWS_ROOT_CA in secrets.h (also validates the OTA download)

MQTT endpoint:
  $(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text)
EOF
