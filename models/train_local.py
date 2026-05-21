#!/usr/bin/env python3
"""Lusaber · Լուսաբեր — local Phase-3 training (CPU / Apple MPS).

End-to-end fine-tune of ``xlm-roberta-base`` on
``data/armenian_news_labeled.csv``, designed for an overnight run on
an Apple Silicon Mac (M2 Pro etc.). No Google Colab imports, no GPU
assumptions — falls back to CPU when MPS is unavailable.

Outputs::

    models/checkpoints/xlmr-lusaber-best/       (HF model + tokenizer)
    models/checkpoints/training_metrics.json    (full eval dump)

Usage::

    venv/bin/python models/train_local.py

The Trainer's per-epoch progress is supplemented by an
``EpochTimerCallback`` that prints an ETA based on the duration of
the first epoch.
"""

from __future__ import annotations

# --- MPS safety net (must precede any torch import) ---------------------
# The MPS allocator's "high watermark ratio" is the soft cap above which
# new allocations get refused with the OOM message we hit on bs=4 +
# xlm-roberta-base. Setting it to 0.0 tells the allocator to never gate
# growth — combined with bs=1 + accum=32 + CPU-forced TrainingArguments
# this run no longer touches MPS, but we leave the env var in place as a
# defensive measure for anyone re-enabling MPS later.
import os

os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"
# ------------------------------------------------------------------------

import json
import logging
import random
import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from datasets import Dataset
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from tqdm import tqdm
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainerCallback,
    TrainingArguments,
)

# ---------------------------------------------------------------------------
# Logging + reproducibility
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lusaber.train_local")

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(SEED)

# ---------------------------------------------------------------------------
# Paths + constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_CSV = REPO_ROOT / "data" / "armenian_news_labeled.csv"
CHECKPOINT_DIR = REPO_ROOT / "models" / "checkpoints" / "xlmr-lusaber"
BEST_DIR = REPO_ROOT / "models" / "checkpoints" / "xlmr-lusaber-best"
METRICS_PATH = REPO_ROOT / "models" / "checkpoints" / "training_metrics.json"

BASE_MODEL = "xlm-roberta-base"
MAX_LEN = 512
NUM_EPOCHS = 3
PER_DEVICE_TRAIN_BS = 1   # was 4 — dropped to 1 after MPS OOM at bs=4
GRAD_ACCUM = 32           # was 8 — bumped so effective batch stays 32
LEARNING_RATE = 2e-5
WARMUP_RATIO = 0.1
WEIGHT_DECAY = 0.01
LR_SCHEDULER = "cosine"
LOGGING_STEPS = 25
SAVE_TOTAL_LIMIT = 2

