#!/bin/bash
set -e

echo "=================================================="
echo "Initializing LocalStack AWS Cloud Resources..."
echo "=================================================="

AWS_REGION="us-east-1"
LOCALSTACK_URL="http://localhost:4566"

export AWS_ACCESS_KEY_ID="test"
export AWS_SECRET_ACCESS_KEY="test"
export AWS_DEFAULT_REGION="${AWS_REGION}"

# 1. Create S3 Bucket for Payload Staging
echo "[1/4] Provisioning AWS S3 Staging Bucket..."
awslocal --endpoint-url="${LOCALSTACK_URL}" s3 mb s3://cloud-orchestrator-payload-staging || true
awslocal --endpoint-url="${LOCALSTACK_URL}" s3 mb s3://cloud-orchestrator-payload-staging-dev || true

# 2. Create DynamoDB State & Audit Ledger Table
echo "[2/4] Provisioning DynamoDB State Ledger Table..."
awslocal --endpoint-url="${LOCALSTACK_URL}" dynamodb create-table \
    --table-name Orchestrator_Workflow_Ledger \
    --attribute-definitions AttributeName=job_id,AttributeType=S \
    --key-schema AttributeName=job_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST || true

# 3. Create Default Migration Target DynamoDB Table
echo "[3/4] Provisioning DynamoDB Target Production Table..."
awslocal --endpoint-url="${LOCALSTACK_URL}" dynamodb create-table \
    --table-name Migrated_Production_Records \
    --attribute-definitions AttributeName=record_id,AttributeType=S \
    --key-schema AttributeName=record_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST || true

awslocal --endpoint-url="${LOCALSTACK_URL}" dynamodb create-table \
    --table-name Users_V2 \
    --attribute-definitions AttributeName=user_id,AttributeType=S \
    --key-schema AttributeName=user_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST || true

# 4. Create CloudWatch Log Group
echo "[4/4] Provisioning CloudWatch Log Groups..."
awslocal --endpoint-url="${LOCALSTACK_URL}" logs create-log-group \
    --log-group-name /aws/orchestrator/workflows || true

echo "=================================================="
echo "LocalStack AWS Cloud Resources Initialized Successfully!"
echo "=================================================="
