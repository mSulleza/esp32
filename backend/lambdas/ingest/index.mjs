// IoT Rule target for LOW-VOLUME messages only: state / captured / ack.
// (Telemetry is written to DynamoDB directly by an IoT Rule — it never reaches
// this Lambda — to avoid a per-message invoke. See the CDK stack.)
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, UpdateCommand } from '@aws-sdk/lib-dynamodb';

const ddb = DynamoDBDocumentClient.from(new DynamoDBClient({}));
const DEVICES = process.env.DEVICES_TABLE;

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
      await ddb.send(new UpdateCommand({
        TableName: DEVICES,
        Key: { deviceId },
        UpdateExpression: 'SET codes.#l = :c, lastSeen = :now',
        ExpressionAttributeNames: { '#l': event.label || 'code' },
        ExpressionAttributeValues: {
          ':c': { decoded: event.decoded ?? null, raw: event.raw, ts: event.ts || now },
          ':now': now,
        },
      })).catch(async (e) => {
        // `codes` map may not exist yet; create it then retry.
        if (e.name === 'ValidationException') {
          await ddb.send(new UpdateCommand({
            TableName: DEVICES,
            Key: { deviceId },
            UpdateExpression: 'SET codes = :m, lastSeen = :now',
            ExpressionAttributeValues: {
              ':m': { [event.label || 'code']: { decoded: event.decoded ?? null, raw: event.raw, ts: event.ts || now } },
              ':now': now,
            },
          }));
        } else { throw e; }
      });
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
  await ddb.send(new UpdateCommand({
    TableName: DEVICES,
    Key: { deviceId },
    UpdateExpression: 'SET ' + sets.join(', '),
    ...(Object.keys(names).length ? { ExpressionAttributeNames: names } : {}),
    ExpressionAttributeValues: values,
  }));
}
