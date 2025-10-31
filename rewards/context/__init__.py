from typing import Callable
from .eval import EvalContext, achievement_registry


def register_achievement(name: str):
    """Decorator to register achievement functions."""
    def decorator(func: Callable):
        achievement_registry.register(name, func)
        return func
    return decorator


__all__ = (
    'EvalContext',
    'achievement_registry',
    'register_achievement',
)
