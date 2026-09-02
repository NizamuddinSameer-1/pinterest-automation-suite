"""
Pipeline stage errors.

Every stage in the pipeline must either produce a trustworthy result or raise.
Returning a plausible-looking placeholder is not allowed: it makes a failed run
indistinguishable from a successful one, which is how this project ended up with
0 rows in `reference_analyses` and `critiques` while jobs sat in `PASS`.
"""

from __future__ import annotations


class PipelineStageError(RuntimeError):
    """A pipeline stage could not produce a usable result."""

    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"[{stage}] {reason}")
        self.stage = stage
        self.reason = reason
