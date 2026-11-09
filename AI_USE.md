# AI Use

## What AI was used for
- Muse (Rocky, a Meta AI assistant) drafted code, prompts, Kubernetes
  manifests, this CI workflow, and the report structure, from the
  assignment brief and the kit files.
- Drafts included: the setup checker, SeaweedFS and worker manifests,
  `worker.py` / `clean.py`, training and evaluation scripts, the FastAPI
  service, Task 4 manifests, unit tests, and this workflow.

## What AI was not used for
- Teacher replies were generated only by Phi-3.5-mini-instruct (Ollama,
  temperature 0, seed 42) and stored exactly as generated; no teacher
  reply was edited by hand or by AI.
- Training used only the cleaned teacher replies (max 1,500 examples).
- No model output, count, or measured result in the report was written
  by AI without a measured source: every number comes from a log, a
  `score.py` report, `kubectl top`, or a Locust CSV in `results/`.

## How the work was verified
- Rishi ran every command on his own laptop and pasted the output back;
  failures were fixed from the exact pasted error, not from memory.
- `clean.py` was tested on synthetic shards before use; the unit tests
  in `tests/` (11 tests) run in CI.
- Two real failures found this way and fixed: a missing
  `k8s/pipeline/namespace.yaml`, and a teacher reply that rambled for
  1,784 tokens and returned a 500 from Ollama (fixed with
  `num_predict: 128`, stop sequences, and resume + incremental upload
  in the worker).
- The trained model was evaluated with `tools/score.py` on the 100
  validation commands, teacher / untrained / student, before deployment.

## Responsibility
- Rishi Raj (230103019) is responsible for the submitted work, the
  measurements, and the claims in the report. AI assistance is disclosed
  here, as the brief requires, and does not change authorship of the
  decisions.
