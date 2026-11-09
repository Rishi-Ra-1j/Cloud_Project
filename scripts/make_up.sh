#!/usr/bin/env bash
# make up: create the cluster and object storage from a fresh clone.
# One command: make up   (after: git clone <repo> && cd <repo>)
set -euo pipefail
cd "$(dirname "$0")/.."
if ! k3d cluster list | grep -q '^cs3081'; then
  k3d cluster create --config cluster/k3d.yaml
fi
bash scripts/setup_seaweedfs.sh
# s3_setup.py needs the S3 port-forward; run it in the background, then stop it.
kubectl -n data port-forward svc/seaweedfs 8333:8333 >/tmp/seaweedfs-pf.log 2>&1 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null || true' EXIT
sleep 3
set -a; source .s3-credentials; set +a
.venv/bin/python scripts/s3_setup.py
echo "make up done: cluster cs3081 + SeaweedFS + datasets/models buckets ready."
echo "Next: ./scripts/run_workers.sh"
