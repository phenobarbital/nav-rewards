from datetime import datetime
from ..context import EvalContext
from ..env import Environment
from .abstract import AbstractRule


class EmploymentDuration(AbstractRule):
    """EmploymentDuration Rule class.

    Rule that checks if the user's employment duration is exactly one year.

    Attributes:
    ----------
    conditions: dict: dictionary of conditions affecting the Rule object
    """
    def __init__(self, conditions: dict = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "EmploymentDuration"
        self.description = "Checks if the user is on Anniversary of Employment"
        self.attributes = kwargs

    def fits(self, ctx, env):
        # Check if User has "start_date" attribute
        return hasattr(ctx.store['user'], 'start_date')

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        # Check if User has "start_date" attribute
        start_date = ctx.store['user'].start_date.date()
        if not start_date:
            return False
        if isinstance(start_date, str):
            try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            except Exception:
                return False

        # Get today's date
        today = datetime.now().date()

        # Check if today is the anniversary of the start_date
        return (
            today.month, today.day
        ) == (
            start_date.month, start_date.day
        ) and today.year > start_date.year
