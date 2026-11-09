#!/usr/bin/env python3
"""Teacher labelling worker (Task 1).

Reads SHARD_INDEX and SHARD_COUNT from the environment. It takes the
commands whose line number (counting from 0) leaves remainder
SHARD_INDEX when divided by SHARD_COUNT, sends each one to the teacher
(Phi-3.5 via Ollama, temperature 0, seed 42) with prompts/teacher_prompt.txt,
and writes one line per command:
  {"id": "...", "text": "...", "teacher_raw": "<the teacher's exact reply>"}
to its own object datasets/teacher/shard-<SHARD_INDEX>.jsonl in SeaweedFS S3.

Env:
  SHARD_INDEX, SHARD_COUNT (required)
  S3_ENDPOINT (default http://seaweedfs.data.svc.cluster.local:8333)
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
  OLLAMA_URL (default http://host.k3d.internal:11434)
    The teacher runs on the laptop host, not in the cluster, so Ollama
    must listen on 0.0.0.0 (see scripts/run_workers.sh). host.k3d.internal
    is injected by k3d and resolves to the host.
  TEACHER_PROMPT_PATH (default /prompts/teacher_prompt.txt)
  MODEL (default phi3.5)
"""
import json
import os
import sys
import time

# boto3 / requests are imported lazily inside main()/call_teacher(), so the
# pure sharding logic can be tested without them installed.

SHARD_INDEX = int(os.environ["SHARD_INDEX"])
SHARD_COUNT = int(os.environ["SHARD_COUNT"])
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://seaweedfs.data.svc.cluster.local:8333")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.k3d.internal:11434")
PROMPT_PATH = os.environ.get("TEACHER_PROMPT_PATH", "/prompts/teacher_prompt.txt")
MODEL = os.environ.get("MODEL", "phi3.5")


def shard_commands(commands):
    """Return the commands for this shard, in file order."""
    return [c for i, c in enumerate(commands) if i % SHARD_COUNT == SHARD_INDEX]


def call_teacher(prompt, command, retries=5):
    import requests

    payload = {
        "model": MODEL,
        "prompt": prompt + "\nCommand: " + command + "\n",
        "stream": False,
        # temperature 0 and seed 42 are the fixed settings from the brief.
        # num_predict caps the reply at 128 tokens: a correct reply is one
        # short JSON object (~30 tokens). Without a cap, Phi-3.5 sometimes
        # rambles for 1,700+ tokens (seen in the Ollama log, 2m20s, then a
        # 500), blocking Ollama's single slot and failing the other worker.
        # stop cuts it off if it tries to start a second command.
        "options": {"temperature": 0, "seed": 42, "num_predict": 128},
        "stop": ["\nCommand:", "\n\n", "```"],
    }
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
            r.raise_for_status()
            return r.json()["response"]
        except Exception as e:  # noqa: BLE001 - retry, then fail loudly
            last = e
            print(f"  retry {attempt + 1}/{retries} after {e}", flush=True)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"teacher call failed after {retries} attempts: {last}")


def main():
    if not 0 <= SHARD_INDEX < SHARD_COUNT:
        raise SystemExit(f"SHARD_INDEX {SHARD_INDEX} out of range for SHARD_COUNT {SHARD_COUNT}")
    with open(PROMPT_PATH, encoding="utf-8") as f:
        prompt = f.read().strip()

    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "admin"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        region_name="us-east-1",
    )
    obj = s3.get_object(Bucket="datasets", Key="commands_pool.jsonl")
    commands = [json.loads(line) for line in obj["Body"].read().decode("utf-8").splitlines() if line.strip()]
    mine = shard_commands(commands)
    print(f"shard {SHARD_INDEX}/{SHARD_COUNT}: {len(mine)} of {len(commands)} commands", flush=True)

    out_key = f"teacher/shard-{SHARD_INDEX}.jsonl"
    # Resume: if a previous run already wrote part of this shard, keep
    # those records and skip them, so a pod restart does not lose work.
    lines = []
    done_ids = set()
    try:
        existing = s3.get_object(Bucket="datasets", Key=out_key)["Body"].read().decode("utf-8")
        for line in existing.splitlines():
            if line.strip():
                lines.append(line)
                done_ids.add(json.loads(line)["id"])
        print(f"shard {SHARD_INDEX}: resuming, {len(lines)} records already done", flush=True)
    except Exception:
        print(f"shard {SHARD_INDEX}: starting fresh", flush=True)

    def upload():
        s3.put_object(Bucket="datasets", Key=out_key, Body=("\n".join(lines) + "\n").encode("utf-8"))

    for n, cmd in enumerate(mine, 1):
        if cmd["id"] in done_ids:
            continue
        raw = call_teacher(prompt, cmd["text"])
        # Store the teacher's reply exactly as generated. Do not edit it.
        lines.append(json.dumps({"id": cmd["id"], "text": cmd["text"], "teacher_raw": raw}, ensure_ascii=False))
        done = len(lines)
        if done % 50 == 0 or done == len(mine):
            upload()
            print(f"shard {SHARD_INDEX}: {done}/{len(mine)} done (saved to S3)", flush=True)

    upload()
    print(f"wrote s3://datasets/{out_key} ({len(lines)} records)", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
