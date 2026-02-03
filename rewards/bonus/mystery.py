"""
Mystery Box Computed Reward for NAV-Rewards.

This module provides:
- MysteryBoxReward: A computed badge type that awards random prizes
- Scheduler integration for automated mystery box events
- Notification integration

Usage in rewards.json:
{
    "reward_id": 9000,
    "reward": "Mystery Box Event",
    "description": "Random prizes awarded throughout the day!",
    "points": 0,
    "reward_type": "Computed Badge",
    "reward_category": "Mystery Box",
    "rules": [
        ["MysteryBoxRule", {
            "winner_count": 3,
            "expires_in_days": 30,
            "tier_boost": {"5": 0.10},
            "eligibility": {
                "min_tenure_days": 30,
                "exclude_recent_winners_days": 7
            }
        }]
    ],
    "job": {
        "trigger": "cron",
        "cron": {
            "minute": "0,30",
            "hour": "9-17",
            "day_of_week": "mon-fri"
        },
        "id": "mystery_box_workday",
        "name": "Workday Mystery Box",
        "timezone": "America/New_York"
    }
}
"""
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime, timedelta
from decimal import Decimal
import random
import asyncio

from navconfig.logging import logging

if TYPE_CHECKING:
    from ..rewards.base import EvalContext, Environment
    from ..models import RewardView

from .service import MarketplaceService, AwardSource


