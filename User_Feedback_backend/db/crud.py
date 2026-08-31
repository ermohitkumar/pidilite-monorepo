"""
Backward-compatibility shim — all CRUD helpers have moved to
repositories.batch_repository. This module re-exports them so that
existing imports (e.g. scripts/seed.py) continue to work.
"""
from repositories.batch_repository import *  # noqa: F401,F403
