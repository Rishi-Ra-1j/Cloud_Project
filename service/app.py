#!/usr/bin/env python3
"""Command-parser inference service (Task 3).

FastAPI, port 8000.
  POST /parse   {"text": "<command>"} -> the 4-key JSON only, plus headers
                 X-Model-Version and X-Served-By
  GET  /healthz 200 always (process is up)
  GET  /readyz  503 until the model is loaded, then 200

Env:
  MODEL_URI       e.g. s3://models/v1   (bucket + key prefix in object storage)
  MODEL_VERSION   e.g. v1
  S3_ENDPOINT     e.g. http://seaweedfs.data.svc.cluster.local:8333
  MAX_NEW_TOKENS  e.g. 128
  FAULT_INJECT    "1" -> respond 500 {"error": "invalid_model_output"}
S3 credentials come only from the environment (in Kubernetes, from a
Secret mounted as env vars); they are never in the image or the code.

At startup the model + tokenizer are downloaded from object storage
into a local directory, then loaded once with transformers (CPU).
Generation is greedy, same prompt format as training:
  Command: <text> JSON:
Output is validated against schema.json (the kit's json_schema, plus
exactly these four keys, no extras). Invalid output -> HTTP 500
{"error": "invalid_model_output"}, never a made-up JSON.
"""
import json
import os
import sys
from pathlib import Path

import torch
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_URI = os.environ["MODEL_URI"]          # s3://models/v1
MODEL_VERSION = os.environ.get("MODEL_VERSION", "v1")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://seaweedfs.data.svc.cluster.local:8333")
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "128"))
FAULT_INJECT = os.environ.get("FAULT_INJECT", "0") == "1"
MODEL_DIR = Path("/tmp/model")

with open(Path(__file__).parent / "schema.json", encoding="utf-8") as f:
    SCHEMA = json.load(f)
INTENTS = set(SCHEMA["intents"])
KEYS = SCHEMA["keys"]

app = FastAPI()
model = None
tokenizer = None


def download_model():
    """Download every object under MODEL_URI into MODEL_DIR."""
    import boto3

    if not MODEL_URI.startswith("s3://"):
        raise ValueError(f"MODEL_URI must be s3://bucket/prefix, got {MODEL_URI}")
    # MODEL_URI is s3://<bucket>/<prefix>, e.g. s3://models/v1.
    # BUG (found 2026-11-09, pods CrashLoopBackOff with NoSuchBucket):
    # the old code split off the bucket and then split the prefix
    # again, so bucket became "v1" instead of "models".
    parts = MODEL_URI[5:].split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ''
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "admin"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        region_name="us-east-1",
    )
    paginator = s3.get_paginator("list_objects_v2")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(prefix):].lstrip("/")
            if not rel:
                continue
            dest = MODEL_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            print(f"downloading s3://{bucket}/{obj['Key']} -> {dest}", flush=True)
            s3.download_file(bucket, obj["Key"], str(dest))
            count += 1
    if count == 0:
        raise RuntimeError(f"no model files found at {MODEL_URI}")
    print(f"downloaded {count} model files", flush=True)


@app.on_event("startup")
def load_model():
    global model, tokenizer
    download_model()
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(str(MODEL_DIR), dtype=torch.float32)  # pythia is fp16 on disk; fp32 for CPU
    model.eval()
    print(f"model {MODEL_VERSION} loaded from {MODEL_URI}", flush=True)


def extract_json(text):
    """Return the first balanced {...} object in text, or text stripped."""
    s = text.find("{")
    if s < 0:
        return text.strip()
    depth = 0
    for i in range(s, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[s:i + 1]
    return text[s:]


def validate(obj):
    """True only if obj is exactly the 4-key JSON with a valid intent."""
    if not isinstance(obj, dict) or set(obj.keys()) != set(KEYS):
        return False
    if obj["intent"] not in INTENTS:
        return False
    return all(v is None or isinstance(v, str) for k, v in obj.items() if k != "intent")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    if model is None:
        return JSONResponse({"status": "not ready"}, status_code=503)
    return {"status": "ready"}


@app.post("/parse")
def parse(request: Request, body: dict):
    text = body.get("text", "")
    if FAULT_INJECT:
        raw = "not json at all"
    else:
        prompt = f"Command: {text} JSON:"  # no trailing space: must match training tokenization
        inputs = tokenizer(prompt, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
            )
        raw = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    # The model sometimes emits a short prefix before the JSON
    # (v1 did this on most rows), and keeps generating after it.
    # Extract ONLY the first balanced JSON object: first '{' to
    # its matching '}'. Anything outside it is discarded.
    # First line only, then the first balanced JSON in that line.
    first = raw.strip().splitlines()[0] if raw.strip() else ""
    line = extract_json(first)
    try:
        obj = json.loads(line)
    except Exception:
        return JSONResponse({"error": "invalid_model_output"}, status_code=500)
    if not validate(obj):
        return JSONResponse({"error": "invalid_model_output"}, status_code=500)
    headers = {
        "X-Model-Version": MODEL_VERSION,
        "X-Served-By": os.environ.get("HOSTNAME", "unknown"),
    }
    return JSONResponse(obj, headers=headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
