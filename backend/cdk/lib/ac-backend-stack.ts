import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as iot from 'aws-cdk-lib/aws-iot';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as apigw from 'aws-cdk-lib/aws-apigatewayv2';
import * as apigwInteg from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as apigwAuth from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as path from 'path';

// Set to an email to receive a billing alert if monthly spend exceeds the cap.
const BUDGET_ALERT_EMAIL = process.env.BUDGET_ALERT_EMAIL ?? '';
const MONTHLY_BUDGET_USD = Number(process.env.MONTHLY_BUDGET_USD ?? '5');

export class AcBackendStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ----------------------------------------------------------------
    // DynamoDB
    // ----------------------------------------------------------------
    const devices = new dynamodb.Table(this, 'Devices', {
      partitionKey: { name: 'deviceId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    // Query devices by owner (Cognito sub).
    devices.addGlobalSecondaryIndex({
      indexName: 'byOwner',
      partitionKey: { name: 'ownerSub', type: dynamodb.AttributeType.STRING },
    });

    const schedules = new dynamodb.Table(this, 'Schedules', {
      partitionKey: { name: 'deviceId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'scheduleId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const telemetry = new dynamodb.Table(this, 'Telemetry', {
      partitionKey: { name: 'deviceId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'ts', type: dynamodb.AttributeType.NUMBER },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'expireAt',   // auto-purge old rows (30 days, set by rule)
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ----------------------------------------------------------------
    // Cognito (user auth for the app/API)
    // ----------------------------------------------------------------
    const userPool = new cognito.UserPool(this, 'UserPool', {
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    const userPoolClient = userPool.addClient('AppClient', {
      authFlows: { userPassword: true, userSrp: true },
    });

    // ----------------------------------------------------------------
    // Lambda: ingest (IoT Rule target) — state / captured / ack only.
    // Telemetry does NOT go through Lambda — it's written to DynamoDB directly
    // by an IoT Rule (cheaper, no cold starts, no per-message invoke). See below.
    // ARM64 (Graviton, ~20% cheaper) + 128 MB + 1-week log retention to keep
    // CloudWatch Logs (a silent cost) from accumulating.
    // ----------------------------------------------------------------
    const ingestFn = new lambda.Function(this, 'IngestFn', {
      runtime: lambda.Runtime.NODEJS_20_X,
      architecture: lambda.Architecture.ARM_64,
      memorySize: 128,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../lambdas/ingest')),
      timeout: cdk.Duration.seconds(15),
      logRetention: logs.RetentionDays.ONE_WEEK,
      environment: {
        DEVICES_TABLE: devices.tableName,
      },
    });
    devices.grantReadWriteData(ingestFn);

    // ----------------------------------------------------------------
    // Lambda: api (HTTP API handler)
    // ----------------------------------------------------------------
    const apiFn = new lambda.Function(this, 'ApiFn', {
      runtime: lambda.Runtime.NODEJS_20_X,
      architecture: lambda.Architecture.ARM_64,
      memorySize: 256,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../lambdas/api')),
      timeout: cdk.Duration.seconds(15),
      logRetention: logs.RetentionDays.ONE_WEEK,
      environment: {
        DEVICES_TABLE: devices.tableName,
        SCHEDULES_TABLE: schedules.tableName,
        TELEMETRY_TABLE: telemetry.tableName,
      },
    });
    devices.grantReadWriteData(apiFn);
    schedules.grantReadWriteData(apiFn);
    telemetry.grantReadData(apiFn);

    // Allow the API lambda to publish MQTT (commands + schedule sync) and
    // update device shadows.
    apiFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['iot:Publish', 'iot:GetThingShadow', 'iot:UpdateThingShadow'],
      resources: [
        `arn:aws:iot:${this.region}:${this.account}:topic/ac/*`,
        `arn:aws:iot:${this.region}:${this.account}:thing/*`,
      ],
    }));
    // The lambda needs the IoT data endpoint at runtime.
    apiFn.addEnvironment('IOT_ENDPOINT_HINT', 'use iot:DescribeEndpoint at deploy or set manually');

    // ----------------------------------------------------------------
    // HTTP API + Cognito authorizer
    // ----------------------------------------------------------------
    const authorizer = new apigwAuth.HttpUserPoolAuthorizer('Authorizer', userPool, {
      userPoolClients: [userPoolClient],
    });
    const httpApi = new apigw.HttpApi(this, 'HttpApi', {
      corsPreflight: {
        allowOrigins: ['*'],
        allowMethods: [apigw.CorsHttpMethod.ANY],
        allowHeaders: ['authorization', 'content-type'],
      },
    });
    const integration = new apigwInteg.HttpLambdaIntegration('ApiInteg', apiFn);
    // One catch-all route; the lambda routes internally by method+path.
    httpApi.addRoutes({
      path: '/{proxy+}',
      methods: [apigw.HttpMethod.ANY],
      integration,
      authorizer,
    });

    // ----------------------------------------------------------------
    // IoT Topic Rules
    //
    // Telemetry  -> DynamoDB DIRECTLY (no Lambda): cheapest path, one write per
    //               message, server-side timestamp + computed 30-day TTL.
    // state/captured/ack -> ingest Lambda (low volume, needs merge logic).
    // ----------------------------------------------------------------
    ingestFn.grantInvoke(new iam.ServicePrincipal('iot.amazonaws.com'));

    // Role the telemetry rule assumes to PutItem into the Telemetry table.
    const telemetryRuleRole = new iam.Role(this, 'TelemetryRuleRole', {
      assumedBy: new iam.ServicePrincipal('iot.amazonaws.com'),
    });
    telemetry.grantWriteData(telemetryRuleRole);

    // Direct DynamoDB write. Uses server timestamp() (ms) as the sort key so
    // ordering is correct even if the device clock isn't NTP-synced, and
    // computes a 30-day TTL inline. Only stores fields we query on.
    new iot.CfnTopicRule(this, 'AcTelemetryRule', {
      ruleName: 'AcTelemetryRule',
      topicRulePayload: {
        awsIotSqlVersion: '2016-03-23',
        sql:
          "SELECT topic(2) AS deviceId, timestamp() AS ts, tempC, humidity, " +
          "rssi, (floor(timestamp() / 1000) + 2592000) AS expireAt " +
          "FROM 'ac/+/telemetry'",
        actions: [{
          dynamoDBv2: {
            putItem: { tableName: telemetry.tableName },
            roleArn: telemetryRuleRole.roleArn,
          },
        }],
      },
    });

    const makeLambdaRule = (name: string, topic: string, kind: string) =>
      new iot.CfnTopicRule(this, name, {
        ruleName: name,
        topicRulePayload: {
          awsIotSqlVersion: '2016-03-23',
          sql: `SELECT *, topic(2) AS deviceId, '${kind}' AS kind FROM '${topic}'`,
          actions: [{ lambda: { functionArn: ingestFn.functionArn } }],
        },
      });

    makeLambdaRule('AcStateRule',    'ac/+/state',    'state');
    makeLambdaRule('AcCapturedRule', 'ac/+/captured', 'captured');
    makeLambdaRule('AcAckRule',      'ac/+/ack',      'ack');

    // ----------------------------------------------------------------
    // IoT policy for devices (scoped to their own thing/topics)
    // Attach this policy to each device certificate at provisioning time.
    // ----------------------------------------------------------------
    new iot.CfnPolicy(this, 'DevicePolicy', {
      policyName: 'AcDevicePolicy',
      policyDocument: {
        Version: '2012-10-17',
        Statement: [
          {
            Effect: 'Allow',
            Action: ['iot:Connect'],
            Resource: [`arn:aws:iot:${this.region}:${this.account}:client/\${iot:Connection.Thing.ThingName}`],
          },
          {
            Effect: 'Allow',
            Action: ['iot:Publish', 'iot:Receive'],
            Resource: [`arn:aws:iot:${this.region}:${this.account}:topic/ac/\${iot:Connection.Thing.ThingName}/*`],
          },
          {
            Effect: 'Allow',
            Action: ['iot:Subscribe'],
            Resource: [`arn:aws:iot:${this.region}:${this.account}:topicfilter/ac/\${iot:Connection.Thing.ThingName}/*`],
          },
          {
            Effect: 'Allow',
            Action: ['iot:Publish', 'iot:Receive', 'iot:GetThingShadow', 'iot:UpdateThingShadow'],
            Resource: [`arn:aws:iot:${this.region}:${this.account}:topic/$aws/things/\${iot:Connection.Thing.ThingName}/shadow/*`],
          },
          {
            Effect: 'Allow',
            Action: ['iot:Subscribe'],
            Resource: [`arn:aws:iot:${this.region}:${this.account}:topicfilter/$aws/things/\${iot:Connection.Thing.ThingName}/shadow/*`],
          },
          // OTA via AWS IoT Jobs: device fetches/updates its own job executions.
          {
            Effect: 'Allow',
            Action: ['iot:Publish', 'iot:Receive'],
            Resource: [`arn:aws:iot:${this.region}:${this.account}:topic/$aws/things/\${iot:Connection.Thing.ThingName}/jobs/*`],
          },
          {
            Effect: 'Allow',
            Action: ['iot:Subscribe'],
            Resource: [`arn:aws:iot:${this.region}:${this.account}:topicfilter/$aws/things/\${iot:Connection.Thing.ThingName}/jobs/*`],
          },
        ],
      },
    });

    // ----------------------------------------------------------------
    // OTA firmware artifacts. The publish script (backend/tools/publish_ota.sh)
    // uploads signed .bin files here and hands the device a presigned GET URL via
    // the IoT Job document. Private bucket — access only through presigned URLs.
    // ----------------------------------------------------------------
    const firmware = new s3.Bucket(this, 'Firmware', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [{ noncurrentVersionExpiration: cdk.Duration.days(90) }],
    });
    new cdk.CfnOutput(this, 'FirmwareBucket', { value: firmware.bucketName });

    // Role IoT assumes to presign the firmware URL when it *delivers* each job
    // execution (so the URL is fresh even if the device was offline at publish time).
    const otaPresignRole = new iam.Role(this, 'OtaPresignRole', {
      assumedBy: new iam.ServicePrincipal('iot.amazonaws.com'),
    });
    firmware.grantRead(otaPresignRole);
    new cdk.CfnOutput(this, 'OtaPresignRoleArn', { value: otaPresignRole.roleArn });

    // ----------------------------------------------------------------
    // Cost guardrail: monthly budget with alerts at 80% (forecast) and 100%.
    // The real footgun isn't steady-state cost (pennies) — it's a misconfig
    // running up a bill silently. This makes that impossible.
    // Set BUDGET_ALERT_EMAIL to enable email notifications.
    // ----------------------------------------------------------------
    if (BUDGET_ALERT_EMAIL) {
      new budgets.CfnBudget(this, 'MonthlyBudget', {
        budget: {
          budgetName: 'AcControllerMonthly',
          budgetType: 'COST',
          timeUnit: 'MONTHLY',
          budgetLimit: { amount: MONTHLY_BUDGET_USD, unit: 'USD' },
        },
        notificationsWithSubscribers: [
          {
            notification: {
              notificationType: 'FORECASTED',
              comparisonOperator: 'GREATER_THAN',
              threshold: 80,
              thresholdType: 'PERCENTAGE',
            },
            subscribers: [{ subscriptionType: 'EMAIL', address: BUDGET_ALERT_EMAIL }],
          },
          {
            notification: {
              notificationType: 'ACTUAL',
              comparisonOperator: 'GREATER_THAN',
              threshold: 100,
              thresholdType: 'PERCENTAGE',
            },
            subscribers: [{ subscriptionType: 'EMAIL', address: BUDGET_ALERT_EMAIL }],
          },
        ],
      });
    }

    // ----------------------------------------------------------------
    // Outputs
    // ----------------------------------------------------------------
    new cdk.CfnOutput(this, 'ApiUrl', { value: httpApi.apiEndpoint });
    new cdk.CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new cdk.CfnOutput(this, 'UserPoolClientId', { value: userPoolClient.userPoolClientId });
    new cdk.CfnOutput(this, 'DevicesTableName', { value: devices.tableName });
    new cdk.CfnOutput(this, 'IotEndpointHint', {
      value: 'Run: aws iot describe-endpoint --endpoint-type iot:Data-ATS',
    });
  }
}
