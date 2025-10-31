from typing import Optional
from ..env import Environment
from ..context import EvalContext
from .abstract import AbstractRule


class EarlyBirdRule(AbstractRule):
    """Reward for early morning activity during business hours."""

    def __init__(self, conditions: Optional[dict] = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "Early Bird"
        self.description = "Reward for activity during early morning hours"

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        return (
            env.day_period == "morning" and env.is_weekday and env.hour < 9
        )  # Before standard business hours

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return True  # If it fits, it's earned


class MidWeekMotivatorRule(AbstractRule):
    """Boost morale during mid-week slump."""

    def __init__(self, conditions: Optional[dict] = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "Mid-Week Motivator"
        self.description = "Special recognition during mid-week"

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        return (env.is_mid_week() and
                env.day_period in ["afternoon", "evening"])

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return True


class QuarterEndChampionRule(AbstractRule):
    """Recognition for end-of-quarter performance."""

    def __init__(self, conditions: Optional[dict] = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "Quarter End Champion"
        self.description = "Recognition during high-intensity quarter end"

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        return (
            env.is_quarter_end and env.is_month_end and env.get_work_intensity() == "high"  # noqa
        )

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return True


class SeasonalBonusRule(AbstractRule):
    """Seasonal rewards based on time of year."""

    def __init__(self, conditions: Optional[dict] = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "Seasonal Bonus"
        self.description = "Seasonal recognition rewards"

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        # Different criteria for different seasons
        if env.season == "summer":
            return env.is_summer_season and env.day_period == "morning"
        elif env.season == "winter":
            return env.is_holiday_season and env.is_weekday
        return env.season in ["spring", "fall"]

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return True


class PayPeriodPerformanceRule(AbstractRule):
    """Reward timed with pay periods."""

    def __init__(self, conditions: Optional[dict] = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "Pay Period Performance"
        self.description = "Performance reward aligned with pay period"

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        return env.is_pay_period and env.is_week_end()

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return True


class OptimalTimingRule(AbstractRule):
    """Reward based on optimal timing score."""

    def __init__(
        self,
        conditions: Optional[dict] = None,
        min_score: int = 8,
        **kwargs
    ):
        super().__init__(conditions, **kwargs)
        self.name = "Optimal Timing"
        self.description = "Reward for optimal timing conditions"
        self.min_score = min_score

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        return env.get_reward_timing_score() >= self.min_score

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return True


class MonthlyMilestoneRule(AbstractRule):
    """Reward for milestone days in the month."""

    def __init__(self, conditions: Optional[dict] = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "Monthly Milestone"
        self.description = "Recognition on significant days of the month"

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        return (env.is_milestone_day() and
                env.is_business_hours and
                env.business_days_remaining > 0)

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return True


class WeekPositionRule(AbstractRule):
    """Different rewards based on week position in month."""

    def __init__(
        self,
        conditions: Optional[dict] = None,
        target_week: str = "first",
        **kwargs
    ):
        super().__init__(conditions, **kwargs)
        self.name = f"Week Position ({target_week.title()})"
        self.description = f"Recognition for {target_week} week activities"
        self.target_week = target_week

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        return (
            env.week_position == self.target_week and env.is_weekday
        )

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return True


class BusinessDaysRemainingRule(AbstractRule):
    """Urgency-based rewards as month end approaches."""

    def __init__(
        self,
        conditions: Optional[dict] = None,
        max_days: int = 3, **kwargs
    ):
        super().__init__(conditions, **kwargs)
        self.name = "Month End Sprint"
        self.description = "Urgency reward as month end approaches"
        self.max_days = max_days

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        return (
            env.business_days_remaining <= self.max_days and env.business_days_remaining > 0 and env.is_weekday  # noqa
        )

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return True


class ComplexEnvironmentalRule(AbstractRule):
    """Complex rule combining multiple environmental factors."""

    def __init__(self, conditions: Optional[dict] = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "Perfect Storm"
        self.description = "Complex environmental condition reward"

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        # Complex conditions combining multiple factors
        perfect_timing = (
            env.day_period == "morning" and env.is_weekday and
            env.week_position in ["first", "second"] and
            env.days_until_weekend >= 2
        )

        seasonal_bonus = (
            env.season in ["spring", "fall"] and
            not env.is_holiday_season
        )

        business_optimal = (
            env.is_business_hours and
            env.get_work_intensity() == "medium" and
            env.business_days_remaining > 5
        )

        return perfect_timing and seasonal_bonus and business_optimal

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return True
