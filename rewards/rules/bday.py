from datetime import datetime
from .abstract import AbstractRule

class Birthday(AbstractRule):
    """Birthday Rule class.

    Rule that checks if the user's birthday is today.

    Attributes:
    ----------
    conditions: dict: dictionary of conditions affecting the Rule object
    """
    def __init__(self, conditions: dict = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "Birthday"
        self.description = "Rule that checks if the user's birthday is today."
        self.attributes = kwargs

    def fits(self, ctx, env):
        # Check if User has "birthday" attribute
        if hasattr(ctx.store['user'], 'birthday'):
            return True
        return False

    async def evaluate(self, ctx, env):
        # Check if User has "birthday" attribute
        today = datetime.now().date()
        try:
            bday = ctx.store['user'].birth_date()
        except ValueError:
            bday = ctx.store['user'].birthday
        if not bday:
            return False
        if isinstance(bday, str):
            try:
                bday = datetime.strptime(bday, "%Y-%m-%d").date()
            except Exception:
                return False
        # Check if today's month and day match the employee's birth
        return bday == today
