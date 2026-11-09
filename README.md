# CS3081 Cloud Computing Mini Project

Distil Phi-3.5-mini-instruct (teacher, Ollama, temperature 0, seed 42)
into EleutherAI/pythia-70m (student) for command parsing: one short
English command -> exactly one JSON object with exactly four keys
`intent`, `date`, `time`, `place`. Deployed on local k3d + SeaweedFS,
with Kubernetes, networking, CI, load testing and cost estimation.

## Prerequisites
- Docker, kubectl, k3d, Ollama with `phi3.5` pulled, Python 3.11 venv
  (see `check_setup.py` in the workspace, or run the checks in
  `scripts/`), `gh` for releases.
- Kit data in place: `data/commands_pool.jsonl` (3,000),
  `data/validation.jsonl` (100), `data/schema.json`, `data/rate_card.json`,
  `tools/score.py`, `tools/locustfile.py`, `tools/nacl_sim.py`.

## Build and deploy
```
git clone <repo> && cd <repo>
make up            # k3d cluster cs3081 + SeaweedFS + datasets/models buckets
./scripts/run_workers.sh   # two teacher workers, namespace pipeline
# when both jobs complete:
make clean         # worker/clean.py -> datasets/v1/train.jsonl + train.sha256
make train SUBSET=50   # smoke test, then:
make train         # v1, 3 epochs, max 1,500 examples
python scripts/evaluate.py teacher
python scripts/evaluate.py base
python scripts/evaluate.py student
```

## Test
```
make test          # 11 pytest unit tests (clean, sharding, schema)
# CI: lint -> tests -> evaluation (score.py --min-validity 95) -> gitleaks
```

## Deploy the service (Tasks 3-4)
```
docker build -t cs3081-parser:v1 service/
k3d image import cs3081-parser:v1 -c cs3081
kubectl apply -f k8s/app/
# Ingress: http://parse.local/parse  (add parse.local to /etc/hosts -> 127.0.0.1)
# v2: rebuild with MODEL_VERSION=v2, kubectl set image, or kubectl rollout undo
```

## Load test and cost (Task 7)
```
locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 \
  --run-time 2m --host http://localhost:8080 --csv results/loadtest
python scripts/cost.py --stats results/loadtest_stats.csv --replicas 2
```

## Teardown
```
make down          # deletes the k3d cluster cs3081 and everything in it
```

## Layout
- `cluster/k3d.yaml` — cluster definition
- `prompts/teacher_prompt.txt` — teacher prompt (temp 0, seed 42)
- `worker/` — teacher worker, `clean.py`, Dockerfile
- `k8s/seaweedfs/`, `k8s/pipeline/`, `k8s/app/` — manifests
- `training/` — config, train.py, loss.csv
- `service/` — FastAPI inference service (port 8000)
- `scripts/` — setup, workers, evaluation, cost
- `network/` — subnets.md, nacl.json
- `tests/` — unit tests
- `AI_USE.md` — AI assistance disclosure

## Submissions
- Trained model + tokenizer + checksums: GitHub Release assets, never
  committed to Git (see `.gitignore`).
- Report: `report/report.pdf` (max 8 pages). Reflection:
  `230103019.pdf` (max 3 pages, handwritten, scanned).
- Final commit tagged `final`.