ID2LABEL = {0: "disinformation", 1: "credible"}
LABEL2ID = {v: k for k, v in ID2LABEL.items()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def format_input(title: str, body: str) -> str:
    """Spec format: ``title + ' [SEP] ' + body_text[:1000]``."""
    title = (title or "").strip()
    body = (body or "").strip()[:1000]
    return f"{title} [SEP] {body}" if title else body


def to_hf_dataset(part_df: pd.DataFrame) -> Dataset:
    return Dataset.from_dict(
        {
            "text": [
                format_input(t, b)
                for t, b in zip(part_df["title"], part_df["body_text"])
            ],
            "label": part_df["label"].tolist(),
        }
    )


def compute_metrics(eval_pred) -> dict[str, float]:
    """Returns accuracy, macro F1, macro precision, macro recall, ROC-AUC."""
    logits, labels = eval_pred
    probs = torch.softmax(torch.tensor(logits), dim=-1).numpy()
    preds = probs.argmax(axis=-1)
    return {
        "accuracy": float(accuracy_score(labels, preds)),
        "f1": float(f1_score(labels, preds, average="macro")),
        "precision": float(precision_score(labels, preds, average="macro", zero_division=0)),
        "recall": float(recall_score(labels, preds, average="macro", zero_division=0)),
        "roc_auc": float(roc_auc_score(labels, probs[:, 1])),
    }


class EpochTimerCallback(TrainerCallback):
    """Records per-epoch wall time and prints a projected ETA after epoch 1.

    The first epoch on CPU/MPS is by far the most expensive operation
    in this run; everything later — total time, when to come back —
    can be projected from it.
    """

    def __init__(self, total_epochs: int) -> None:
        self.total_epochs = total_epochs
        self.epoch_starts: list[float] = []
        self.epoch_ends: list[float] = []
        self._run_start = time.monotonic()

    def on_epoch_begin(self, args, state, control, **kwargs):  # noqa: D401
        self.epoch_starts.append(time.monotonic())
        idx = len(self.epoch_starts)
        log.info(">>> epoch %d/%d started", idx, self.total_epochs)

    def on_epoch_end(self, args, state, control, **kwargs):  # noqa: D401
        end = time.monotonic()
        self.epoch_ends.append(end)
        idx = len(self.epoch_ends)
        last = end - self.epoch_starts[-1]
        log.info("<<< epoch %d/%d finished in %s", idx, self.total_epochs,
                 timedelta(seconds=int(last)))
        if idx == 1 and self.total_epochs > 1:
            est_total = last * self.total_epochs
            est_left = last * (self.total_epochs - 1)
            log.info(
                "ETA: each epoch ≈ %s · total ≈ %s · remaining ≈ %s",
                timedelta(seconds=int(last)),
                timedelta(seconds=int(est_total)),
                timedelta(seconds=int(est_left)),
            )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def load_and_split() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load the labeled CSV and produce a stratified 80/10/10 split."""
    if not DATA_CSV.exists():
        log.error("dataset not found: %s", DATA_CSV)
        sys.exit(1)
    df = pd.read_csv(DATA_CSV)
    df["label"] = df["label"].astype(int)
    df["title"] = df["title"].fillna("")
    df["body_text"] = df["body_text"].fillna("")
    df["url"] = df["url"].fillna("")
    log.info("loaded %d rows from %s", len(df), DATA_CSV)
    log.info("class distribution: %s", df["label"].value_counts().to_dict())

    train_df, temp_df = train_test_split(
        df, test_size=0.20, random_state=SEED, stratify=df["label"]
    )
    val_df, test_df = train_test_split(
        temp_df, test_size=0.50, random_state=SEED, stratify=temp_df["label"]
    )
    train_df = train_df.reset_index(drop=True)
    val_df = val_df.reset_index(drop=True)
    test_df = test_df.reset_index(drop=True)
    log.info(
        "split sizes — train=%d  val=%d  test=%d",
        len(train_df), len(val_df), len(test_df),
    )
    return train_df, val_df, test_df


def build_datasets(
    tokenizer: AutoTokenizer,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
) -> tuple[Dataset, Dataset, Dataset]:
    ds_train = to_hf_dataset(train_df)
    ds_val = to_hf_dataset(val_df)
    ds_test = to_hf_dataset(test_df)

    def tok(batch):
        return tokenizer(
            batch["text"], max_length=MAX_LEN, truncation=True, padding=False
        )

    log.info("tokenizing splits (max_len=%d)…", MAX_LEN)
    ds_train = ds_train.map(tok, batched=True, remove_columns=["text"])
    ds_val = ds_val.map(tok, batched=True, remove_columns=["text"])
    ds_test = ds_test.map(tok, batched=True, remove_columns=["text"])
    return ds_train, ds_val, ds_test


def build_training_args() -> TrainingArguments:
    """Construct ``TrainingArguments`` with the local-run config.

    Forces CPU execution: the MPS allocator OOM'd at bs=4 on this Mac,
    so we drop to bs=1, accum=32, and disable both CUDA and MPS via
    ``use_cpu=True`` (transformers ≥ 4.46) or its legacy alias
    ``no_cuda=True`` (transformers ≤ 4.45).

    transformers also renamed ``evaluation_strategy`` to
    ``eval_strategy`` around 4.46. We try the new pairing first; on
    older versions the constructor raises ``TypeError`` and we fall
    back to the legacy names.
    """
    common = dict(
        output_dir=str(CHECKPOINT_DIR),
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=PER_DEVICE_TRAIN_BS,
        per_device_eval_batch_size=PER_DEVICE_TRAIN_BS * 2,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LEARNING_RATE,
        warmup_ratio=WARMUP_RATIO,
        weight_decay=WEIGHT_DECAY,
        lr_scheduler_type=LR_SCHEDULER,
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        fp16=False,
        logging_steps=LOGGING_STEPS,
        save_total_limit=SAVE_TOTAL_LIMIT,
        report_to="none",
        seed=SEED,
    )
    for kwargs in (
        dict(eval_strategy="epoch", use_cpu=True),          # transformers 4.46+
        dict(evaluation_strategy="epoch", no_cuda=True),    # transformers ≤ 4.45
    ):
        try:
            return TrainingArguments(**kwargs, **common)
        except TypeError as exc:
            log.info(
                "TrainingArguments rejected %s (%s); trying next API form",
                list(kwargs.keys()), exc,
            )
    raise RuntimeError(
        "no compatible TrainingArguments key set for this transformers version"
    )


def main() -> int:
    BEST_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Device probe — we deliberately force CPU below (see
    # build_training_args). The probe is still informative for the
    # log so we know what accelerator we *could* have used.
    if torch.backends.mps.is_available():
        accel = "mps"
    elif torch.cuda.is_available():
        accel = "cuda"
    else:
        accel = "cpu"
    device = "cpu"
    log.info(
        "device=%s (forced; %s available) torch=%s",
        device, accel, torch.__version__,
    )

    # 1. Data
    train_df, val_df, test_df = load_and_split()

    # 2. Tokenizer + model
    log.info("loading tokenizer %s …", BASE_MODEL)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    log.info("loading model %s (num_labels=2) …", BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=2, id2label=ID2LABEL, label2id=LABEL2ID
    )

    # 3. Tokenized HF datasets
    ds_train, ds_val, ds_test = build_datasets(tokenizer, train_df, val_df, test_df)

    # 4. Trainer
    args = build_training_args()
    collator = DataCollatorWithPadding(tokenizer=tokenizer)
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=ds_train,
        eval_dataset=ds_val,
        tokenizer=tokenizer,
        data_collator=collator,
        compute_metrics=compute_metrics,
        callbacks=[EpochTimerCallback(NUM_EPOCHS)],
    )

    # 5. Train
    log.info("starting training (%d epochs, batch=%d × accum=%d, lr=%.0e)",
             NUM_EPOCHS, PER_DEVICE_TRAIN_BS, GRAD_ACCUM, LEARNING_RATE)
    run_start = time.monotonic()
    train_result = trainer.train()
    train_seconds = int(time.monotonic() - run_start)
    log.info("training done in %s · metrics=%s",
             timedelta(seconds=train_seconds), train_result.metrics)

    # 6. Held-out evaluation
    log.info("evaluating on held-out test set (n=%d) …", len(ds_test))
    test_metrics = trainer.evaluate(ds_test, metric_key_prefix="test")
    log.info("test metrics:\n%s", json.dumps(test_metrics, indent=2))

    # 7+8. Save best model + tokenizer
    trainer.save_model(str(BEST_DIR))
    tokenizer.save_pretrained(str(BEST_DIR))
    log.info("saved best model → %s", BEST_DIR)

    # 9. Persist metrics
    metrics_blob = {
        "base_model": BASE_MODEL,
        "device": device,
        "training_seconds": train_seconds,
        "splits": {
            "train": len(train_df), "val": len(val_df), "test": len(test_df),
        },
        "training_args": {
            "num_train_epochs": NUM_EPOCHS,
            "per_device_train_batch_size": PER_DEVICE_TRAIN_BS,
            "gradient_accumulation_steps": GRAD_ACCUM,
            "learning_rate": LEARNING_RATE,
            "warmup_ratio": WARMUP_RATIO,
            "weight_decay": WEIGHT_DECAY,
            "lr_scheduler_type": LR_SCHEDULER,
            "fp16": False,
            "seed": SEED,
        },
        "best_eval": trainer.state.best_metric,
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "train_metrics": train_result.metrics,
        "test_metrics": test_metrics,
    }
    METRICS_PATH.write_text(json.dumps(metrics_blob, indent=2, default=str))
    log.info("saved metrics → %s", METRICS_PATH)

    # 10. Summary
    print("\n" + "=" * 72)
    print(" Lusaber · Լուսաբեր — training complete")
    print("=" * 72)
    print(f"  Device          : {device}")
    print(f"  Wall time       : {timedelta(seconds=train_seconds)}")
    print(f"  Best val F1     : {trainer.state.best_metric:.4f}")
    print(f"  Test F1         : {test_metrics.get('test_f1', float('nan')):.4f}")
    print(f"  Test accuracy   : {test_metrics.get('test_accuracy', float('nan')):.4f}")
    print(f"  Test ROC-AUC    : {test_metrics.get('test_roc_auc', float('nan')):.4f}")
    print(f"  Saved model     : {BEST_DIR}")
    print(f"  Saved metrics   : {METRICS_PATH}")
    print("=" * 72 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
