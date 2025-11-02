import contextlib
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import pandas as pd
try:
    from querysource.queries.qs import QS
    from querysource.exceptions import DataNotFound
except ImportError:
    print("QuerySource not Found")
from ..context import EvalContext
from ..env import Environment
from .abstract import AbstractRule


class AttendanceRule(AbstractRule):
    """Attendance Rule class.

    Check for perfect or near-perfect attendance on a time interval.

    Attributes:
    ----------
    count: int: Number of time units to look back
    unit: str: Time unit ('day', 'week', 'month')
    dataset: str: QuerySource slug for attendance data
    only_weekdays: bool: Whether to only consider weekdays (Mon-Fri)
    match: str: 'perfect' or 'partial' attendance requirement
    deviation: int: Max allowed missing days for 'partial' match
    filter_by: str: Date field name in the dataset
    conditions: dict: dictionary of conditions affecting the Rule object
    """

    def __init__(
        self,
        conditions: dict = None,
        period_type: str = 'rolling',  # 'rolling' or 'fixed'
        count: int = 1,
        unit: str = 'day',
        dataset: str = None,
        filter_by: str = 'attendance_date',
        match: str = 'perfect',
        deviation: int = 2,
        only_weekdays: bool = True,
        employee_identifier: str = 'associate_id',
        **kwargs
    ):
        super().__init__(conditions, **kwargs)
        self.name = "Attendance"
        self.description = "Check for perfect or near-perfect attendance on a time interval."  # noqa: E501
        self.period_type = period_type
        if period_type not in ['rolling', 'fixed']:
            raise ValueError("period_type must be 'rolling' or 'fixed'")
        # Validate inputs
        if not dataset:
            raise ValueError(
                "dataset parameter is required for AttendanceRule"
            )

        if unit not in ['day', 'week', 'month']:
            raise ValueError(
                f"Invalid unit '{unit}'. Must be 'day', 'week', or 'month'"
            )

        if match not in ['perfect', 'partial']:
            raise ValueError(
                f"Invalid match '{match}'. Must be 'perfect' or 'partial'"
            )

        if count <= 0:
            raise ValueError("count must be positive")

        if deviation < 0:
            raise ValueError("deviation must be non-negative")

        # Core attributes
        self.count: int = count
        self.unit: str = unit
        self.dataset: str = dataset
        self.filter_by: str = filter_by
        self.match: str = match
        self.deviation: int = deviation
        self.only_weekdays: bool = only_weekdays
        self.employee_identifier: str = employee_identifier

        # Additional attributes
        self.attributes = kwargs

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        """Check if the rule can be applied to the user."""
        if not ctx.user:
            return False

        # Check if user has associate_id (employee identifier)
        if not hasattr(
            ctx.user, self.employee_identifier
        ) or not getattr(ctx.user, self.employee_identifier):
            _id = getattr(ctx.user, 'email', 'unknown')
            self.logger.warning(
                f"User {_id} has no Employee Identifier "
                " ({self.employee_identifier}) set. "
                "Attendance rule cannot be applied."
            )
            return False

        return True

    def get_expected_dates(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> set:
        """
        Generate set of expected attendance dates based on configuration.

        Args:
            start_date: Start of the period
            end_date: End of the period

        Returns:
            Set of expected attendance dates
        """
        expected_dates = set()
        current_date = start_date

        while current_date <= end_date:
            if (
                self.only_weekdays
                and current_date.weekday() < 5
                or not self.only_weekdays
            ):
                # Only include weekdays (Monday=0 to Friday=4) or all days
                expected_dates.add(current_date.date())
            current_date += timedelta(days=1)

        return expected_dates

    def calculate_date_range(self, reference_date: datetime = None) -> tuple:
        """
        Calculate start and end dates based on period type.
        """
        if reference_date is None:
            reference_date = datetime.now()

        if self.period_type == 'rolling':
            # Rolling window - look back from reference date
            return self._calculate_rolling_range(reference_date)
        else:
            # Fixed period - use calendar boundaries
            return self._calculate_fixed_range(reference_date)

    def _calculate_rolling_range(self, reference_date: datetime) -> tuple:
        """Calculate rolling time window."""
        # End date is yesterday (to avoid incomplete current day)
        start_date = None
        end_date = reference_date.replace(
            hour=23,
            minute=59,
            second=59
        ) - timedelta(days=1)

        if self.unit == 'day':
            start_date = end_date - timedelta(days=self.count - 1)
        elif self.unit == 'week':
            start_date = end_date - timedelta(weeks=self.count) + timedelta(days=1)  # noqa: E501
        elif self.unit == 'month':
            start_date = end_date - relativedelta(months=self.count) + timedelta(days=1)  # noqa: E501

        return start_date, end_date

    def _calculate_fixed_range(self, reference_date: datetime) -> tuple:
        """Calculate fixed calendar period."""
        if self.unit == 'day':
            # For days, fixed period doesn't make much sense, so use rolling
            return self._calculate_rolling_range(reference_date)

        elif self.unit == 'week':
            # Current week (Monday to Sunday)
            days_since_monday = reference_date.weekday()
            start_date = reference_date - timedelta(days=days_since_monday)
            end_date = start_date + timedelta(days=6)

            # Go back additional weeks if count > 1
            if self.count > 1:
                start_date = start_date - timedelta(weeks=self.count - 1)

        elif self.unit == 'month':
            # Current month
            start_date = reference_date.replace(
                day=1,
                hour=0,
                minute=0,
                second=0
            )

            # Go back additional months if count > 1
            if self.count > 1:
                start_date = start_date - relativedelta(months=self.count - 1)

            # End of the current month
            next_month = reference_date.replace(day=1) + relativedelta(months=1)  # noqa: E501
            end_date = next_month - timedelta(days=1)
            end_date = end_date.replace(hour=23, minute=59, second=59)

        return start_date, end_date

    async def fetch_attendance_data(
        self,
        ctx: EvalContext,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Fetch attendance data for the user in the specified date range.

        Args:
            ctx: Evaluation context
            start_date: Start of the period
            end_date: End of the period

        Returns:
            DataFrame with attendance data
        """
        try:
            employee = getattr(
                ctx.user,
                self.employee_identifier,
                None
            )
            qry = QS(
                slug=self.dataset,
                lazy=True,
                conditions={
                    "fields": [self.filter_by],
                    "filter": {
                        self.filter_by: [
                            start_date.strftime("%Y-%m-%d"),
                            end_date.strftime("%Y-%m-%d")
                        ],
                        self.employee_identifier: employee
                    },
                    "group_by": [self.filter_by]
                }
            )

            await qry.build_provider()
            res, error = await qry.query()

            if error:
                self.logger.error(f"Error fetching attendance data: {error}")
                return pd.DataFrame()

            if not res:
                self.logger.warning(
                    f"No attendance data found for user {employee}"
                )
                return pd.DataFrame()

            # Convert to DataFrame
            df = pd.DataFrame([dict(r) for r in res])
            df = df.infer_objects()

            # Convert date column to datetime if it's string
            if self.filter_by in df.columns:
                df[self.filter_by] = pd.to_datetime(df[self.filter_by])

            return df

        except DataNotFound:
            self.logger.warning(
                f"Dataset '{self.dataset}' not found"
            )
            return pd.DataFrame()
        except Exception as err:
            self.logger.error(
                f"Error fetching attendance data: {err}"
            )
            return pd.DataFrame()

    def evaluate_attendance(
        self,
        expected_dates: set,
        actual_dates: set
    ) -> bool:
        """
        Evaluate attendance based on expected vs actual dates.

        Args:
            expected_dates: Set of expected attendance dates
            actual_dates: Set of actual attendance dates

        Returns:
            True if attendance meets criteria
        """
        if self.match == 'perfect':
            # All expected dates must be present in actual dates
            missing_dates = expected_dates - actual_dates
            result = len(missing_dates) == 0

            if not result:
                self.logger.debug(
                    f"Perfect attendance failed. Missing date: {missing_dates}"
                )

            return result

        elif self.match == 'partial':
            # Calculate missing days
            missing_dates = expected_dates - actual_dates
            missing_count = len(missing_dates)
            result = missing_count <= self.deviation

            self.logger.debug(
                f"Partial attendance: {missing_count} missing days "
                f"(allowed: {self.deviation}). Result: {result}"
            )

            if not result:
                self.logger.debug(f"Missing dates: {missing_dates}")

            return result

        return False

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        """
        Evaluate the attendance against the provided user context and env.

        Args:
            ctx: The evaluation context,
                containing user and session information.
            env: The environment information, such as the current time.

        Returns:
            True if the user meets the attendance criteria.
        """
        try:
            # Calculate date range
            start_date, end_date = self.calculate_date_range()
            employee_id = getattr(
                ctx.user,
                self.employee_identifier,
                'unknown'
            )
            self.logger.debug(
                f"Evaluating attendance for user {employee_id} "
                f"from {start_date.date()} to {end_date.date()}"
            )

            # Fetch attendance data
            df = await self.fetch_attendance_data(ctx, start_date, end_date)

            if df.empty:
                self.logger.warning(
                    f"No attendance data found for user {employee_id}"
                )
                return False

            # Get expected dates
            expected_dates = self.get_expected_dates(start_date, end_date)

            # Get actual attendance dates
            actual_dates = set()
            if self.filter_by in df.columns:
                # Convert datetime to date for comparison
                actual_dates = set(df[self.filter_by].dt.date.unique())

            self.logger.debug(
                f"Expected dates ({len(expected_dates)}): {sorted(expected_dates)}"  # noqa: E501
            )
            self.logger.debug(
                f"Actual dates ({len(actual_dates)}): {sorted(actual_dates)}"
            )

            # Evaluate attendance
            result = self.evaluate_attendance(expected_dates, actual_dates)

            employee_id = getattr(
                ctx.user,
                self.employee_identifier,
                'unknown'
            )
            self.logger.info(
                f"Attendance evaluation for {employee_id}: {result} "
                f"({self.match} attendance over {self.count} {self.unit}(s))"
            )

            return result

        except Exception as err:
            self.logger.error(
                f"Error evaluating attendance rule: {err}"
            )
            return False

    def get_attendance_summary(
        self,
        expected_dates: set,
        actual_dates: set
    ) -> dict:
        """
        Get a summary of attendance statistics.

        Args:
            expected_dates: Set of expected attendance dates
            actual_dates: Set of actual attendance dates

        Returns:
            Dictionary with attendance statistics
        """
        missing_dates = expected_dates - actual_dates
        extra_dates = actual_dates - expected_dates
        present_dates = expected_dates & actual_dates

        total_expected = len(expected_dates)
        total_present = len(present_dates)
        attendance_rate = (total_present / total_expected * 100) if total_expected > 0 else 0  # noqa: E501

        return {
            "total_expected_days": total_expected,
            "total_present_days": total_present,
            "total_missing_days": len(missing_dates),
            "attendance_rate_percent": round(attendance_rate, 2),
            "missing_dates": sorted(missing_dates),
            "extra_dates": sorted(extra_dates),
            "meets_criteria": self.evaluate_attendance(expected_dates, actual_dates)  # noqa: E501
        }
