"""Lusaber · Լուսաբեր — training entry point (Phase 3).

Fine-tunes ``xlm-roberta-base`` for binary credibility classification
on the Armenian disinformation dataset and trains the LightGBM
companion model used in the soft-voting ensemble.

This module is a stub. The full training pipeline (HuggingFace
``Trainer``, ``compute_metrics``, FP16, cosine schedule) is built
out in Phase 3 after Phase 1 and 2 are accepted.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("lusaber.train")
