"""Initialization of the rewards rules package."""
from .abstract import AbstractRule
from .bday import Birthday
from .duration import EmploymentDuration
from .seller import BestSeller
from .random_users import RandomUsers
from .anniversary import WorkAnniversary, EmploymentAnniversary
from .attendance import AttendanceRule
from .achievement import AchievementRule
from .hierarchy import DirectManagerRule, HierarchyRelationshipRule
from .other import (
    EarlyBirdRule,
    MidWeekMotivatorRule,
    QuarterEndChampionRule,
    SeasonalBonusRule,
    OptimalTimingRule,
    WeekPositionRule,
    BusinessDaysRemainingRule,
    ComplexEnvironmentalRule
)

__all__ = (
    'AbstractRule',
    'Birthday',
    'EmploymentDuration',
    'BestSeller',
    'RandomUsers',
    'WorkAnniversary',
    'EmploymentAnniversary',
    'AttendanceRule',
    'AchievementRule',
    'DirectManagerRule',
    'HierarchyRelationshipRule',
    'EarlyBirdRule',
    'MidWeekMotivatorRule',
    'QuarterEndChampionRule',
    'SeasonalBonusRule',
    'OptimalTimingRule',
    'WeekPositionRule',
    'BusinessDaysRemainingRule',
    'ComplexEnvironmentalRule',
)
