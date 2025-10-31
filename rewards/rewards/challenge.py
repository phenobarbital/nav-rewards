from collections.abc import Iterable
from typing import Optional, Any
import aiormq
from datamodel import BaseModel, Field
from navigator_auth.libs.json import json_encoder, json_decoder
from resources.users import User
from .event import EventReward
from ..models import (
    RewardView,
)
from ..context import EvalContext
from ..env import Environment


class ChallengeStep(BaseModel):
    step: str
    args: dict[str, Any] = Field(default_factory=dict)
    completed: bool = Field(default=False)

class ChallengeReward(EventReward):
    """ChallengeReward.

    This is the ChallengeReward class.


    Args:
        RewardObject (RewardObject): RewardObject.

    Returns:
        ChallengeReward: a ChallengeReward.
    """
    type: str = 'challenge'

    def __init__(
        self,
        reward: RewardView,
        rules: Optional[list] = None,
        conditions: Optional[dict] = None,
        challenges: list[dict] = None,
        **kwargs
    ) -> None:
        super().__init__(reward, rules, conditions, **kwargs)
        self.challenges = self._parse_challenges(challenges)
        self._num_challenges = len(challenges)
        # Optimization: Create a set of step names from challenges
        self.step_names = {challenge.step for challenge in self.challenges}

    def _parse_challenges(self, challenges: list[dict]) -> list[ChallengeStep]:
        return [ChallengeStep(**c) for c in challenges]

    async def evaluate_event(
        self,
        data: Iterable,
        event: aiormq.abc.DeliveredMessage,
        env: Environment
    ) -> User:
        # Use "data" to obtain the User:
        user_id = data.get('user_id', None)
        result = []
        async with await env.connection.acquire() as conn:
            User.Meta.connection = conn
            user = await User.get(user_id=user_id)
            ctx, _ = self.get_user_context(user)
            ctx.event = data
            result.append(ctx)
        return result

    def is_completed(self, userdata) -> bool:
        return all(
            challenge_data.completed for challenge_data in userdata['steps']
        )

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        """
        Evaluates the Reward against the criteria.

        :param ctx: The evaluation context, containing user and session
           information.
        :param environ: The environment information, such as the current time.
        :return: True if this Reward can be applied to User.
        """
        # 1. Load user's state from the database
        userdata = await self.get_user_data(ctx, env)
        if self.is_completed(userdata):
            if self._reward.multiple is True:
                # erasing the user's state
                await self.del_user_data(ctx, env)
                # and retrieve again the user data:
                userdata = await self.get_user_data(ctx, env)
            else:
                # User already completed this Challenge
                return False
        # Update Progress
        current_step = ctx.event.get('step')
        if current_step in self.step_names:
            # Step is valid, update the user's progress
            for challenge_data in userdata['steps']:
                if challenge_data.step == current_step:
                    # TODO: also evaluate if the step
                    # is valid based on attributes
                    if await self.check_completion(userdata):
                        challenge_data.completed = True
                        await self._progress_challenge(
                            ctx,
                            env,
                            userdata
                        )
                    break
        else:
            # Step is invalid, ignore
            return False
        # Check if all steps are completed
        if self.is_completed(userdata):
            self.logger.notice(
                f"Challenge {self._reward.reward_id} \
                has been completed by {ctx.user.username}"

            )
            return True  # Reward can be applied
        else:
            return False

    async def get_user_data(self, ctx: EvalContext, env: Environment):
        # Load user's workflow state from the database
        # TODO: Using Database or Redis
        key = f"{ctx.user.username}:{ctx.user.user_id}"
        if await env.cache.exists(key):
            # User Exists:
            user_data = await env.cache.hget(key, 'rewards')
            rewards = json_decoder(user_data)
            try:
                reward = rewards[f"{self._reward.reward_id}"]
            except (TypeError, KeyError, ValueError):
                # Starting with Reward info:
                rewards[f"{self._reward.reward_id}"] = {
                    'steps': self.challenges,
                    'progress': 0
                }
        else:
            # User does not exist and need to be created:
            user_data = {
                'user_id': ctx.user.user_id,
                'username': ctx.user.username,
                'email': ctx.user.email,
                'rewards': {
                    f"{self._reward.reward_id}": {
                        'steps': self.challenges,
                        'progress': 0
                    }
                },
            }
            # Serialize the rewards dictionary
            user_data['rewards'] = json_encoder(user_data['rewards'])
            try:
                await env.cache.hset(
                    key,
                    mapping=user_data
                )
            except Exception as e:
                print(e)
            rewards = user_data['rewards']
        # Deserialize steps
        if 'steps' in reward:  # Check if 'steps' key exists
            reward['steps'] = [
                ChallengeStep(**step_data) for step_data in reward['steps']
            ]
        return rewards[f"{self._reward.reward_id}"]

    async def check_completion(self, user_data):
        # Implement logic to check criteria against user_data
        # ...
        return True  # If the challenge has been completed

    async def _progress_challenge(
        self,
        ctx: EvalContext,
        env: Environment,
        userdata: dict
    ):
        # Saving the state to the database (or cache)
        userdata['progress'] += 1
        key = f"{ctx.user.username}:{ctx.user.user_id}"
        try:
            user = await env.cache.hget(key, 'rewards')
            rewards = json_decoder(user)
            rewards[f"{self._reward.reward_id}"] = userdata
            await env.cache.hset(
                key,
                'rewards',
                json_encoder(rewards)
            )
        except Exception as err:
            self.logger.erro(
                f"Error Saving Challenge State: {err}"
            )
            raise

    async def del_user_data(self, ctx: EvalContext, env: Environment):
        key = f"{ctx.user.username}:{ctx.user.user_id}"
        rewards = json_decoder(
            await env.cache.hget(key, 'rewards')
        )
        try:
            del rewards[f"{self._reward.reward_id}"]
        except KeyError:
            pass
        # Set the Rewards Tree to the cache
        await env.cache.hset(
            key,
            'rewards',
            json_encoder(rewards)
        )
