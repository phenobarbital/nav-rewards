from typing import Union
from ..env import Environment
from ..context.eval import EvalContext, achievement_registry
from .abstract import AbstractRule


class AchievementRule(AbstractRule):
    """
    Rule that evaluates achievement thresholds using function loading.
    This rule allows dynamic evaluation of user achievements based on
    configurable functions and thresholds.
    Attributes:
    ----------
    function_path: str: Path to the achievement function to evaluate
    threshold: Union[int, float]: The threshold value to compare against
    operator: str: The comparison operator to use (gte, gt, lte, lt, eq, ne)
    function_params: dict: Additional parameters to pass to the achievement fn
    """

    def __init__(self, conditions: dict = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "Achievement"
        self.description = "Rule that checks achievement thresholds"

        # Achievement configuration
        self.achievement_name = kwargs.get('achievement_name', None)
        self.function_path = kwargs.get('function_path')
        self.threshold = kwargs.get('threshold', 0)
        # gte, gt, lte, lt, eq, ne
        self.operator = kwargs.get('operator', 'gte')
        self.function_params = kwargs.get('function_params', {})

        # Support legacy achievement_name for backward compatibility
        if not self.function_path and self.achievement_name:
            self.function_path = f"rewards.functions.{self.achievement_name}"

        if not self.function_path:
            raise ValueError(
                "function_path is required for AchievementRule"
            )

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        """Check if the rule can be applied to the user."""
        # Try to load the function to validate it exists
        func = achievement_registry.get_function(self.function_path)
        if not func:
            self.logger.warning(
                f"Achievement function '{self.function_path}' not available"
            )
            return False
        # Check if user exists
        return bool(ctx.user)

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        """Evaluate the achievement against the threshold."""
        try:
            # Get the achievement value
            value = await ctx.get_achievement(
                self.function_path,
                env,
                **self.function_params
            )

            if value is None:
                return False

            # Evaluate against threshold
            return self._compare_value(value, self.threshold, self.operator)

        except Exception as err:
            self.logger.error(
                f"Error evaluating dynamic achievement rule: {err}"
            )
            return False

    def _compare_value(
        self,
        value: Union[int, float],
        threshold: Union[int, float],
        operator: str
    ) -> bool:
        """Compare value against threshold using the specified operator."""
        operators = {
            'gte': lambda v, t: v >= t,
            'gt': lambda v, t: v > t,
            'lte': lambda v, t: v <= t,
            'lt': lambda v, t: v < t,
            'eq': lambda v, t: v == t,
            'ne': lambda v, t: v != t,
        }

        if operator not in operators:
            raise ValueError(f"Invalid operator: {operator}")

        return operators[operator](value, threshold)
