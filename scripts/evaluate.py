#!/usr/bin/env python3
"""Evaluate a model on validation.jsonl and score it (Task 2, step 6).

Modes:
  teacher    Phi-3.5 via Ollama, same prompt and settings as Task 1
             (temperature 0, seed 42, num_predict 128)
  base       untrained EleutherAI/pythia-70m, local Hugging Face generate
  student    trained model in models/<version>/ (default v1)

Usage (from the repo root, venv active):
  .venv/bin/python scripts/evaluate.py teacher
  .venv/bin/python scripts/evaluate.py base
  .venv/bin/python scripts/evaluate.py student --model models/v1

Writes:
  results/<mode>_predictions.jsonl   {"id": ..., "prediction": "<raw text>"}
  results/<mode>_validation.json     score.py report (also printed)
Teacher output is saved as results/teacher_validation.json, as required.

The student/base prompt is the training format:
  Command: <text> JSON:
and generation is greedy, max 128 new tokens. The raw generated text
after the prompt is the prediction; score.py parses it as JSON.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import requests


def load_validation():
    return [json.loads(line) for line in open("data/validation.jsonl", encoding="utf-8") if line.strip()]


def score_predictions(mode, predictions_path):
    out = Path(f"results/{mode}_validation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [sys.executable, "tools/score.py", str(predictions_path), "data/validation.jsonl", "--out", str(out)],
        capture_output=True, text=True, check=False,
    )
    print(r.stdout, end="")
    if r.stderr:
        print(r.stderr, file=sys.stderr)
    if r.returncode != 0:
        raise SystemExit(f"score.py failed for {mode}")
    return out


def save_and_score(mode, rows):
    Path("results").mkdir(exist_ok=True)
    path = Path(f"results/{mode}_predictions.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {path} ({len(rows)} predictions)")
    return score_predictions(mode, path)


def evaluate_teacher():
    prompt = Path("prompts/teacher_prompt.txt").read_text(encoding="utf-8").strip()
    rows = []
    for i, rec in enumerate(load_validation(), 1):
        payload = {
            "model": "phi3.5",
            "prompt": prompt + "\nCommand: " + rec["text"] + "\n",
            "stream": False,
            "options": {"temperature": 0, "seed": 42, "num_predict": 128},
            "stop": ["\nCommand:", "\n\n", "```"],
        }
        r = requests.post("http://localhost:11434/api/generate", json=payload, timeout=120)
        r.raise_for_status()
        rows.append({"id": rec["id"], "prediction": r.json()["response"]})
        if i % 25 == 0:
            print(f"teacher: {i}/100 done", flush=True)
    return save_and_score("teacher", rows)


def evaluate_hf(mode, model_path):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_path, dtype=torch.float32)  # pythia is fp16 on disk; fp32 for CPU
    model.eval()
    rows = []
    for i, rec in enumerate(load_validation(), 1):
        prompt = f"Command: {rec['text']} JSON:"  # no trailing space: must match training tokenization
        inputs = tokenizer(prompt, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=128, do_sample=False, pad_token_id=tokenizer.pad_token_id)
        gen = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        # The model sometimes emits a short prefix before the JSON
        # (v1 did this on most rows, which made score.py report 0%).
        # Extract the JSON object itself: first '{' to last '}'.
        s, e = gen.find("{"), gen.rfind("}")
        pred = gen[s:e + 1] if s >= 0 and e > s else gen.strip()
        rows.append({"id": rec["id"], "prediction": pred})
        if i % 25 == 0:
            print(f"{mode}: {i}/100 done", flush=True)
    return save_and_score(mode, rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["teacher", "base", "student"])
    ap.add_argument("--model", default="models/v1", help="model path for student mode")
    a = ap.parse_args()
    if a.mode == "teacher":
        evaluate_teacher()
    elif a.mode == "base":
        evaluate_hf("base", "EleutherAI/pythia-70m")
    else:
        evaluate_hf("student", a.model)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
