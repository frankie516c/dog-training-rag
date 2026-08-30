from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_freeze_training_eval.py"
SPEC = importlib.util.spec_from_file_location("validate_freeze_training_eval", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ValidateFreezeTrainingEvalTests(unittest.TestCase):
    def test_rejects_rows_with_missing_anchor(self):
        rows = [{"query_id": "q", "review_status": "APPROVED", "coverage": "answerable", "query_type": "potty_training", "anchors": []}]
        with self.assertRaises(ValueError):
            module.validate(rows, {})

