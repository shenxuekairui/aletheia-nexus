"""Opt-in AI literature processing; canonical sources remain read-only."""

from .contracts import load_task, validate_task
from .engine import run_task

__all__ = ["load_task", "run_task", "validate_task"]
