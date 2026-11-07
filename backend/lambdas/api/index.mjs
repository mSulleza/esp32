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

// ---------------------------------------------------------------------------
// Input validation. Everything the API publishes to a device is rebuilt from
// validated fields; unknown keys are rejected rather than passed through.
// ---------------------------------------------------------------------------
// Setpoint range accepted by the API. Keep in sync with AC_MIN_TEMP_C /
// AC_MAX_TEMP_C in firmware/src/config.h (the firmware clamps to the same range).
const TEMP_MIN_C = 16;
const TEMP_MAX_C = 30;
const MODES  = ['cool', 'heat', 'dry', 'fan', 'auto'];
const FANS   = ['auto', 'low', 'med', 'high', 'max'];
const SWINGS = ['off', 'vertical', 'horizontal', 'both'];
const CMDS   = ['setState', 'replay', 'capture', 'identify', 'getState'];
// Learned-code labels become NVS keys / a comma-joined index on the device.
const LABEL_RE = /^[A-Za-z0-9_-]{1,32}$/;
const SCHEDULE_ID_RE = /^[A-Za-z0-9_-]{1,32}$/;
const TIME_RE = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;   // HH:MM, 24h
const MAX_BODY_BYTES = 16 * 1024;
const MAX_CAPTURE_TIMEOUT_SEC = 300;
const MAX_SCHEDULES = 32;              // firmware MAX_SCHEDULES (config.h)
// The schedule list is pushed to the device in one MQTT message; the firmware's
// PubSubClient buffer is 2048 bytes including the MQTT header and topic.
const MAX_SCHEDULE_SYNC_BYTES = 1800;

class BadRequest extends Error {}
const fail = (msg) => { throw new BadRequest(msg); };
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const showKey = (k) => JSON.stringify(String(k).slice(0, 40));

function onlyKeys(o, allowed, where) {
  if (!isObj(o)) fail(`${where} must be a JSON object`);
  for (const k of Object.keys(o))
    if (!allowed.includes(k)) fail(`${where}: unexpected field ${showKey(k)}`);
}
function optBool(v, def, where) {
  if (v === undefined) return def;
  if (typeof v !== 'boolean') fail(`${where} must be true or false`);
  return v;
}
function optEnum(v, allowed, def, where) {
  if (v === undefined) return def;
  if (!allowed.includes(v)) fail(`${where} must be one of ${allowed.join(', ')}`);
  return v;
}
function optInt(v, min, max, def, where) {
  if (v === undefined) return def;
  if (!Number.isInteger(v) || v < min || v > max) fail(`${where} must be an integer ${min}-${max}`);
  return v;
}
function label(v, where) {
  if (typeof v !== 'string' || !LABEL_RE.test(v))
    fail(`${where} must be 1-32 characters of A-Z, a-z, 0-9, _ or -`);
  return v;
}

function parseBody(event) {
  if (!event.body) return {};
  const raw = event.isBase64Encoded
    ? Buffer.from(event.body, 'base64').toString('utf8') : event.body;
  if (Buffer.byteLength(raw, 'utf8') > MAX_BODY_BYTES) fail('body too large');
  let v;
  try { v = JSON.parse(raw); } catch { fail('body is not valid JSON'); }
  if (!isObj(v)) fail('body must be a JSON object');
  return v;
}

// A target AC state; missing fields get the same defaults the firmware uses.
function validateAcState(s, where) {
  onlyKeys(s, ['power', 'mode', 'tempC', 'fan', 'swing'], where);
  return {
    power: optBool(s.power, false, `${where}.power`),
    mode:  optEnum(s.mode, MODES, 'cool', `${where}.mode`),
    tempC: optInt(s.tempC, TEMP_MIN_C, TEMP_MAX_C, 24, `${where}.tempC`),
    fan:   optEnum(s.fan, FANS, 'auto', `${where}.fan`),
    swing: optEnum(s.swing, SWINGS, 'off', `${where}.swing`),
  };
}

function validateCapture(b) {
  return {
    enable: optBool(b.enable, true, 'enable'),
    label: b.label === undefined ? 'code' : label(b.label, 'label'),
    timeoutSec: optInt(b.timeoutSec, 1, MAX_CAPTURE_TIMEOUT_SEC, 30, 'timeoutSec'),
  };
}

