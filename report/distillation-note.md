# Task 2 — Distillation method (draft, under one page, for report/report.pdf)

## Sequence-level vs logit-based distillation

Knowledge distillation transfers a teacher's behaviour to a smaller
student. There are two standard ways to do it.

**Logit-based distillation** trains the student to match the teacher's
full output distribution at every step: for each token position, the
teacher's probability over the whole vocabulary (its logits, softened
by a temperature) becomes the student's target, usually with a
KL-divergence loss. The student therefore learns not only the teacher's
chosen token, but how confident it was, and which alternatives were
close. This is richer supervision per example than a single hard label.

**Sequence-level distillation** trains the student only on the
teacher's chosen output sequence: the teacher generates one complete
reply for each input, and the student is trained with ordinary
next-token cross-entropy to reproduce that reply, token by token.
The supervision is the hard sequence, not the distribution that
produced it. It is the standard method when the teacher is only
available as a black box.

This project uses sequence-level distillation. For each of the 3,000
commands in `commands_pool.jsonl`, the teacher (Phi-3.5-mini-instruct,
temperature 0, seed 42) generated one JSON reply, stored exactly as
generated. After cleaning, at most the first 1,500 cleaned examples
were used to fine-tune Pythia-70M, with the training format
`Command: <text> JSON: <teacher reply>`, cross-entropy loss on the
reply tokens only.

## Why logit-based distillation is impossible here

Logit-based distillation needs the teacher's logits, i.e. access to
the teacher model's output layer for every token position. In this
project the teacher is served by Ollama, and Ollama's `/api/generate`
endpoint returns only the generated text (plus token counts). It does
not expose logits, log-probabilities, or the model weights. There is
no supported Ollama call that returns a per-token distribution for
Phi-3.5, so the KL-divergence target that logit-based distillation
requires simply does not exist in this setup. The only supervision
available is the generated sequence, which is exactly what
sequence-level distillation uses.

## One real limitation

Sequence-level distillation can only teach what the teacher actually
generated. If the teacher's reply for a command is wrong — a wrong
intent, a slot copied from the wrong phrase, or a value the command
never mentioned — that wrong reply becomes a training example, and
the student learns to reproduce the error. Cleaning removes replies
that are invalid JSON, have wrong keys, a bad intent, or a slot value
not present in the command, but it cannot detect a reply that is
well-formed and plausible yet semantically wrong (for example, the
right intent with the wrong date phrase). The student therefore
inherits the teacher's silent errors, and its ceiling is the
teacher's accuracy on this task, not the accuracy of the original
labels.
