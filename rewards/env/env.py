from typing import Literal
from datetime import datetime, date, time, timedelta
import time as tt
import calendar
from redis.asyncio.client import Redis
from asyncdb.drivers.pg import pgPool
from datamodel import BaseModel, Field


def now():
    return datetime.now()

def now_date():
    return datetime.now().date()

def curtime():
    return tt.time()

class Environment(BaseModel):
    # Original time fields
    curtime: time = Field(default_factory=curtime)
    timestamp: datetime = Field(default_factory=now)
    dow: int
    day_of_week: str
    day: str
    hour: int
    curdate: date = Field(required=False, default=now_date)
    month: int
    month_name: str
    year: int

    # New environmental variables
    day_period: Literal["morning", "noon", "afternoon", "evening", "night"]
    is_business_hours: bool
    is_weekend: bool
    is_weekday: bool
    quarter: Literal["Q1", "Q2", "Q3", "Q4"]
    season: Literal["spring", "summer", "fall", "winter"]
    week_of_year: int
    days_until_weekend: int
    days_since_weekend: int
    is_month_start: bool  # First 3 days of month
    is_month_end: bool    # Last 3 days of month
    is_quarter_end: bool  # Last month of quarter
    is_year_end: bool     # December
    days_in_current_month: int
    business_days_in_month: int
    business_days_remaining: int
    is_holiday_season: bool  # Nov-Dec
    is_summer_season: bool   # Jun-Aug
    week_position: Literal[
        "first",
        "second",
        "third",
        "fourth",
        "last"
    ]  # Week position in month
    is_pay_period: bool      # Assuming bi-weekly pay periods
    timezone_name: str

    # Infrastructure
    connection: pgPool = Field(required=False)
    cache: Redis = Field(required=False)

    def __post_init__(self):
        # Original calculations
        self.hour = self.timestamp.hour
        self.dow = self.timestamp.weekday()
        self.day_of_week = self.timestamp.strftime('%A')
        self.curdate = self.timestamp.date()
        self.curtime = self.timestamp.time()
        self.day = self.curdate.strftime('%Y-%m-%d')
        self.month = self.timestamp.month
        self.month_name = self.timestamp.strftime('%B')
        self.year = self.timestamp.year

        # New environmental calculations
        self.day_period = self._calculate_day_period()
        self.is_business_hours = self._is_business_hours()
        self.is_weekend = self.dow >= 5  # Saturday = 5, Sunday = 6
        self.is_weekday = not self.is_weekend
        self.quarter = self._get_quarter()
        self.season = self._get_season()
        self.week_of_year = self.timestamp.isocalendar()[1]
        self.days_until_weekend = self._days_until_weekend()
        self.days_since_weekend = self._days_since_weekend()
        self.days_in_current_month = calendar.monthrange(
            self.year,
            self.month
        )[1]
        self.is_month_start = self.curdate.day <= 3
        self.is_month_end = self._is_month_end()
        self.is_quarter_end = self.month in [3, 6, 9, 12]
        self.is_year_end = self.month == 12
        self.business_days_in_month = self._count_business_days_in_month()
        self.business_days_remaining = self._count_business_days_remaining()
        self.is_holiday_season = self.month in [11, 12]
        self.is_summer_season = self.month in [6, 7, 8]
        self.week_position = self._get_week_position()
        self.is_pay_period = self._is_pay_period()
        self.timezone_name = self._get_timezone_name()

        super(Environment, self).__post_init__()

    def _calculate_day_period(self) -> str:
        """Calculate the period of day based on hour."""
        hour = self.timestamp.hour

        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 13:
            return "noon"
        elif 13 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"

    def _is_business_hours(self) -> bool:
        """
        Check if current time is within business hours
        (9 AM - 5 PM, weekdays).
        """
        return False if self.is_weekend else 9 <= self.hour < 17

    def _get_quarter(self) -> str:
        """Get the business quarter."""
        if self.month <= 3:
            return "Q1"
        elif self.month <= 6:
            return "Q2"
        elif self.month <= 9:
            return "Q3"
        else:
            return "Q4"

    def _get_season(self) -> str:
        """Get the meteorological season."""
        if self.month in [12, 1, 2]:
            return "winter"
        elif self.month in [3, 4, 5]:
            return "spring"
        elif self.month in [6, 7, 8]:
            return "summer"
        else:
            return "fall"

    def _days_until_weekend(self) -> int:
        """Calculate days until next weekend (Saturday)."""
        return 0 if self.is_weekend else 5 - self.dow  # 5 = Saturday

    def _days_since_weekend(self) -> int:
        """Calculate days since last weekend ended (Sunday)."""
        if self.dow == 6:  # Sunday
            return 0
        elif self.dow == 5:  # Saturday
            return 6  # Since last Sunday
        else:
            return self.dow + 1  # Monday = 1 day since Sunday

    def _is_month_end(self) -> bool:
        """Check if we're in the last 3 days of the month."""
        return self.curdate.day > self.days_in_current_month - 3

    def _count_business_days_in_month(self) -> int:
        """Count business days (Monday-Friday) in current month."""
        first_day = self.curdate.replace(day=1)
        last_day = self.curdate.replace(day=self.days_in_current_month)

        business_days = 0
        current_day = first_day

        while current_day <= last_day:
            if current_day.weekday() < 5:  # Monday=0, Friday=4
                business_days += 1
            current_day += timedelta(days=1)

        return business_days

    def _count_business_days_remaining(self) -> int:
        """Count remaining business days in current month."""
        last_day = self.curdate.replace(day=self.days_in_current_month)

        business_days = 0
        current_day = self.curdate + timedelta(days=1)  # Start from tomorrow

        while current_day <= last_day:
            if current_day.weekday() < 5:  # Monday=0, Friday=4
                business_days += 1
            current_day += timedelta(days=1)

        return business_days

    def _get_week_position(self) -> str:
        """Get the position of current week in the month."""
        # Calculate which week of the month we're in
        first_day = self.curdate.replace(day=1)
        week_number = ((self.curdate.day - 1) // 7) + 1

        # Check if it's the last week
        last_day = self.curdate.replace(day=self.days_in_current_month)
        if self.curdate.day > self.days_in_current_month - 7:
            return "last"

        positions = ["first", "second", "third", "fourth", "last"]
        return positions[min(week_number - 1, 3)]

    def _is_pay_period(self) -> bool:
        """
        Check if we're in a typical bi-weekly pay period end
        (every other Friday).
        """
        # Assuming pay periods end on Fridays, every 2 weeks
        # This is a simplified calculation - in reality, you'd want to
        # configure actual pay period dates
        if self.dow == 4:  # Friday
            # Simple heuristic: pay periods typically end on 1st and 3rd Friday
            friday_count = 0
            for day in range(1, self.curdate.day + 1):
                test_date = self.curdate.replace(day=day)
                if test_date.weekday() == 4:  # Friday
                    friday_count += 1
            return friday_count in [1, 3]
        return False

    def _get_timezone_name(self) -> str:
        """Get timezone name if available."""
        try:
            if hasattr(self.timestamp, 'tzinfo') and self.timestamp.tzinfo:
                return str(self.timestamp.tzinfo)
            return "UTC"
        except Exception:
            return "UTC"

    # Additional utility methods for complex environmental checks
    def is_milestone_day(self) -> bool:
        """Check if today is a milestone day (1st, 15th, last day of month)."""
        return self.curdate.day in [1, 15, self.days_in_current_month]

    def is_mid_week(self) -> bool:
        """Check if today is mid-week (Tuesday, Wednesday, Thursday)."""
        return self.dow in [1, 2, 3]

    def is_week_start(self) -> bool:
        """Check if today is start of work week (Monday)."""
        return self.dow == 0

    def is_week_end(self) -> bool:
        """Check if today is end of work week (Friday)."""
        return self.dow == 4

    def get_work_intensity(self) -> Literal["low", "medium", "high"]:
        """Get subjective work intensity based on day and time."""
        if self.is_weekend:
            return "low"
        elif self.is_month_end or self.is_quarter_end:
            return "high"
        elif self.day_period in ["morning", "afternoon"] and self.is_weekday:
            return "high"
        elif self.day_period in ["evening", "night"]:
            return "low"
        else:
            return "medium"

    def get_reward_timing_score(self) -> int:
        """Get a score (1-10) indicating how good the timing is for rewards."""
        score = 5  # Base score

        # Positive factors
        if self.day_period in ["morning", "noon"]:
            score += 2
        if self.is_weekday:
            score += 1
        if self.is_month_start:
            score += 1
        if self.dow == 4:  # Friday
            score += 2

        # Negative factors
        if self.day_period == "night":
            score -= 2
        if self.is_weekend:
            score -= 1
        if self.is_month_end and not self.is_quarter_end:
            score -= 1

        return max(1, min(10, score))

    def to_dict(self) -> dict:
        """Convert environment to dictionary for easy rule evaluation."""
        return {
            'hour': self.hour,
            'day_of_week': self.day_of_week,
            'day_period': self.day_period,
            'is_business_hours': self.is_business_hours,
            'is_weekend': self.is_weekend,
            'is_weekday': self.is_weekday,
            'quarter': self.quarter,
            'season': self.season,
            'month': self.month,
            'month_name': self.month_name,
            'year': self.year,
            'week_of_year': self.week_of_year,
            'days_until_weekend': self.days_until_weekend,
            'days_since_weekend': self.days_since_weekend,
            'is_month_start': self.is_month_start,
            'is_month_end': self.is_month_end,
            'is_quarter_end': self.is_quarter_end,
            'is_year_end': self.is_year_end,
            'is_holiday_season': self.is_holiday_season,
            'is_summer_season': self.is_summer_season,
            'week_position': self.week_position,
            'is_pay_period': self.is_pay_period,
            'work_intensity': self.get_work_intensity(),
            'reward_timing_score': self.get_reward_timing_score()
        }
