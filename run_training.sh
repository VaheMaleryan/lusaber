#!/bin/bash
cd "$(dirname "$0")"
echo "Starting Lusaber training — estimated 3-4 hours on M2 Pro"
echo "Logs will be saved to training.log"
venv/bin/python models/train_local.py 2>&1 | tee training.log
echo "Done. Check training.log for results."
