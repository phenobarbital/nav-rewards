from typing import Dict, Any
from datetime import datetime, timedelta
from ...rules.abstract import AbstractRule
from ...context import EvalContext
from ...env import Environment
from .models import NominationCampaign


class NominationEligibilityRule(AbstractRule):
    """Rule to check nomination eligibility based on various criteria."""

    def __init__(self, conditions: Dict = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "NominationEligibility"
        self.description = "Check if user meets nomination eligibility criteria"  # noqa

        # Configuration options
        self.check_tenure = kwargs.get('check_tenure', False)
        self.min_tenure_days = kwargs.get('min_tenure_days', 30)
        self.check_recent_winners = kwargs.get('check_recent_winners', False)
        self.recent_winner_months = kwargs.get('recent_winner_months', 6)
        self.check_performance = kwargs.get('check_performance', False)
        self.required_job_codes = kwargs.get('required_job_codes', [])
        self.excluded_job_codes = kwargs.get('excluded_job_codes', [])

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        """Check if rule applies to this context."""
        return bool(ctx.user)

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        """Evaluate nomination eligibility."""
        user = ctx.user

        try:
            # Check tenure requirement
            if self.check_tenure and not await self._check_tenure(user, env):
                return False

            # Check recent winner exclusion
            if self.check_recent_winners and await self._is_recent_winner(user, env):  # noqa
                return False

            # Check job code requirements
            if self.required_job_codes:
                user_job_code = getattr(user, 'job_code', None)
                if user_job_code not in self.required_job_codes:
                    return False

            # Check job code exclusions
            if self.excluded_job_codes:
                user_job_code = getattr(user, 'job_code', None)
                if user_job_code in self.excluded_job_codes:
                    return False

            return True

        except Exception as err:
            self.logger.error(
                f"Error evaluating nomination eligibility: {err}"
            )
            return False

    async def _check_tenure(self, user, env: Environment) -> bool:
        """Check if user meets minimum tenure requirement."""
        try:
            start_date = getattr(user, 'start_date', None)
            if not start_date:
                return False

            if isinstance(start_date, str):
                start_date = datetime.fromisoformat(start_date)
            elif hasattr(start_date, 'date'):
                start_date = start_date.date()

            tenure_days = (env.timestamp.date() - start_date).days
            return tenure_days >= self.min_tenure_days

        except Exception as err:
            self.logger.error(f"Error checking tenure: {err}")
            return False

    async def _is_recent_winner(self, user, env: Environment) -> bool:
        """Check if user won a nomination award recently."""
        try:
            cutoff_date = env.timestamp - timedelta(
                days=self.recent_winner_months * 30
            )

            async with await env.connection.acquire() as conn:
                query = """
                    SELECT COUNT(*)
                    FROM rewards.users_rewards ur
                    JOIN rewards.rewards r ON ur.reward_id = r.reward_id
                    WHERE ur.receiver_user = $1
                    AND r.reward_type = 'Nomination Badge'
                    AND ur.awarded_at >= $2
                """
                count = await conn.fetchval(query, user.user_id, cutoff_date)
                return count > 0

        except Exception as err:
            self.logger.error(
                f"Error checking recent winners: {err}"
            )
            return False


class NominationPhaseRule(AbstractRule):
    """Rule to check if nomination is in the correct phase."""

    def __init__(self, conditions: Dict = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "NominationPhase"
        self.description = "Check if nomination campaign is in correct phase"
        self.required_phase = kwargs.get('required_phase', 'nomination')
        self.campaign_id = kwargs.get('campaign_id')

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        """Check if rule applies to this context."""
        return bool(self.campaign_id)

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        """Check if campaign is in required phase."""
        try:
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=self.campaign_id
                )

                # Check phase
                if campaign.status.value != self.required_phase:
                    return False

                # Check timing
                now = env.timestamp
                if self.required_phase == 'nomination':
                    return campaign.nomination_start <= now <= campaign.nomination_end  # noqa
                elif self.required_phase == 'voting':
                    return campaign.voting_start <= now <= campaign.voting_end

                return True

        except Exception as err:
            self.logger.error(
                f"Error checking nomination phase: {err}"
            )
            return False