class MysteryBoxRule:
    """
    Rule for mystery box prize distribution.

    Parameters:
        winner_count: Number of winners per event (default: 1)
        expires_in_days: Days until prizes expire (default: 30)
        tier_boost: Dict of tier_id -> additional drop rate (e.g., {5: 0.10} adds 10% to legendary)
        eligibility: Dict with eligibility criteria:
            - min_tenure_days: Minimum days as employee
            - groups: List of required groups
            - job_codes: List of allowed job codes
            - exclude_recent_winners_days: Days to exclude previous winners
        prize_pool_filter: Dict to filter available prizes:
            - category_ids: List of category IDs
            - tier_ids: List of tier IDs
            - min_value: Minimum monetary value
            - max_value: Maximum monetary value
    """

    def __init__(
        self,
        winner_count: int = 1,
        expires_in_days: int = 30,
        tier_boost: Optional[Dict[int, float]] = None,
        eligibility: Optional[Dict[str, Any]] = None,
        prize_pool_filter: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        self.winner_count = winner_count
        self.expires_in_days = expires_in_days
        self.tier_boost = tier_boost or {}
        self.eligibility = eligibility or {}
        self.prize_pool_filter = prize_pool_filter or {}
        self.logger = logging.getLogger('Rewards.MysteryBox')

    async def evaluate(
        self,
        ctx: 'EvalContext',
        env: 'Environment',
        reward: 'RewardView'
    ) -> List[Dict[str, Any]]:
        """
        Evaluate and execute the mystery box event.

        Returns list of winners with their prizes.
        """
        try:
            service = MarketplaceService(
                connection=env.connection,
                logger=self.logger
            )

            # Execute mystery box
            result = await service.execute_mystery_box(
                event_name=f"Scheduled: {reward.reward}",
                winner_count=self.winner_count,
                eligibility_criteria=self.eligibility,
                tier_overrides=self._calculate_tier_rates(),
                expires_in_days=self.expires_in_days,
                linked_reward_id=reward.reward_id,
                created_by="scheduler"
            )

            if result.success:
                self.logger.info(
                    f"Mystery Box Event completed: {result.total_prizes_awarded} prizes awarded"
                )
                return result.winners
            else:
                self.logger.error(f"Mystery Box Event failed: {result.error}")
                return []

        except Exception as err:
            self.logger.error(f"Error in MysteryBoxRule evaluation: {err}")
            return []

    def _calculate_tier_rates(self) -> Dict[int, float]:
        """Apply tier boosts to base drop rates."""
        if not self.tier_boost:
            return {}

        # Convert boost values to proper decimal rates
        return {
            int(tier_id): float(boost)
            for tier_id, boost in self.tier_boost.items()
        }


class MysteryBoxReward:
    """
    Computed reward type for mystery box events.

    This integrates with the NAV-Rewards scheduler system to run
    automated mystery box events at configured intervals.
    """

    def __init__(
        self,
        reward: 'RewardView',
        rules: List[Any],
        conditions: Dict[str, Any] = None,
        job: Dict[str, Any] = None
    ):
        self._reward = reward
        self._rules = rules
        self._conditions = conditions or {}
        self._job = job or {}
        self.logger = logging.getLogger('Rewards.MysteryBoxReward')

        # Parse the mystery box rule
        self._mystery_rule = self._parse_mystery_rule()

    def _parse_mystery_rule(self) -> Optional[MysteryBoxRule]:
        """Parse the MysteryBoxRule from rules list."""
        for rule in self._rules:
            if isinstance(rule, (list, tuple)) and len(rule) >= 2:
                rule_name, rule_params = rule[0], rule[1]
                if rule_name == 'MysteryBoxRule':
                    return MysteryBoxRule(**rule_params)
        return MysteryBoxRule()  # Default

    @property
    def reward_type(self) -> str:
        return self._reward.reward_type

    @property
    def job_config(self) -> Dict[str, Any]:
        return self._job

    def is_enabled(self) -> bool:
        """Check if the mystery box reward is enabled."""
        return getattr(self._reward, 'is_enabled', True)

    async def execute(
        self,
        app,
        ctx: 'EvalContext' = None,
        env: 'Environment' = None
    ) -> List[Dict[str, Any]]:
        """
        Execute the mystery box event.

        This is called by the scheduler at configured intervals.
        """
        self.logger.info(
            f"Executing Mystery Box: {self._reward.reward}"
        )

        # Create environment if not provided
        if env is None:
            from ..rewards.base import Environment
            db = app.get('database')
            cache = app.get('cache')
            env = Environment(connection=db, cache=cache)

        try:
            winners = await self._mystery_rule.evaluate(
                ctx, env, self._reward
            )

            # Send notifications
            if winners:
                await self._notify_winners(app, winners)

            return winners

        except Exception as err:
            self.logger.error(f"Error executing mystery box: {err}")
            return []

    async def _notify_winners(
        self,
        app,
        winners: List[Dict[str, Any]]
    ):
        """Send notifications to mystery box winners."""
        try:
            # Import notification utilities
            from ..notifications.teams_webhook import TeamsWebhookNotifier

            notifier_config = app.get('teams_webhook_config')
            if notifier_config:
                notifier = TeamsWebhookNotifier(**notifier_config)

                for winner in winners:
                    await notifier.send_notification(
                        title="🎁 Mystery Box Winner!",
                        message=(
                            f"Congratulations! You've won a **{winner['tier']}** prize: "
                            f"**{winner['prize_name']}**!\n\n"
                            f"Check your Prize Wallet to redeem it."
                        ),
                        recipient_email=winner['user_email']
                    )

        except Exception as err:
            self.logger.warning(f"Failed to send winner notifications: {err}")


# ============================================================================
# SCHEDULER INTEGRATION
# ============================================================================

async def random_mystery_box_event(app, config: Dict[str, Any] = None):
    """
    Scheduled job function for mystery box events.

    This function is called by APScheduler at configured intervals.

    Usage in rewards engine:
        scheduler.add_job(
            random_mystery_box_event,
            'cron',
            minute='0,30',
            hour='9-17',
            args=[app],
            kwargs={'config': {...}}
        )

    Args:
        app: The aiohttp application
        config: Optional configuration override:
            - winner_count: Number of winners
            - event_name: Name for the event
            - expires_in_days: Prize expiration
            - eligibility: Eligibility criteria
    """
    logger = logging.getLogger('Rewards.MysteryBoxScheduler')

    config = config or {}

    try:
        db = app.get('database')
        service = MarketplaceService(connection=db, logger=logger)

        result = await service.execute_mystery_box(
            event_name=config.get('event_name', 'Scheduled Mystery Box'),
            winner_count=config.get('winner_count', 1),
            eligibility_criteria=config.get('eligibility'),
            tier_overrides=config.get('tier_overrides'),
            expires_in_days=config.get('expires_in_days', 30),
            linked_reward_id=config.get('linked_reward_id'),
            created_by='scheduler'
        )

        if result.success:
            logger.info(
                f"Scheduled Mystery Box completed: "
                f"{result.total_prizes_awarded} prizes to {len(result.winners)} winners"
            )
        else:
            logger.error(f"Scheduled Mystery Box failed: {result.error}")

    except Exception as err:
        logger.error(f"Error in scheduled mystery box: {err}")


async def expire_old_prizes(app):
    """
    Scheduled job to expire old prize awards.

    Should be run daily.
    """
    logger = logging.getLogger('Rewards.PrizeExpiration')

    try:
        db = app.get('database')
        service = MarketplaceService(connection=db, logger=logger)

        expired_count = await service.expire_old_awards()

        if expired_count > 0:
            logger.info(f"Expired {expired_count} old prize awards")

    except Exception as err:
        logger.error(f"Error expiring prizes: {err}")


def register_mystery_box_jobs(scheduler, app, timezone=None):
    """
    Register mystery box related scheduler jobs.

    Call this from your rewards engine setup:
        from rewards.marketplace.mystery_box import register_mystery_box_jobs
        register_mystery_box_jobs(self.scheduler, self.app, self._timezone)

    Args:
        scheduler: APScheduler instance
        app: aiohttp application
        timezone: Timezone for job scheduling
    """
    from datetime import timedelta

    # Workday mystery box events (every 30 min during work hours)
    scheduler.add_job(
        random_mystery_box_event,
        'cron',
        minute='0,30',
        hour='9-17',
        day_of_week='mon-fri',
        args=[app],
        kwargs={
            'config': {
                'event_name': 'Workday Mystery Box',
                'winner_count': 1,
                'expires_in_days': 30
            }
        },
        id='mystery_box_workday',
        name='Workday Mystery Box (Every 30min)',
        replace_existing=True,
        timezone=timezone,
        misfire_grace_time=60
    )

    # Daily prize expiration check
    scheduler.add_job(
        expire_old_prizes,
        'cron',
        hour=2,  # 2 AM
        args=[app],
        id='prize_expiration_check',
        name='Daily Prize Expiration',
        replace_existing=True,
        timezone=timezone
    )

    # Optional: Lunch time special (higher legendary rate)
    scheduler.add_job(
        random_mystery_box_event,
        'cron',
        hour=12,
        minute=0,
        day_of_week='mon-fri',
        args=[app],
        kwargs={
            'config': {
                'event_name': 'Lunch Special Mystery Box',
                'winner_count': 3,
                'expires_in_days': 30,
                'tier_overrides': {5: 0.08, 4: 0.15}  # Boosted rare drops
            }
        },
        id='mystery_box_lunch_special',
        name='Lunch Special Mystery Box',
        replace_existing=True,
        timezone=timezone
    )


# ============================================================================
# JSON CONFIGURATION EXAMPLES
# ============================================================================

MYSTERY_BOX_EXAMPLES = """
# Example Mystery Box Configurations for rewards.json

## Basic Mystery Box (runs every 30 min during work hours)
{
    "reward_id": 9000,
    "reward": "Workday Mystery Box",
    "description": "Random prizes awarded throughout the workday!",
    "points": 0,
    "reward_type": "Computed Badge",
    "reward_category": "Mystery Box",
    "reward_group": "Engagement",
    "multiple": true,
    "rules": [
        ["MysteryBoxRule", {
            "winner_count": 1,
            "expires_in_days": 30
        }]
    ],
    "job": {
        "trigger": "cron",
        "cron": {
            "minute": "0,30",
            "hour": "9-17",
            "day_of_week": "mon-fri"
        },
        "id": "mystery_box_workday",
        "name": "Workday Mystery Box",
        "timezone": "America/New_York"
    }
}

## Weekly Big Mystery Box (higher chances, more winners)
{
    "reward_id": 9001,
    "reward": "Friday Jackpot Mystery Box",
    "description": "Big weekly mystery box with boosted legendary chances!",
    "points": 0,
    "reward_type": "Computed Badge",
    "reward_category": "Mystery Box",
    "reward_group": "Weekly Events",
    "multiple": true,
    "rules": [
        ["MysteryBoxRule", {
            "winner_count": 10,
            "expires_in_days": 14,
            "tier_boost": {
                "5": 0.10,
                "4": 0.15
            },
            "eligibility": {
                "min_tenure_days": 30,
                "exclude_recent_winners_days": 7
            }
        }]
    ],
    "job": {
        "trigger": "cron",
        "cron": {
            "day_of_week": "fri",
            "hour": 16,
            "minute": 0
        },
        "id": "mystery_box_friday_jackpot",
        "name": "Friday Jackpot Mystery Box"
    }
}

## Monthly Premium Mystery Box
{
    "reward_id": 9002,
    "reward": "Monthly Premium Mystery Box",
    "description": "Exclusive monthly mystery box with premium prizes only!",
    "points": 0,
    "reward_type": "Computed Badge",
    "reward_category": "Mystery Box",
    "reward_group": "Monthly Events",
    "multiple": true,
    "rules": [
        ["MysteryBoxRule", {
            "winner_count": 5,
            "expires_in_days": 60,
            "tier_boost": {
                "5": 0.20,
                "4": 0.30,
                "3": 0.30,
                "2": 0.15,
                "1": 0.05
            },
            "prize_pool_filter": {
                "tier_ids": [3, 4, 5],
                "min_value": 50.00
            }
        }]
    ],
    "job": {
        "trigger": "cron",
        "cron": {
            "day": "last",
            "hour": 12,
            "minute": 0
        },
        "id": "mystery_box_monthly_premium",
        "name": "Monthly Premium Mystery Box"
    }
}

## Holiday Special Mystery Box (one-time)
{
    "reward_id": 9003,
    "reward": "Holiday Special Mystery Box",
    "description": "Special holiday mystery box event!",
    "points": 0,
    "reward_type": "Computed Badge",
    "reward_category": "Mystery Box",
    "reward_group": "Special Events",
    "rules": [
        ["MysteryBoxRule", {
            "winner_count": 50,
            "expires_in_days": 30,
            "tier_boost": {
                "5": 0.15,
                "4": 0.25
            }
        }]
    ],
    "job": {
        "trigger": "date",
        "run_date": "2025-12-25 10:00:00",
        "id": "mystery_box_holiday_2025",
        "name": "Holiday Special 2025"
    }
}
"""
