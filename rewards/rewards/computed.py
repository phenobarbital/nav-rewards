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
                    await self.apply(ctx, env, conn)
        return True

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
        args = {
            "reward_id": self._reward.reward_id,
            "reward": self._reward.reward,
            "receiver_user": ctx.user.user_id,
            "receiver_email": ctx.user.email,
            "receiver_id": ctx.user.user_id,
            "receiver_employee": ctx.user.associate_id,
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
