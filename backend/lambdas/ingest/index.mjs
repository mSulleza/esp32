// IoT Rule target for LOW-VOLUME messages only: state / captured / ack.
// (Telemetry is written to DynamoDB directly by an IoT Rule — it never reaches
// this Lambda — to avoid a per-message invoke. See the CDK stack.)
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, UpdateCommand } from '@aws-sdk/lib-dynamodb';

const ddb = DynamoDBDocumentClient.from(new DynamoDBClient({}));
const DEVICES = process.env.DEVICES_TABLE;

// Devices only ever UPDATE their own existing row. Rows are created (with an
// ownerSub) by backend/cdk/provision-device.sh; a check-in from a Thing with no
// row is logged and dropped instead of creating an ownerless row.
const MUST_EXIST = 'attribute_exists(deviceId)';

async function updateExisting(params) {
  try {
    await ddb.send(new UpdateCommand({ ...params, ConditionExpression: MUST_EXIST }));
    return true;
  } catch (e) {
    if (e.name === 'ConditionalCheckFailedException') {
      console.warn('ignoring message for unprovisioned device', JSON.stringify(params.Key.deviceId));
      return false;
    }
    throw e;
  }
}

export const handler = async (event) => {
  const { deviceId, kind } = event;
  if (!deviceId) { console.warn('no deviceId', event); return; }
  const now = Date.now();

  switch (kind) {
    case 'state': {
      await touchDevice(deviceId, {
        lastSeen: now,
        protocol: event.protocol,
        lastState: {
          power: event.power, mode: event.mode,
          tempC: event.tempC, fan: event.fan, swing: event.swing,
        },
      });
      break;
    }
    case 'captured': {
      // Store the learned code under the device for backup/restore.
      const label = event.label || 'code';
      const code = { decoded: event.decoded ?? null, raw: event.raw, ts: event.ts || now };
      try {
        await updateExisting({
          TableName: DEVICES,
          Key: { deviceId },
          UpdateExpression: 'SET codes.#l = :c, lastSeen = :now',
          ExpressionAttributeNames: { '#l': label },
          ExpressionAttributeValues: { ':c': code, ':now': now },
        });
      } catch (e) {
        // `codes` map may not exist yet; create it then retry.
        if (e.name !== 'ValidationException') throw e;
        await updateExisting({
          TableName: DEVICES,
          Key: { deviceId },
          UpdateExpression: 'SET codes = :m, lastSeen = :now',
          ExpressionAttributeValues: { ':m': { [label]: code }, ':now': now },
        });
      }
      break;
    }
    case 'ack':
      console.log('ack', deviceId, JSON.stringify(event));
      break;
    default:
      console.warn('unknown kind', kind);
  }
};

async function touchDevice(deviceId, attrs) {
  const sets = ['lastSeen = :ls'];
  const values = { ':ls': attrs.lastSeen || Date.now() };
  const names = {};
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'lastSeen' || v === undefined) continue;
    sets.push(`#${k} = :${k}`);
    names[`#${k}`] = k;
    values[`:${k}`] = v;
  }
  await updateExisting({
    TableName: DEVICES,
    Key: { deviceId },
    UpdateExpression: 'SET ' + sets.join(', '),
    ...(Object.keys(names).length ? { ExpressionAttributeNames: names } : {}),
    ExpressionAttributeValues: values,
  });
}
