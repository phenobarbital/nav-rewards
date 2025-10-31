# Dynamic Achievement System with String Routes
from typing import Callable, Dict, Optional
import importlib
import inspect
from navconfig.logging import logging


class AchievementRegistry:
    """Registry for dynamically loaded achievement calculation functions."""

    def __init__(self):
        self._loaded_functions: Dict[str, Callable] = {}
        self._function_cache: Dict[str, Callable] = {}
        self.logger = logging.getLogger('rewards.AchievementRegistry')

    def _load_function_from_path(self, function_path):
        # Split module path and function name
        module_path, function_name = function_path.rsplit('.', 1)
        # Import the module
        module = importlib.import_module(module_path)
        # Get the function
        func = getattr(module, function_name)
        # Validate function signature
        self._validate_function_signature(func, function_path)
        # Cache the function
        self._function_cache[function_path] = func
        self.logger.info(f"Loaded achievement function: {function_path}")
        return func

    def load_function(self, function_path: str) -> Optional[Callable]:
        """
        Dynamically load an achievement function from a string path.

        Args:
            function_path: String like "rewards.functions.calls.get_call_count"

        Returns:
            The loaded function or None if not found
        """
        # Check cache first
        if function_path in self._function_cache:
            return self._function_cache[function_path]

        try:
            # Attempt to load the function from the path
            return self._load_function_from_path(function_path)

        except (ImportError, AttributeError, ValueError) as err:
            self.logger.error(
                f"Failed to load achievement function '{function_path}': {err}"
            )
            return None

    def _validate_function_signature(self, func: Callable, path: str):
        """Validate that the function has the expected signature."""
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        # Expected: (user, env, conn, **kwargs) or async version
        if len(params) < 3:
            raise ValueError(
                f"Function {path} must accept at least (user, env, conn) args"
            )

        if not inspect.iscoroutinefunction(func):
            raise ValueError(
                f"Achievement function {path} must be async"
            )

    def get_function(self, function_path: str) -> Optional[Callable]:
        """Get an achievement function, loading it if necessary."""
        return self.load_function(function_path)

    def clear_cache(self):
        """Clear the function cache."""
        self._function_cache.clear()
        self.logger.info("Achievement function cache cleared")

    def list_functions(self) -> list:
        """List all loaded function paths."""
        return list(self._function_cache.keys())

    def register(self, name: str, func: Callable):
        """Register an achievement calculation function.

        Args:
            name: The name of the achievement attribute
            func: A callable that takes (user, env, conn, **kwargs)
                and returns a value
        """
        self._functions[name] = func
        self.logger.info(f"Registered achievement function: {name}")


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
