// REST API behind API Gateway HTTP API (Cognito-authorized).
// Routes by method + path; owns device CRUD-lite, telemetry queries, schedule
// management, command publishing, and learn-mode arming.
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import {
  DynamoDBDocumentClient, GetCommand, PutCommand, DeleteCommand,
  QueryCommand,
} from '@aws-sdk/lib-dynamodb';
import { IoTClient, DescribeEndpointCommand } from '@aws-sdk/client-iot';
import { IoTDataPlaneClient, PublishCommand } from '@aws-sdk/client-iot-data-plane';

const ddb = DynamoDBDocumentClient.from(new DynamoDBClient({}));
const DEVICES = process.env.DEVICES_TABLE;
const SCHEDULES = process.env.SCHEDULES_TABLE;
const TELEMETRY = process.env.TELEMETRY_TABLE;

// Resolve the IoT data endpoint once per container.
let iotData;
async function iot() {
  if (iotData) return iotData;
  const ep = await new IoTClient({}).send(
    new DescribeEndpointCommand({ endpointType: 'iot:Data-ATS' }));
  iotData = new IoTDataPlaneClient({ endpoint: `https://${ep.endpointAddress}` });
  return iotData;
}
async function publish(topic, payload) {
  const c = await iot();
  await c.send(new PublishCommand({
    topic, qos: 1, payload: Buffer.from(JSON.stringify(payload)),
  }));
}

const json = (code, body) => ({
  statusCode: code,
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body),
});
const reqId = () => 'req_' + Math.random().toString(36).slice(2, 12);

export const handler = async (event) => {
  const method = event.requestContext?.http?.method;
  const path = event.rawPath || '/';
  const sub = event.requestContext?.authorizer?.jwt?.claims?.sub;
  if (!sub) return json(401, { error: 'unauthorized' });

  const seg = path.split('/').filter(Boolean);   // e.g. ["devices","ac1","schedules"]
  const body = event.body ? JSON.parse(event.body) : {};

  try {
    // GET /devices
    if (method === 'GET' && seg[0] === 'devices' && seg.length === 1) {
      const r = await ddb.send(new QueryCommand({
        TableName: DEVICES, IndexName: 'byOwner',
        KeyConditionExpression: 'ownerSub = :s',
        ExpressionAttributeValues: { ':s': sub },
      }));
      return json(200, { devices: r.Items ?? [] });
    }

    const deviceId = seg[1];
    if (seg[0] === 'devices' && deviceId) {
      const dev = await getOwnedDevice(deviceId, sub);
      if (!dev) return json(404, { error: 'device not found or not yours' });

      // GET /devices/{id}
      if (method === 'GET' && seg.length === 2) return json(200, { device: dev });

      // POST /devices/{id}/command
      if (method === 'POST' && seg[2] === 'command') {
        const payload = { ...body, reqId: reqId() };
        await publish(`ac/${deviceId}/command`, payload);
        return json(202, { reqId: payload.reqId, delivered: true });
      }

      // POST /devices/{id}/capture  -> arm/disarm learn mode
      if (method === 'POST' && seg[2] === 'capture') {
        const payload = {
          cmd: 'capture', reqId: reqId(),
          enable: body.enable !== false,
          label: body.label || 'code',
          timeoutSec: body.timeoutSec || 30,
        };
        await publish(`ac/${deviceId}/command`, payload);
        return json(202, { reqId: payload.reqId });
      }

      // GET /devices/{id}/telemetry?from=&to=
      if (method === 'GET' && seg[2] === 'telemetry') {
        const q = event.queryStringParameters || {};
        const from = parseInt(q.from || (Date.now() - 24 * 3600e3), 10);
        const to = parseInt(q.to || Date.now(), 10);
        const r = await ddb.send(new QueryCommand({
          TableName: TELEMETRY,
          KeyConditionExpression: 'deviceId = :d AND ts BETWEEN :f AND :t',
          ExpressionAttributeValues: { ':d': deviceId, ':f': from, ':t': to },
          ScanIndexForward: true, Limit: 2000,
        }));
        return json(200, { points: r.Items ?? [] });
      }

      // GET /devices/{id}/codes
      if (method === 'GET' && seg[2] === 'codes') {
        return json(200, { codes: Object.keys(dev.codes || {}) });
      }

      // ----- schedules -----
      if (seg[2] === 'schedules') {
        if (method === 'GET' && seg.length === 3) {
          const r = await ddb.send(new QueryCommand({
            TableName: SCHEDULES,
            KeyConditionExpression: 'deviceId = :d',
            ExpressionAttributeValues: { ':d': deviceId },
          }));
          return json(200, { schedules: r.Items ?? [] });
        }
        // POST -> create one
        if (method === 'POST' && seg.length === 3) {
          const scheduleId = 'sch_' + Math.random().toString(36).slice(2, 10);
          const item = sanitizeSchedule(deviceId, scheduleId, body);
          await ddb.send(new PutCommand({ TableName: SCHEDULES, Item: item }));
          await syncSchedules(deviceId);
          return json(201, { scheduleId });
        }
        // PUT -> replace all
        if (method === 'PUT' && seg.length === 3) {
          const incoming = Array.isArray(body.schedules) ? body.schedules : [];
          // naive replace: delete existing then put new (fine for small N)
          const existing = await ddb.send(new QueryCommand({
            TableName: SCHEDULES,
            KeyConditionExpression: 'deviceId = :d',
            ExpressionAttributeValues: { ':d': deviceId },
          }));
          for (const e of existing.Items ?? [])
            await ddb.send(new DeleteCommand({ TableName: SCHEDULES, Key: { deviceId, scheduleId: e.scheduleId } }));
          for (const s of incoming) {
            const scheduleId = s.id || 'sch_' + Math.random().toString(36).slice(2, 10);
            await ddb.send(new PutCommand({ TableName: SCHEDULES, Item: sanitizeSchedule(deviceId, scheduleId, s) }));
          }
          await syncSchedules(deviceId);
          return json(200, { ok: true, count: incoming.length });
        }
        // DELETE /devices/{id}/schedules/{sid}
        if (method === 'DELETE' && seg.length === 4) {
          await ddb.send(new DeleteCommand({ TableName: SCHEDULES, Key: { deviceId, scheduleId: seg[3] } }));
          await syncSchedules(deviceId);
          return json(200, { ok: true });
        }
      }
    }

    return json(404, { error: 'route not found', method, path });
  } catch (err) {
    console.error(err);
    return json(500, { error: 'internal', detail: String(err) });
  }
};

