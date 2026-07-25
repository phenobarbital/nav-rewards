"""Regression tests for the navrules migration (PR-2/PR-3).

Covers the fits() multi-rule bug (a), rule loading via RuleLoader, and
availability evaluation via AvailabilityWindow.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from navrules import RuleLoadError

from rewards.context import EvalContext
from rewards.env import Environment
from rewards.rewards.base import RewardObject
from rewards.rules.abstract import AbstractRule

MONDAY = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)


class PassRule(AbstractRule):
    def fits(self, ctx, env):
        return True

    async def evaluate(self, ctx, env):
        return True


class FailRule(AbstractRule):
    def fits(self, ctx, env):
        return False

    async def evaluate(self, ctx, env):
        return False


class BoomRule(AbstractRule):
    def fits(self, ctx, env):
        raise RuntimeError("boom")

    async def evaluate(self, ctx, env):
        return True


def fake_reward(**overrides) -> SimpleNamespace:
    base = dict(
        reward_id=999,
        reward="Test Badge",
        description="test",
        reward_type="Recognition Badge",
        timeframe=None,
        events=[],
        programs=[],
        assigner=None,
        awardee=[],
        availability_rule={},
        multiple=False,
        is_enabled=True,
        emoji=None,
        message=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def make_ctx() -> EvalContext:
    return EvalContext(
        request=None,
        user={"email": "e@x.co"},
        session={"user_id": 1, "email": "e@x.co"},
    )


class TestFitsAllRules:
    """Bug (a): fit_rules was overwritten per iteration — only the last
    rule counted. Now it must be the AND of ALL rules."""

    def test_failing_rule_first_no_longer_masked(self):
        reward = RewardObject(
            reward=fake_reward(), rules=[FailRule(), PassRule()]
        )
        assert reward.fits(make_ctx(), Environment(timestamp=MONDAY)) is False
        failed = reward.failed_conditions()
        assert "fit_rules" in failed

    def test_failing_rule_last_still_fails(self):
        reward = RewardObject(
            reward=fake_reward(), rules=[PassRule(), FailRule()]
        )
        assert reward.fits(make_ctx(), Environment(timestamp=MONDAY)) is False

    def test_all_passing_fits(self):
        reward = RewardObject(
            reward=fake_reward(), rules=[PassRule(), PassRule()]
        )
        assert reward.fits(make_ctx(), Environment(timestamp=MONDAY)) is True

    def test_raising_rule_counts_as_failure(self):
        reward = RewardObject(
            reward=fake_reward(), rules=[BoomRule(), PassRule()]
        )
        assert reward.fits(make_ctx(), Environment(timestamp=MONDAY)) is False


class TestRuleLoading:
    def test_load_by_class_name_list(self):
        reward = RewardObject(
            reward=fake_reward(), rules=[["EarlyBirdRule"]]
        )
        assert len(reward._rules) == 1
        assert reward._rules[0].name == "Early Bird"

    def test_load_from_dict_spec(self):
        reward = RewardObject(
            reward=fake_reward(),
            rules=[{"rule_type": "OptimalTimingRule", "min_score": 9}],
        )
        assert reward._rules[0].min_score == 9

    def test_spec_list_not_mutated(self):
        spec = ["EarlyBirdRule", {}]
        RewardObject(reward=fake_reward(), rules=[spec])
        assert spec[0] == "EarlyBirdRule"

    def test_invalid_rule_raises(self):
        with pytest.raises(RuleLoadError):
            RewardObject(reward=fake_reward(), rules=[["NoSuchRule"]])


class TestAvailabilityWindow:
    def test_time_window(self):
        reward = RewardObject(
            reward=fake_reward(
                availability_rule={
                    "start_time": "09:00:00", "end_time": "17:00:00"
                }
            )
        )
        assert reward.evaluate_environment(Environment(timestamp=MONDAY)) is True
        night = datetime(2026, 7, 20, 22, 0, tzinfo=timezone.utc)
        assert reward.evaluate_environment(Environment(timestamp=night)) is False

    def test_attribute_matching(self):
        reward = RewardObject(
            reward=fake_reward(availability_rule={"quarter": ["Q3", "Q4"]})
        )
        assert reward.evaluate_environment(Environment(timestamp=MONDAY)) is True
        feb = datetime(2026, 2, 2, tzinfo=timezone.utc)
        assert reward.evaluate_environment(Environment(timestamp=feb)) is False


class TestEvaluate:
    async def test_evaluate_all_rules_and(self):
        reward = RewardObject(
            reward=fake_reward(), rules=[PassRule(), FailRule()]
        )
        reward._failed_conditions = []
        ok = await reward.evaluate(make_ctx(), Environment(timestamp=MONDAY))
        assert ok is False

    async def test_evaluate_all_passing(self):
        reward = RewardObject(
            reward=fake_reward(), rules=[PassRule(), PassRule()]
        )
        reward._failed_conditions = []
        ok = await reward.evaluate(make_ctx(), Environment(timestamp=MONDAY))
        assert ok is True
