import pandas as pd
from .computed import ComputedRule


class Birthday(ComputedRule):
    """Birthday Rule class.

    ComputedRule that finds all users whose birthday is today.
    Used for scheduled birthday badge awards.

    Attributes:
    ----------
    conditions: dict: dictionary of conditions affecting the Rule object
    column: str: name of the birthday column (default: 'birthday')
    table: str: table/view to query (default: 'auth.vw_users')
    employee_id: str: employee ID column name (default: 'associate_id')
    """
    def __init__(self, conditions: dict = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "Birthday"
        self.description = "Rule that finds all users with birthday today."
        self.attributes = kwargs
        # Configurable column name for the birthday field (default: 'birthday')
        self.column = kwargs.get('column', 'birthday')
        # Configurable table/view name (default: 'auth.vw_users')
        self.table = kwargs.get('table', 'auth.vw_users')
        # Configurable employee ID column name (default: 'associate_id')
        self.employee_id = kwargs.get('employee_id', 'associate_id')

    async def _get_candidates(
        self,
        env,
        dataset=None
    ) -> list:
        """
        Get all users whose birthday is today.

        Queries auth.vw_users for active users where the month and day
        of their birthday match today's date.

        :param env: The environment information.
        :param dataset: Optional dataset (unused).
        :return: DataFrame of users with birthdays today.
        """
        async with await env.connection.acquire() as conn:
            # Query users where birthday (string YYYY-MM-DD) matches today's month/day
            # birthday column is stored as string like '1964-10-03'
            query = f"""
                SELECT u.user_id, u.{self.employee_id} as associate_id, u.email, u.display_name, u.{self.column} as birthday
                FROM {self.table} u
                WHERE u.is_active = true
                AND u.{self.column} IS NOT NULL
                AND u.{self.column} != ''
                AND EXTRACT(MONTH FROM u.{self.column}::date) = EXTRACT(MONTH FROM CURRENT_DATE)
                AND EXTRACT(DAY FROM u.{self.column}::date) = EXTRACT(DAY FROM CURRENT_DATE)
            """
            try:
                result = await conn.fetch_all(query)
                df = self.get_dataframe(result)
                if df is not None and not df.empty:
                    self.logger.info(
                        f"Found {len(df)} users with birthday today"
                    )
                else:
                    self.logger.info("No users with birthday today")
                    return pd.DataFrame()
                return df
            except Exception as exc:
                self.logger.error(
                    f"Error fetching birthday candidates: {exc}"
                )
                return pd.DataFrame()
