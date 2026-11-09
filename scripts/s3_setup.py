#!/usr/bin/env python3
"""Create buckets `datasets` and `models` in SeaweedFS S3 and upload
data/commands_pool.jsonl to datasets/commands_pool.jsonl.

Usage (from the repo root, with the venv active, and a port-forward running):
  kubectl -n data port-forward svc/seaweedfs 8333:8333 &
  set -a; source .s3-credentials; set +a   # or export the three vars by hand
  .venv/bin/python scripts/s3_setup.py

Env: S3_ENDPOINT (default http://localhost:8333),
     AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY.
Only boto3 (already in the venv) is used.
"""
import os
import sys

import boto3
from botocore.exceptions import ClientError

ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:8333")
s3 = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "admin"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
    region_name="us-east-1",
)


def ensure_bucket(name):
    try:
        s3.create_bucket(Bucket=name)
        print(f"created bucket {name}")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f"bucket {name} already exists")
        else:
            raise


def main():
    for bucket in ("datasets", "models"):
        ensure_bucket(bucket)
    s3.upload_file("data/commands_pool.jsonl", "datasets", "commands_pool.jsonl")
    print("uploaded data/commands_pool.jsonl -> s3://datasets/commands_pool.jsonl")
    for bucket in ("datasets", "models"):
        objs = s3.list_objects_v2(Bucket=bucket).get("Contents", [])
        print(f"s3://{bucket}/: " + ", ".join(f"{o['Key']} ({o['Size']} bytes)" for o in objs) or "(empty)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Is the port-forward running? kubectl -n data port-forward svc/seaweedfs 8333:8333", file=sys.stderr)
        raise SystemExit(1)
