#!/usr/bin/env python3
"""Clean the teacher shard outputs (Task 1, step 6).

Reads all shard outputs from s3://datasets/teacher/shard-*.jsonl,
removes bad records, and writes the rest, in id order, to
s3://datasets/v1/train.jsonl, with its SHA-256 checksum in
s3://datasets/v1/train.sha256.

Removed, in this order (a record counts once, for the first reason
that applies):
  (a) replies that are not valid JSON
  (b) replies whose keys are not exactly intent, date, time, place
  (c) replies whose intent is not one of the eight
  (d) replies with a slot value that is neither null nor text that
      appears in the command
  duplicates: duplicate commands (same text), keep the smallest id.

Output format is the same as the shard outputs:
  {"id": "...", "text": "...", "teacher_raw": "<exact teacher reply>"}
so training can parse teacher_raw directly.

Usage (S3 mode, from the repo root):
  kubectl -n data port-forward svc/seaweedfs 8333:8333 &
  set -a; source .s3-credentials; set +a
  .venv/bin/python worker/clean.py

Local test mode (no S3): --local-shards DIR --local-out DIR
  reads DIR/shard-*.jsonl and writes DIR/../out/train.jsonl + train.sha256.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# boto3 is imported lazily inside main() (S3 mode only), so --local-shards
# mode works without boto3 installed.

KEYS = {"intent", "date", "time", "place"}
INTENTS = {
    "alarm_set", "alarm_query", "calendar_set", "calendar_query",
    "calendar_remove", "weather_query", "datetime_query", "recommendation_events",
}


def clean_records(records):
    """Return (kept, counts). records are shard-output dicts, any order."""
    counts = {"input": 0, "a": 0, "b": 0, "c": 0, "d": 0, "duplicates": 0, "kept": 0}
    kept = []
    seen_texts = set()
    for rec in sorted(records, key=lambda r: r.get("id", "")):
        counts["input"] += 1
        raw = rec.get("teacher_raw", "")
        try:
            obj = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            counts["a"] += 1
            continue
        if not isinstance(obj, dict) or set(obj.keys()) != KEYS:
            counts["b"] += 1
            continue
        if obj["intent"] not in INTENTS:
            counts["c"] += 1
            continue
        bad_slot = False
        for slot in ("date", "time", "place"):
            v = obj[slot]
            if v is None:
                continue
            if not isinstance(v, str) or v.lower() not in rec["text"].lower():
                bad_slot = True
                break
        if bad_slot:
            counts["d"] += 1
            continue
        if rec["text"] in seen_texts:
            counts["duplicates"] += 1
            continue
        seen_texts.add(rec["text"])
        kept.append({"id": rec["id"], "text": rec["text"], "teacher_raw": raw})
    counts["kept"] = len(kept)
    assert counts["input"] == counts["a"] + counts["b"] + counts["c"] + counts["d"] + counts["duplicates"] + counts["kept"]
    return kept, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-shards", help="read shard-*.jsonl from this dir instead of S3")
    ap.add_argument("--local-out", help="write train.jsonl + train.sha256 to this dir instead of S3")
    a = ap.parse_args()

    if a.local_shards:
        records = []
        for path in sorted(Path(a.local_shards).glob("shard-*.jsonl")):
            records += [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        kept, counts = clean_records(records)
        out = Path(a.local_out)
        out.mkdir(parents=True, exist_ok=True)
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept).encode("utf-8")
        (out / "train.jsonl").write_bytes(body)
        (out / "train.sha256").write_text(hashlib.sha256(body).hexdigest() + "  train.jsonl\n")
    else:
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT", "http://localhost:8333"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "admin"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
            region_name="us-east-1",
        )
        records = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket="datasets", Prefix="teacher/"):
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith(".jsonl"):
                    continue
                body = s3.get_object(Bucket="datasets", Key=obj["Key"])["Body"].read().decode("utf-8")
                records += [json.loads(line) for line in body.splitlines() if line.strip()]
        kept, counts = clean_records(records)
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept).encode("utf-8")
        s3.put_object(Bucket="datasets", Key="v1/train.jsonl", Body=body)
        digest = hashlib.sha256(body).hexdigest()
        s3.put_object(Bucket="datasets", Key="v1/train.sha256", Body=(digest + "  train.jsonl\n").encode("utf-8"))
        print(f"wrote s3://datasets/v1/train.jsonl ({len(kept)} records), sha256 {digest}")

    print("Counts:")
    for k in ("input", "a", "b", "c", "d", "duplicates", "kept"):
        print(f"  {k}: {counts[k]}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
