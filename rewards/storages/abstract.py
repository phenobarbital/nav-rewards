from abc import ABCMeta, abstractmethod
from typing import Optional
from datamodel.exceptions import ValidationError
from navconfig.logging import logging
from ..rewards import (
    RewardObject,
    ComputedReward,
    WorkflowReward,
    EventReward,
    ChallengeReward
)
from ..models import RewardView
from ..rewards.nomination import NominationAward
from ..rewards.nomination.models import CampaignStatus


class StorageError(Exception):
    """StorageError.
    """

class AbstractStorage(metaclass=ABCMeta):
    """AbstractStorage.

    Base class for Reward Storage.

    Raises:
        RuntimeError: Some exception raised.
        web.InternalServerError: Database connector is not installed.

    Returns:
        A collection of Rewards loaded from Storage(s).
    """
    def __init__(self) -> None:
        self._rewardobject = RewardObject
        self.logger = logging.getLogger(f'rewards.{__name__}')

    @abstractmethod
    async def load_rewards(self):
        """load_rewards.

        Load all Rewards from Storage.
        """

    @abstractmethod
    async def open(self):
        """open.

        Open the Storage Connection.
        """
        pass

    @abstractmethod
    async def close(self):
        """close.

        Close the Storage Connection.
        """
        pass

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    def _create_rewards(self, reward: dict) -> Optional[RewardObject]:
        """Create appropriate reward object based on reward type."""
        rules: list = reward.pop('rules', [])
        conditions: dict = reward.pop('conditions', {})
        job: dict = reward.pop('job', {})
        workflow: list = reward.pop('workflow', [])
        challenges: list = reward.pop('challenges', [])

        if not rules:
            rules = []
        # Safety check: ensure rules is a proper list
        if rules and not isinstance(rules, list):
            self.logger.warning(
                f"Rules should be a list, got {type(rules)}. Skipping rules for reward {reward.get('reward_id')}"  # noqa: E501
            )
            rules = []
        # Safety check: ensure each rule in rules is properly formatted
        if rules:
            cleaned_rules = []
            for rule in rules:
                if isinstance(rule, (list, dict)):
                    cleaned_rules.append(rule)
                else:
                    self.logger.warning(
                        f"Skipping invalid rule format: {type(rule)} for reward {reward.get('reward_id')}"  # noqa: E501
                    )
            rules = cleaned_rules
        try:
            r = RewardView(**reward)
            # Determine reward type and create appropriate object
            reward_type = r.reward_type
            if reward_type == "Nomination Badge":
                return self._create_nomination_reward(
                    r,
                    rules,
                    conditions,
                    reward
                )
            if workflow or reward_type == "Workflow Badge":
                completion_callbacks = reward.get('completion_callbacks', [])
                step_callbacks = reward.get('step_callbacks', {})
                auto_evaluation = reward.get('auto_evaluation', True)
                return WorkflowReward(
                    reward=r,
                    rules=rules,
                    conditions=conditions,
                    workflow=workflow,
                    completion_callbacks=completion_callbacks,
                    step_callbacks=step_callbacks,
                    auto_evaluation=auto_evaluation
                )
            if reward_type == 'Computed Badge':
                return ComputedReward(
                    reward=r,
                    rules=rules,
                    conditions=conditions,
                    job=job
                )
            if r.events or reward_type in ["Automated Badge", "Recognition Badge"]:  # noqa: E501
                return EventReward(
                    reward=r,
                    rules=rules,
                    conditions=conditions
                )
            if challenges:
                return ChallengeReward(
                    r,
                    rules,
                    conditions,
                    challenges=challenges
                )
            return self._rewardobject(
                reward=r,
                rules=rules,
                conditions=conditions
            )
        except ValueError as exc:
            self.logger.error(
                f"Value Error {reward!r}, Error: {exc}"
            )
            return None
        except ValidationError as exc:
            self.logger.error(
                f"Error validating Reward {reward!r}, Error: {exc.payload}"
            )
            return None
        except Exception as exc:
            self.logger.error(
                f"Error creating Reward {reward!r}, Error: {exc}"
            )
            return None

    def _create_nomination_reward(
        self,
        reward: RewardView,
        rules: list,
        conditions: dict,
        reward_data: dict
    ) -> Optional[NominationAward]:
        """Create a nomination reward object."""
        try:
            nomination_config = reward_data.get('nomination_config', {})

            # Create workflow steps for nomination process
            workflow_steps = [
                {"step": "Nomination Phase"},
                {"step": "Voting Phase"},
                {"step": "Winner Selection"}
            ]

            return NominationAward(
                reward=reward,
                rules=rules,
                conditions=conditions,
                nomination_config=nomination_config,
                workflow=workflow_steps
            )

        except Exception as err:
            self.logger.error(
                f"Error creating nomination reward: {err}"
            )
            return None
