"""Lusaber · Լուսաբեր — ensemble & calibration (Phase 3c).

Soft-voting ensemble that combines the XLM-RoBERTa classifier with the
LightGBM model trained on TF-IDF + Phase-2 features:

    final_prob = 0.65 * transformer_prob + 0.35 * lgbm_prob

The combined probabilities are then passed through
``CalibratedClassifierCV`` to map them onto a calibrated credibility
score in [0, 100]. Verdict thresholds::

    <  40 -> LIKELY DISINFORMATION
    40-65 -> UNCERTAIN
    >  65 -> LIKELY CREDIBLE

This module is a stub for Phase 3c.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("lusaber.ensemble")
