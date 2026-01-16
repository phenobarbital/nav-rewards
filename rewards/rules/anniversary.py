from datetime import datetime
import pandas as pd
from dateutil.relativedelta import relativedelta
from ..context import EvalContext
from ..env import Environment
from .abstract import AbstractRule
from .computed import ComputedRule


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


class EmploymentAnniversary(ComputedRule):
    """EmploymentAnniversary Rule class.

    ComputedRule that finds all users whose employment anniversary is today.
    Used for scheduled anniversary badge awards (1 year, 5 years, 10 years, etc.).

    Attributes:
    ----------
    conditions: dict: dictionary of conditions affecting the Rule object
    column: str: name of the date column to use (default: 'start_date')
    starting_year: int: minimum years of employment to match (default: 1)
    """
    def __init__(self, conditions: dict = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "EmploymentAnniversary"
        self.description = "Rule that finds all users with employment anniversary today."
        self.attributes = kwargs
        # Configurable column name for the start date field (default: 'start_date')
        self.column = kwargs.get('column', 'start_date')
        # Starting year for anniversary (default: 1 year)
        # This finds users who have been employed for exactly N years as of today
        self.starting_year = kwargs.get('starting_year', 1)

    async def _get_candidates(
        self,
        env,
        dataset=None
    ) -> list:
        """
        Get all users whose employment anniversary is today.

        Queries auth.vw_users for active users where:
        - The month and day of their start_date match today's date
        - Their employment duration is at least `starting_year` years

        :param env: The environment information.
        :param dataset: Optional dataset (unused).
        :return: DataFrame of users with employment anniversary today.
        """
        async with await env.connection.acquire() as conn:
            # Query users where start_date matches today's month/day
            # and employment duration is exactly N years
            query = f"""
                SELECT 
                    u.user_id, 
                    u.associate_id, 
                    u.email, 
                    u.display_name, 
                    u.{self.column} as start_date,
                    EXTRACT(YEAR FROM AGE(CURRENT_DATE, u.{self.column}::date))::int as years_employed
                FROM auth.vw_users u
                WHERE u.is_active = true
                AND u.{self.column} IS NOT NULL
                AND EXTRACT(MONTH FROM u.{self.column}::date) = EXTRACT(MONTH FROM CURRENT_DATE)
                AND EXTRACT(DAY FROM u.{self.column}::date) = EXTRACT(DAY FROM CURRENT_DATE)
                AND EXTRACT(YEAR FROM AGE(CURRENT_DATE, u.{self.column}::date))::int >= {self.starting_year}
            """
            try:
                result = await conn.fetch_all(query)
                df = self.get_dataframe(result)
                if df is not None and not df.empty:
                    self.logger.info(
                        f"Found {len(df)} users with employment anniversary today "
                        f"(>= {self.starting_year} years)"
                    )
                else:
                    self.logger.info(
                        f"No users with employment anniversary today "
                        f"(>= {self.starting_year} years)"
                    )
                    return pd.DataFrame()
                return df
            except Exception as exc:
                self.logger.error(
                    f"Error fetching anniversary candidates: {exc}"
                )
                return pd.DataFrame()

