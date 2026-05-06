#!/usr/bin/env python3
"""Compatibility shim for older imports.

The web worker now delegates to the canonical ClusterWeave shell workflow via
``canonical_pipeline``. Keep this module as a small forwarding layer so older
local tooling that imports ``pipeline`` does not silently run the removed
direct-runner implementation.
"""
try:
    from canonical_pipeline import Job, JobStatus, run_pipeline
except ImportError:  # pragma: no cover - package-style imports in local tests
    from .canonical_pipeline import Job, JobStatus, run_pipeline

__all__ = ["Job", "JobStatus", "run_pipeline"]
