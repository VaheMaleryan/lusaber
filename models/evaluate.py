"""Lusaber · Լուսաբեր — evaluation & reporting (Phase 5).

Produces:

* Classification report per class.
* Confusion-matrix heatmap → ``evaluation/confusion_matrix.png``.
* ROC curve with AUC      → ``evaluation/roc_curve.png``.
* Precision-Recall curve  → ``evaluation/pr_curve.png``.
* 20 worked example predictions with red-flag explanations.
* Comparison against the majority-class and TF-IDF-only baselines.
* Aggregated metrics dump → ``evaluation/metrics.json``.

Target on held-out test set: macro F1 ≥ 0.78.

This module is a stub for Phase 5.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("lusaber.evaluate")
