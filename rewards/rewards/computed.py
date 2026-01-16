from typing import Optional, Any
from aiohttp import web
from asyncdb.exceptions import DriverError
from datamodel.exceptions import ValidationError
from .base import RewardObject
from ..models import (
    RewardView,
    UserReward
)
from ..context import EvalContext
from ..env import Environment


class ComputedReward(RewardObject):
    """ComputedReward.

    Computed Reward.

    Args:
        RewardObject (RewardObject): RewardObject.

    Returns:
        ComputedReward: ComputedReward.
    """
    def __init__(
        self,
        reward: RewardView,
        rules: Optional[list] = None,
        conditions: Optional[dict] = None,
        job: Optional[dict] = None,
        **kwargs
    ) -> None:
        super().__init__(reward, rules, conditions, **kwargs)
        # We cannot Allow JOBs on non-Computed Badges
        # Job (for computed Rewards):
        self._job = job

    def __repr__(self) -> str:
        return f'ComputedReward({self._reward} - {self._job})'

    @property
    def job(self):
        return self._job

    async def call_reward(self, app: web.Application, **kwargs):
        try:
            system = app['reward_engine']
        except Exception as err:
            raise RuntimeError(
                f"Reward System is not installed: {err}"
            ) from err
        env = Environment(
            connection=system.connection,
            cache=system.get_cache(),
        )
        candidates = []
        awarded_users = []  # Track awarded users for webhook notification
        for rule in self._rules:
            # Computed Reward:
            if rule.fits_computed(env):
                candidates = await rule.evaluate_dataset(env)
            async with await env.connection.acquire() as conn:
                for ctx in candidates:
                    user = ctx.user
                    if not self.fits(ctx=ctx, env=env):
                        continue
                    if not await self.check_awardee(ctx):
                        continue
                    if await self.has_awarded(user, env, conn, self.timeframe):
                        continue
                    # Apply reward to User
                    result, error = await self.apply(ctx, env, conn)
                    if result and not error:
                        # Collect user info for webhook notification
                        awarded_users.append({
                            'display_name': getattr(user, 'display_name', user.email),
                            'email': user.email,
                            'years_employed': ctx.args.get('years_employed') if hasattr(ctx, 'args') else None
                        })
        
        # Send Teams webhook notification if configured
        if awarded_users:
            await self._send_teams_webhook_notification(awarded_users)
        
        return True

    async def _send_teams_webhook_notification(self, awarded_users: list) -> None:
        """Send Teams webhook notification for awarded users.
        
        Args:
            awarded_users: List of user dicts that were awarded.
        """
        # Check if teams_webhook is configured in the reward
        teams_webhook = getattr(self._reward, 'teams_webhook', None)
        if not teams_webhook:
            # Check in attributes dict as fallback
            attributes = getattr(self._reward, 'attributes', {}) or {}
            teams_webhook = attributes.get('teams_webhook')
        
        if not teams_webhook:
            return  # No webhook configured
        
        try:
            from ..notifications.teams_webhook import TeamsWebhook
            webhook = TeamsWebhook(teams_webhook)
            
            reward_name = self._reward.reward
            reward_icon = getattr(self._reward, 'icon', None)
            reward_category = getattr(self._reward, 'reward_category', '')
            
            # Determine notification type based on reward category or name
            if 'birthday' in reward_name.lower() or 'birthday' in str(reward_category).lower():
                await webhook.send_birthday_notification(
                    users=awarded_users,
                    reward_name=reward_name,
                    reward_icon=reward_icon
                )
            elif 'anniversary' in reward_name.lower() or 'anniversary' in str(reward_category).lower():
                await webhook.send_anniversary_notification(
                    users=awarded_users,
                    reward_name=reward_name,
                    reward_icon=reward_icon
                )
            else:
                # Generic notification for other computed rewards
                await webhook.send_birthday_notification(
                    users=awarded_users,
                    reward_name=reward_name,
                    reward_icon=reward_icon
                )
            
            self.logger.info(
                f"Teams webhook notification sent for {len(awarded_users)} users"
            )
        except Exception as exc:
            self.logger.error(
                f"Error sending Teams webhook notification: {exc}"
            )

    async def apply(
        self,
        ctx: EvalContext,
        env: Environment,
        conn: Any,
        **kwargs
    ) -> bool:
        """
        Apply the Reward to the User.

        :param ctx: The evaluation context, containing user and session
        information.
        :param environ: The environment information, such as the current time.
        :return: True if the reward was successfully applied.
        """
        # Computed Reward:
        kwargs['message'] = kwargs.pop(
            'message',
            await self._reward_message(ctx, env, ctx.user)
        )
        userid = ctx.user.user_id
        email = ctx.user.email
        args = {
            "reward_id": self._reward.reward_id,
            "reward": self._reward.reward,
            "receiver_user": userid,
            "receiver_email": email,
            "receiver_id": userid,
            "receiver_employee": getattr(ctx.user, 'associate_id', email),
            "points": self._reward.points,
            "awarded_at": env.timestamp,
            **kwargs
        }
        error = None
        try:
            UserReward.Meta.connection = conn
            reward = UserReward(**args)
            print('AWARD > ', reward)
            a = await reward.insert()
            self.logger.notice(
                f"User {ctx.user.email} has been "
                f"awarded with {self._reward.reward} at {a.awarded_at}"
            )
            return a, error
        except ValidationError as err:
            error = {
                "message": "Error Validating Reward Payload",
                "error": err.payload,
            }
            return None, error
        except DriverError as err:
            error = {
                "message": "Error on Rewards Database",
                "error": str(err),
            }
            return None, error
        except Exception as err:
            error = {
                "message": "Error Creating Reward",
                "error": str(err),
            }
            return None, error
