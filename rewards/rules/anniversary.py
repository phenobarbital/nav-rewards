from datetime import datetime
from dateutil.relativedelta import relativedelta
from ..context import EvalContext
from ..env import Environment
from .abstract import AbstractRule


class WorkAnniversary(AbstractRule):
    """WorkAnniversary Rule class.

    Rule that checks if the user's employment duration is exactly one year.

    Attributes:
    ----------
    conditions: dict: dictionary of conditions affecting the Rule object
    """
    def __init__(self, conditions: dict = None, years: int = 1, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "WorkAnniversary"
        self.description = "Checks if the user is on Anniversary of Employment"
        self.years: int = years
        self.attributes = kwargs

    def fits(self, ctx, env):
        # Check if User has "start_date" attribute
        return hasattr(ctx.store['user'], 'start_date')

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        # Check if User has "start_date" attribute
        start_date = ctx.user.start_date
        if not start_date:
            return False

        start_date = start_date.date()
        if isinstance(start_date, str):
            try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            except Exception:
                return False

        # Get today's date
        today = datetime.now().date()

        # Check if anniversary
        # Calculate the difference between today and the start date
        difference = relativedelta(today, start_date)

        # Check if the difference is greater than self.years
        if difference.years >= self.years:
            return True
        else:
            return False
