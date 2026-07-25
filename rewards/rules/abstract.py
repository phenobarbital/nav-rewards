from typing import Optional
from navconfig.logging import logging
from navrules import AbstractRule as BaseAbstractRule
from ..env import Environment  # noqa: F401 - re-exported for subclasses
from ..context import EvalContext  # noqa: F401 - re-exported for subclasses


class AbstractRule(BaseAbstractRule):
    """AbstractRule Rule class.

    Base class for all Rules defined on the Reward System. The two-phase
    contract (sync `fits()` pre-filter + async `evaluate()`) now lives in
    navrules.AbstractRule, which also adds `priority` and `result` support;
    this subclass keeps the navconfig logger (`.notice()` et al.) and the
    historical string representation.
    """

    def __init__(
            self,
            conditions: Optional[dict] = None,
            **kwargs
    ):
        super().__init__(conditions, **kwargs)
        self.logger = logging.getLogger(__name__)

    def __str__(self):
        return f"<{self.name}:>"
