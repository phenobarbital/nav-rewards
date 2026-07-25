"""Environment for reward evaluation.

The implementation now lives in the shared `navrules` engine
(navrules.environment.Environment): same field names, same derived
calculations, plus `Environment.at(timestamp, tz=...)` and an `extra` dict
for ambient values. This module re-exports it to keep import paths stable.
"""
from datetime import datetime, timezone
import time as tt

from navrules import Environment

__all__ = ("Environment", "now", "now_date", "curtime")


def now():
    return datetime.now(tz=timezone.utc)


def now_date():
    return datetime.now(tz=timezone.utc).date()


def curtime():
    return tt.time()