// Body of POST /devices/{id}/command. A client-sent reqId is accepted for
// compatibility but ignored: the server always assigns its own.
function validateCommand(b) {
  if (!CMDS.includes(b.cmd)) fail(`cmd must be one of ${CMDS.join(', ')}`);
  switch (b.cmd) {
    case 'setState':
      onlyKeys(b, ['cmd', 'reqId', 'state'], 'command');
      return { cmd: b.cmd, state: validateAcState(b.state, 'state') };
    case 'replay':
      onlyKeys(b, ['cmd', 'reqId', 'rawCodeId'], 'command');
      return { cmd: b.cmd, rawCodeId: label(b.rawCodeId, 'rawCodeId') };
    case 'capture':
      onlyKeys(b, ['cmd', 'reqId', 'enable', 'label', 'timeoutSec'], 'command');
      return { cmd: b.cmd, ...validateCapture(b) };
    default:   // identify, getState
      onlyKeys(b, ['cmd', 'reqId'], 'command');
      return { cmd: b.cmd };
  }
}

// One schedule. deviceId / scheduleId / updatedAt (as returned by GET) are
// accepted so a GET -> edit -> PUT round trip works; the path deviceId and the
// server clock always win.
function validateSchedule(b, where) {
  onlyKeys(b, ['id', 'scheduleId', 'deviceId', 'updatedAt', 'enabled',
               'daysOfWeek', 'time', 'action', 'rawCodeId'], where);
  let days = [0, 1, 2, 3, 4, 5, 6];
  if (b.daysOfWeek !== undefined) {
    const d = b.daysOfWeek;
    if (!Array.isArray(d) || d.length < 1 || d.length > 7 ||
        !d.every((x) => Number.isInteger(x) && x >= 0 && x <= 6) ||
        new Set(d).size !== d.length)
      fail(`${where}.daysOfWeek must be 1-7 distinct integers 0-6 (0 = Sunday)`);
    days = [...d].sort((x, y) => x - y);
  }
  if (typeof b.time !== 'string' || !TIME_RE.test(b.time))
    fail(`${where}.time must be "HH:MM" (00:00-23:59)`);
  const id = b.id ?? b.scheduleId;
  if (id !== undefined && (typeof id !== 'string' || !SCHEDULE_ID_RE.test(id)))
    fail(`${where}.id must be 1-32 characters of A-Z, a-z, 0-9, _ or -`);
  return {
    id,
    enabled: optBool(b.enabled, true, `${where}.enabled`),
    daysOfWeek: days,
    time: b.time,
    action: validateAcState(b.action ?? {}, `${where}.action`),
    rawCodeId: b.rawCodeId == null ? null : label(b.rawCodeId, `${where}.rawCodeId`),
  };
}

const newScheduleId = () => 'sch_' + Math.random().toString(36).slice(2, 10);

function scheduleItem(deviceId, scheduleId, v) {
  return {
    deviceId, scheduleId,
    id: scheduleId,
    enabled: v.enabled,
    daysOfWeek: v.daysOfWeek,
    time: v.time,
    action: v.action,
    rawCodeId: v.rawCodeId,
    updatedAt: Date.now(),
  };
}

// What the device receives on ac/{id}/schedules.
const toDeviceSchedule = (s) => ({
  id: s.scheduleId, enabled: s.enabled, daysOfWeek: s.daysOfWeek,
  time: s.time, action: s.action, rawCodeId: s.rawCodeId,
});
function checkSyncSize(items) {
  if (items.length > MAX_SCHEDULES) fail(`at most ${MAX_SCHEDULES} schedules per device`);
  const bytes = Buffer.byteLength(JSON.stringify(
    { ts: Date.now(), schedules: items.map(toDeviceSchedule) }), 'utf8');
  if (bytes > MAX_SCHEDULE_SYNC_BYTES)
    fail(`schedule list too large for the device (${bytes} > ${MAX_SCHEDULE_SYNC_BYTES} bytes); use fewer schedules`);
}

