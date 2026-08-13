"""Prompt Eval v0.

Measures what changes when only the grounded system instruction changes: the model, the
embedding, the retrieval result and the EvidenceCard context are all held fixed. Nothing in
this package is imported by `backend.app`; production behaviour is unaffected.
"""
