import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta

# Mock navconfig and other external dependencies before they're imported
sys.modules['navconfig'] = MagicMock()
sys.modules['navconfig.logging'] = MagicMock()
sys.modules['notify'] = MagicMock()
sys.modules['notify.providers'] = MagicMock()
sys.modules['notify.providers.teams'] = MagicMock()
sys.modules['notify.providers.ses'] = MagicMock()
sys.modules['notify.models'] = MagicMock()
sys.modules['navigator_auth'] = MagicMock()
sys.modules['navigator_auth.models'] = MagicMock()
sys.modules['navigator_auth.conf'] = MagicMock()
sys.modules['navigator_auth.libs'] = MagicMock()
sys.modules['navigator_auth.libs.json'] = MagicMock()
sys.modules['navigator'] = MagicMock()
sys.modules['navigator.views'] = MagicMock()
sys.modules['transitions'] = MagicMock()
sys.modules['aiormq'] = MagicMock()


from rewards.rewards.base import RewardObject
from rewards.models import RewardView
from rewards.env import Environment

# Mock user object for testing
class MockUser:
    def __init__(self, user_id):
        self.user_id = user_id

@pytest.mark.asyncio
async def test_has_awarded_timeframe_none():
    """
    Tests that has_awarded returns False when timeframe is None and cooldown has passed.
    """
    # 1. Set up a RewardObject
    reward_view = RewardView(
        reward_id=1,
        reward="Test Reward",
        multiple=True,
        timeframe=None,
        cooldown_minutes=5,
        reward_category="Test Category"
    )
    reward_object = RewardObject(reward=reward_view)

    # 2. Mock the database connection
    mock_conn = AsyncMock()
    # Simulate a previous award that is outside the cooldown period
    previous_award_time = datetime.now() - timedelta(minutes=10)
    mock_conn.fetch_all.return_value = [
        {'awarded_at': previous_award_time, 'giver_user': 123}
    ]

    # 3. Create user and environment objects
    user = MockUser(user_id=1)
    env = Environment()

    # 4. Call has_awarded
    result = await reward_object.has_awarded(user, env, mock_conn)

    # 5. Assert the result is True
    assert result is True

@pytest.mark.asyncio
async def test_has_awarded_timeframe_none_within_cooldown():
    """
    Tests that has_awarded returns True when timeframe is None and within cooldown.
    """
    # 1. Set up a RewardObject
    reward_view = RewardView(
        reward_id=1,
        reward="Test Reward",
        multiple=True,
        timeframe=None,
        cooldown_minutes=15,
        reward_category="Test Category"
    )
    reward_object = RewardObject(reward=reward_view)

    # 2. Mock the database connection
    mock_conn = AsyncMock()
    # Simulate a previous award that is inside the cooldown period
    previous_award_time = datetime.now() - timedelta(minutes=5)
    mock_conn.fetch_all.return_value = [
        {'awarded_at': previous_award_time, 'giver_user': 123}
    ]

    # 3. Create user and environment objects
    user = MockUser(user_id=1)
    env = Environment()

    # 4. Call has_awarded
    result = await reward_object.has_awarded(user, env, mock_conn)

    # 5. Assert the result is True
    assert result is True

@pytest.mark.asyncio
async def test_has_awarded_daily_timeframe_already_awarded():
    """
    Tests that has_awarded returns True when timeframe is 'daily' and the user has already been awarded today.
    """
    reward_view = RewardView(
        reward_id=2,
        reward="Daily Reward",
        multiple=True,
        timeframe='daily',
        cooldown_minutes=0,
        reward_category="Test Category"
    )
    reward_object = RewardObject(reward=reward_view)

    mock_conn = AsyncMock()
    previous_award_time = datetime.now() - timedelta(hours=2)
    mock_conn.fetch_all.return_value = [{'awarded_at': previous_award_time, 'giver_user': 123}]

    user = MockUser(user_id=2)
    env = Environment()

    result = await reward_object.has_awarded(user, env, mock_conn)

    assert result is True


@pytest.mark.asyncio
async def test_has_awarded_daily_timeframe_not_awarded():
    """
    Tests that has_awarded returns False when timeframe is 'daily' and the user has not been awarded today.
    """
    reward_view = RewardView(
        reward_id=2,
        reward="Daily Reward",
        multiple=True,
        timeframe='daily',
        cooldown_minutes=0,
        reward_category="Test Category"
    )
    reward_object = RewardObject(reward=reward_view)

    mock_conn = AsyncMock()
    previous_award_time = datetime.now() - timedelta(days=1)
    mock_conn.fetch_all.return_value = [{'awarded_at': previous_award_time, 'giver_user': 123}]

    user = MockUser(user_id=2)
    env = Environment()

    result = await reward_object.has_awarded(user, env, mock_conn)

    assert result is False


@pytest.mark.asyncio
async def test_has_awarded_hourly_timeframe_already_awarded():
    """
    Tests that has_awarded returns True when timeframe is 'hourly' and the user has already been awarded this hour.
    """
    reward_view = RewardView(
        reward_id=3,
        reward="Hourly Reward",
        multiple=True,
        timeframe='hourly',
        cooldown_minutes=0,
        reward_category="Test Category"
    )
    reward_object = RewardObject(reward=reward_view)

    mock_conn = AsyncMock()
    previous_award_time = datetime.now() - timedelta(minutes=30)
    mock_conn.fetch_all.return_value = [{'awarded_at': previous_award_time, 'giver_user': 123}]

    user = MockUser(user_id=3)
    env = Environment()

    result = await reward_object.has_awarded(user, env, mock_conn)

    assert result is True


@pytest.mark.asyncio
async def test_has_awarded_hourly_timeframe_not_awarded():
    """
    Tests that has_awarded returns False when timeframe is 'hourly' and the user has not been awarded this hour.
    """
    reward_view = RewardView(
        reward_id=3,
        reward="Hourly Reward",
        multiple=True,
        timeframe='hourly',
        cooldown_minutes=1,
        reward_category="Test Category"
    )
    reward_object = RewardObject(reward=reward_view)

    mock_conn = AsyncMock()
    previous_award_time = datetime.now() - timedelta(hours=1)
    mock_conn.fetch_all.return_value = [{'awarded_at': previous_award_time, 'giver_user': 123}]

    user = MockUser(user_id=3)
    env = Environment()

    result = await reward_object.has_awarded(user, env, mock_conn)

    assert result is True
