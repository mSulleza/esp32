#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { AcBackendStack } from '../lib/ac-backend-stack';

const app = new cdk.App();
new AcBackendStack(app, 'AcControllerBackend', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? 'ap-southeast-1',
  },
  description: 'ESP32 Smart AC Controller backend: IoT Core + Lambda + DynamoDB',
});