export const handler = async (event) => {
  const method = event.requestContext?.http?.method;
  const path = event.rawPath || '/';
  const sub = event.requestContext?.authorizer?.jwt?.claims?.sub;
  if (!sub) return json(401, { error: 'unauthorized' });

  const seg = path.split('/').filter(Boolean);   // e.g. ["devices","ac1","schedules"]

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
        const payload = { ...validateCommand(parseBody(event)), reqId: reqId() };
        await publish(`ac/${deviceId}/command`, payload);
        return json(202, { reqId: payload.reqId, delivered: true });
      }

      // POST /devices/{id}/capture  -> arm/disarm learn mode
      if (method === 'POST' && seg[2] === 'capture') {
        const body = parseBody(event);
        onlyKeys(body, ['enable', 'label', 'timeoutSec'], 'body');
        const payload = { cmd: 'capture', reqId: reqId(), ...validateCapture(body) };
        await publish(`ac/${deviceId}/command`, payload);
        return json(202, { reqId: payload.reqId });
      }

      // GET /devices/{id}/telemetry?from=&to=
      if (method === 'GET' && seg[2] === 'telemetry') {
        const q = event.queryStringParameters || {};
        const from = q.from === undefined ? Date.now() - 24 * 3600e3 : Number(q.from);
        const to = q.to === undefined ? Date.now() : Number(q.to);
        if (!Number.isSafeInteger(from) || !Number.isSafeInteger(to) || from < 0 || to < from)
          fail('from/to must be epoch milliseconds with from <= to');
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
          return json(200, { schedules: await listSchedules(deviceId) });
        }
        // POST -> create one
        if (method === 'POST' && seg.length === 3) {
          const v = validateSchedule(parseBody(event), 'schedule');
          const scheduleId = newScheduleId();   // server-assigned; any body id is ignored
          const item = scheduleItem(deviceId, scheduleId, v);
          const existing = await listSchedules(deviceId);
          checkSyncSize([...existing, item]);
          await ddb.send(new PutCommand({ TableName: SCHEDULES, Item: item }));
          await syncSchedules(deviceId);
          return json(201, { scheduleId });
        }
        // PUT -> replace all
        if (method === 'PUT' && seg.length === 3) {
          const body = parseBody(event);
          onlyKeys(body, ['schedules'], 'body');
          if (!Array.isArray(body.schedules)) fail('schedules must be an array');
          if (body.schedules.length > MAX_SCHEDULES) fail(`at most ${MAX_SCHEDULES} schedules per device`);
          const items = body.schedules.map((s, i) => {
            const v = validateSchedule(s, `schedules[${i}]`);
            return scheduleItem(deviceId, v.id ?? newScheduleId(), v);
          });
          if (new Set(items.map((x) => x.scheduleId)).size !== items.length)
            fail('schedule ids must be unique');
          checkSyncSize(items);
          // naive replace: delete existing then put new (fine for small N)
          for (const e of await listSchedules(deviceId))
            await ddb.send(new DeleteCommand({ TableName: SCHEDULES, Key: { deviceId, scheduleId: e.scheduleId } }));
          for (const item of items)
            await ddb.send(new PutCommand({ TableName: SCHEDULES, Item: item }));
          await syncSchedules(deviceId);
          return json(200, { ok: true, count: items.length });
        }
        // DELETE /devices/{id}/schedules/{sid}
        if (method === 'DELETE' && seg.length === 4) {
          if (!SCHEDULE_ID_RE.test(seg[3])) fail('bad schedule id');
          await ddb.send(new DeleteCommand({ TableName: SCHEDULES, Key: { deviceId, scheduleId: seg[3] } }));
          await syncSchedules(deviceId);
          return json(200, { ok: true });
        }
      }
    }

    return json(404, { error: 'route not found', method, path });
  } catch (err) {
    if (err instanceof BadRequest) return json(400, { error: 'bad request', detail: err.message });
    // Full error goes to CloudWatch only; clients get an opaque id to quote.
    const requestId = event.requestContext?.requestId;
    console.error('unhandled error', { requestId, method, path }, err);
    return json(500, { error: 'internal', requestId });
  }
};

// Only the recorded owner may see or control a device. A row with no ownerSub
// is not claimable by whoever asks first: provision-device.sh writes the owner.
async function getOwnedDevice(deviceId, sub) {
  const r = await ddb.send(new GetCommand({ TableName: DEVICES, Key: { deviceId } }));
  if (!r.Item || r.Item.ownerSub !== sub) return null;
  return r.Item;
}

async function listSchedules(deviceId) {
  const r = await ddb.send(new QueryCommand({
    TableName: SCHEDULES,
    KeyConditionExpression: 'deviceId = :d',
    ExpressionAttributeValues: { ':d': deviceId },
  }));
  return r.Items ?? [];
}

// Push the full schedule list to the device so it caches + fires locally.
async function syncSchedules(deviceId) {
  const schedules = (await listSchedules(deviceId)).map(toDeviceSchedule);
  await publish(`ac/${deviceId}/schedules`, { ts: Date.now(), schedules });
}
