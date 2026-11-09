#!/usr/bin/env python3
"""Train the student (Task 2, sequence-level distillation).

Each training example is built exactly as the brief requires:
  Command: <the command> JSON: <the teacher's JSON reply>
The model learns to produce the teacher's reply, given the command.
That is sequence-level distillation: the teacher's output is the target.
No teacher logits are used.

Usage:
  make train                 # 1,500 records, config.yaml, output models/v1/
  make train SUBSET=50       # first 50 records only (verification run)
  .venv/bin/python training/train.py --version v2 --epochs 4 --seed 43

Reads train.jsonl from S3 (datasets/v1/train.jsonl, via a port-forward to
SeaweedFS) or, if S3 is not reachable, from a local data/train.jsonl.
Saves the model + tokenizer locally to models/<version>/ and, when S3 is
reachable, uploads them to s3://models/<version>/ plus a per-file SHA-256
list at s3://models/<version>/model.sha256. Writes one loss value per
epoch to training/loss.csv (training/loss-<version>.csv for v2).
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

import yaml

# torch / transformers are imported lazily in main() so --help works
# without them and so import errors are reported clearly.


def make_collator(tokenizer):
    """Pad a batch to the longest example in the batch.

    The built-in DataCollatorForLanguageModeling failed on this
    transformers version with "Unable to create tensor ... labels have
    excessive nesting", because the tokenised examples have different
    lengths and were never padded. This collator pads input_ids with
    the pad token, attention_mask with 0, and labels with -100 (so
    padding is ignored by the loss), and returns real tensors.
    """
    import torch

    pad_id = tokenizer.pad_token_id

    def collate(batch):
        maxlen = max(len(x["input_ids"]) for x in batch)
        input_ids, attention_mask, labels = [], [], []
        for x in batch:
            ids = list(x["input_ids"])
            pad = maxlen - len(ids)
            input_ids.append(ids + [pad_id] * pad)
            attention_mask.append(list(x.get("attention_mask", [1] * len(ids))) + [0] * pad)
            labels.append(list(x["labels"]) + [-100] * pad)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }

    return collate


def load_train_records(subset, max_examples):
    """Return the first `subset or max_examples` records from train.jsonl."""
    local = Path("data/train.jsonl")
    if local.exists():
        lines = local.read_text(encoding="utf-8").splitlines()
        print(f"reading train.jsonl from local {local}")
    else:
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT", "http://localhost:8333"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "admin"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
            region_name="us-east-1",
        )
        print("downloading s3://datasets/v1/train.jsonl")
        body = s3.get_object(Bucket="datasets", Key="v1/train.jsonl")["Body"].read().decode("utf-8")
        lines = body.splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    n = subset or max_examples
    print(f"train.jsonl has {len(records)} records, using first {min(n, len(records))}")
    return records[:n]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="training/config.yaml")
    ap.add_argument("--subset", type=int, default=None, help="train on the first N records only")
    ap.add_argument("--version", default=None, help="model version, e.g. v1 or v2")
    ap.add_argument("--epochs", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()

    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    seed = a.seed if a.seed is not None else cfg["seed"]
    epochs = a.epochs if a.epochs is not None else cfg["num_train_epochs"]
    version = a.version or cfg["output_version"]
    max_len = cfg["max_seq_length"]

    import torch
    from datasets import Dataset
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    torch.manual_seed(seed)
    records = load_train_records(a.subset, cfg["max_train_examples"])

    tokenizer = AutoTokenizer.from_pretrained(cfg["base_model"])
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(cfg["base_model"], dtype=torch.float32)
    # Pythia-70M is stored in float16 (166 MB file). Loading it as-is
    # trains in fp16 on CPU: fp16 has no GradScaler here, so gradients
    # overflow to NaN, and CPU fp16 math is very slow (64 s/step in the
    # smoke test). float32 is the correct dtype for CPU training.
    print(f"model dtype: {next(model.parameters()).dtype}", flush=True)
    model.config.pad_token_id = tokenizer.pad_token_id

    def build_text(rec):
        # teacher_raw is the teacher's exact JSON reply string.
        return f"Command: {rec['text']} JSON: {rec['teacher_raw']}"

    texts = [build_text(r) for r in records]
    prompts = [f"Command: {r['text']} JSON: " for r in records]

    def tokenize(batch):
        # v2: train ONLY on the JSON reply, not on the prompt.
        # v1 trained on the whole "Command: ... JSON: ..." sequence, so
        # at inference the model sometimes generated a command-like
        # prefix before the JSON. Masking the prompt (labels -100) and
        # appending EOS teaches it: after "JSON: " emit JSON, then stop.
        enc = tokenizer(batch["text"], truncation=True, max_length=max_len)
        prompt_enc = tokenizer(batch["prompt"], truncation=True, max_length=max_len)
        input_ids, attention_mask, labels = [], [], []
        for ids, pids, mask in zip(enc["input_ids"], prompt_enc["input_ids"], enc["attention_mask"]):
            n = min(len(pids), len(ids))
            lab = [-100] * n + list(ids[n:])
            input_ids.append(list(ids) + [tokenizer.eos_token_id])
            attention_mask.append(list(mask) + [1])
            labels.append(lab + [tokenizer.eos_token_id])
        return {"input_ids": input_ids, "attention_mask": attention_mask, "labels": labels}

    ds = Dataset.from_dict({"text": texts, "prompt": prompts}).map(
        tokenize, batched=True, remove_columns=["text", "prompt"]
    )
    collator = make_collator(tokenizer)

    args = TrainingArguments(
        output_dir=f"training/output-{version}",
        per_device_train_batch_size=cfg["batch_size"],
        gradient_accumulation_steps=cfg["gradient_accumulation_steps"],
        num_train_epochs=epochs,
        learning_rate=cfg["learning_rate"],
        seed=seed,
        logging_steps=10,
        save_strategy="no",
        report_to=[],
        dataloader_num_workers=0,
    )
    trainer = Trainer(model=model, args=args, train_dataset=ds, data_collator=collator)
    trainer.train()

    # One loss value per epoch, from the trainer's log history.
    by_epoch = {}
    for entry in trainer.state.log_history:
        if "loss" in entry and "epoch" in entry:
            by_epoch.setdefault(int(entry["epoch"]) + 1, []).append(entry["loss"])
    loss_path = Path(f"training/loss-{version}.csv") if version != "v1" else Path("training/loss.csv")
    with open(loss_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "loss"])
        for epoch in sorted(by_epoch):
            w.writerow([epoch, round(sum(by_epoch[epoch]) / len(by_epoch[epoch]), 6)])
    print(f"wrote {loss_path}")

    out_dir = Path(f"models/{version}")
    out_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(out_dir)
    tokenizer.save_pretrained(out_dir)
    print(f"saved model + tokenizer to {out_dir}")

    # SHA-256 per file, like sha256sum output.
    sha_path = out_dir / "model.sha256"
    with open(sha_path, "w", encoding="utf-8") as f:
        for path in sorted(p for p in out_dir.iterdir() if p.is_file() and p.name != "model.sha256"):
            f.write(f"{sha256_file(path)}  {path.name}\n")
    print(f"wrote {sha_path}")

    # Upload to object storage when it is reachable; otherwise the local
    # models/<version>/ copy is the artefact (upload it with the Release).
    try:
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT", "http://localhost:8333"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "admin"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
            region_name="us-east-1",
        )
        for path in sorted(out_dir.iterdir()):
            if path.is_file():
                s3.upload_file(str(path), "models", f"{version}/{path.name}")
                print(f"uploaded s3://models/{version}/{path.name}")
    except Exception as e:  # noqa: BLE001 - S3 may not be port-forwarded
        print(f"S3 upload skipped ({e}); local models/{version}/ is the artefact.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
