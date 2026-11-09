#!/usr/bin/env bash
# Task 1: deploy SeaweedFS in namespace `data`.
# Usage: ./scripts/setup_seaweedfs.sh
# Creates the namespace and the S3 credentials Secret (random secret,
# never committed to Git), then applies the manifests and waits for Ready.
# Prints the credentials to a local file .s3-credentials (gitignored) -
# keep that file on the laptop only.
set -euo pipefail
cd "$(dirname "$0")/.."

kubectl apply -f k8s/seaweedfs/namespace.yaml

if kubectl -n data get secret seaweedfs-s3-config >/dev/null 2>&1; then
  echo "Secret seaweedfs-s3-config already exists, reusing it."
else
  S3_SECRET_KEY="$(openssl rand -hex 16)"
  kubectl -n data create secret generic seaweedfs-s3-config \
    --from-literal=s3.json="{\"identities\": [{\"name\": \"admin\", \"credentials\": [{\"accessKey\": \"admin\", \"secretKey\": \"$S3_SECRET_KEY\"}], \"actions\": [\"Admin\", \"Read\", \"Write\"]}]}"
  printf 'AWS_ACCESS_KEY_ID=admin\nAWS_SECRET_ACCESS_KEY=%s\nS3_ENDPOINT=http://localhost:8333\n' "$S3_SECRET_KEY" > .s3-credentials
  chmod 600 .s3-credentials
  echo "Created secret. Credentials saved to .s3-credentials (do NOT commit it)."
fi

kubectl apply -f k8s/seaweedfs/service.yaml -f k8s/seaweedfs/statefulset.yaml
kubectl -n data rollout status statefulset/seaweedfs --timeout=300s
kubectl -n data get pods -o wide
