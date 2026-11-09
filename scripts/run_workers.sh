#!/usr/bin/env bash
# Task 1: build the worker image, import it into k3d, expose host Ollama
# to the cluster, and start two workers (shards 0 and 1) at the same time.
# Usage: ./scripts/run_workers.sh
# Prerequisites: cluster up, SeaweedFS up, .s3-credentials present,
# Ollama running on the host with phi3.5 pulled.
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. Ollama must listen on all interfaces, not just localhost, or the
#    pods cannot reach it via host.k3d.internal. Do this once.
if ! systemctl is-active --quiet ollama; then
  echo "Ollama service is not running. Start it first: sudo systemctl start ollama"
  exit 1
fi
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' | sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart ollama
sleep 3
curl -fsS http://localhost:11434/api/tags >/dev/null
echo "Ollama reachable on 0.0.0.0:11434"

# 2. Build + import the worker image into the k3d cluster.
docker build -t cs3081-teacher-worker:latest worker/
k3d image import cs3081-teacher-worker:latest -c cs3081

# 3. Namespace, S3 credentials (copied from .s3-credentials) and prompt.
kubectl apply -f k8s/pipeline/namespace.yaml
set -a; source .s3-credentials; set +a
kubectl -n pipeline create secret generic s3-credentials \
  --from-literal=access-key="$AWS_ACCESS_KEY_ID" \
  --from-literal=secret-key="$AWS_SECRET_ACCESS_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n pipeline create configmap teacher-prompt \
  --from-file=teacher_prompt.txt=prompts/teacher_prompt.txt \
  --dry-run=client -o yaml | kubectl apply -f -

# 4. Start both workers at the same time.
kubectl apply -f k8s/pipeline/worker-job-0.yaml -f k8s/pipeline/worker-job-1.yaml
kubectl -n pipeline get jobs
echo "Workers started. Follow with: kubectl -n pipeline logs -f job/teacher-worker-0"
echo "and in another terminal: kubectl -n pipeline logs -f job/teacher-worker-1"
