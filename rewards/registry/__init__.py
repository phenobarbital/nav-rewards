# Dynamic Achievement System with String Routes
from typing import Callable, Optional
import importlib
from navconfig.logging import logging
from navrules.registry import FunctionRegistry


class AchievementRegistry(FunctionRegistry):
    """Registry for dynamically loaded achievement calculation functions.

    Backed by navrules.FunctionRegistry, which fixes the historical bug
    where `register()` wrote to an attribute that was never initialized
    (`self._functions`), raising AttributeError on every registration.
    """

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger('rewards.AchievementRegistry')


# Integration Helper:
class AchievementLoader:
    """Helper to load and register achievement functions."""

    def __init__(
        self,
        registry: AchievementRegistry,
        base_path: str = "rewards.functions"
    ):
        self.registry = registry
        self.base_path = base_path
        self.logger = logging.getLogger('rewards.AchievementLoader')

    def preload_modules(self, module_names: list):
        """Preload achievement modules to warm the cache."""
        for module_name in module_names:
            try:
                module_path = f"{self.base_path}.{module_name}"
                importlib.import_module(module_path)
                self.logger.info(
                    f"Preloaded achievement module: {module_path}"
                )
            except ImportError as err:
                self.logger.warning(
                    f"Failed to preload module {module_name}: {err}"
                )

    def validate_function_path(self, function_path: str) -> bool:
        """Validate that a function path exists and is callable."""
        func = self.registry.get_function(function_path)
        return func is not None

    def load(self, function_path: str) -> Optional[Callable]:
        """Load an achievement function and register it."""
        func = self.registry.load_function(function_path)
        if func:
            self.registry.register(function_path, func)
        return func