async function getOwnedDevice(deviceId, sub) {
  const r = await ddb.send(new GetCommand({ TableName: DEVICES, Key: { deviceId } }));
  if (!r.Item) return null;
  if (r.Item.ownerSub && r.Item.ownerSub !== sub) return null;
  return r.Item;
}

function sanitizeSchedule(deviceId, scheduleId, b) {
  return {
    deviceId, scheduleId,
    id: scheduleId,
    enabled: b.enabled !== false,
    daysOfWeek: Array.isArray(b.daysOfWeek) ? b.daysOfWeek : [0, 1, 2, 3, 4, 5, 6],
    time: typeof b.time === 'string' ? b.time : '08:00',
    action: {
      power: !!b.action?.power,
      mode: b.action?.mode || 'cool',
      tempC: b.action?.tempC ?? 24,
      fan: b.action?.fan || 'auto',
      swing: b.action?.swing || 'off',
    },
    rawCodeId: b.rawCodeId || null,
    updatedAt: Date.now(),
  };
}

// Push the full schedule list to the device so it caches + fires locally.
async function syncSchedules(deviceId) {
  const r = await ddb.send(new QueryCommand({
    TableName: SCHEDULES,
    KeyConditionExpression: 'deviceId = :d',
    ExpressionAttributeValues: { ':d': deviceId },
  }));
  const schedules = (r.Items ?? []).map((s) => ({
    id: s.scheduleId, enabled: s.enabled, daysOfWeek: s.daysOfWeek,
    time: s.time, action: s.action, rawCodeId: s.rawCodeId,
  }));
  await publish(`ac/${deviceId}/schedules`, { ts: Date.now(), schedules });
}
